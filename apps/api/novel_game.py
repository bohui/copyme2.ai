"""Confirmed scenes → resumable NovelToGame stages → verified Memoir RPG data."""
import asyncio
import hashlib
from importlib import import_module
import json
import os
from pathlib import Path
import sys
import tempfile
import time

import httpx

from .higgsfield_game import load_build_packet
from .model_request import instruction_manifest, manifest_metadata
from .novel_game_bundle import assets, journey, scene_library, validate_bundle, validate_style
from .prompt_artifact import load_prompt_artifact, prompt_path
from .story_game_runtime import GameFence, GamePublication, GameRequestBody
from .story_game_selection import selected_scenes, validate_brief

runner = import_module('experiments.novel-to-game.stages')
ROOT = journey.PACKAGE.parents[1]
MODEL = 'gpt-6.1-sol'
STAGES = ('analyze', 'concept', 'design', 'whitebox', 'art', 'production')


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def fingerprint(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def dependency_snapshot():
    root = ROOT/'deps/novel-to-game'
    lock = json.loads((ROOT/'deps/novel-to-game.lock.json').read_text())
    files = {p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted((root/'skills').rglob('*.md'))}
    if not files or files != lock['files']:
        raise ValueError('game_novel_dependency_changed; run make deps-install or review make deps-update')
    return lock


def confirmed_source(packet):
    """Selection is the adaptation boundary, including multiple options from one chapter."""
    selected = selected_scenes(packet)['scenes']
    events = {e['id']:e for e in packet['timeline']}
    chapters, timeline = [], []
    for i,scene in enumerate(selected):
        chapter_id, event_id = 'selected-'+str(i+1), 'event-'+str(i+1)
        linked = [events[e] for e in scene['event_ids']]
        event = {k:linked[0][k] for k in ('age','life_stage','year','date','uncertainty')
                 if k in linked[0] and all(e.get(k)==linked[0][k] for e in linked)}
        temporal = {k:v for k,v in (linked[0].get('temporal') or {}).items()
                    if k in ('expression','precision','year_start','year_end')}
        if temporal and all({k:v for k,v in (e.get('temporal') or {}).items() if k in temporal}==temporal for e in linked):
            event['temporal']=temporal
            if not event.get('age') and temporal.get('precision')=='age':
                from .memory_events import _memory_age_number
                age=_memory_age_number(temporal.get('expression',''))
                if age is not None and 0<=age<=120: event['age']=dict(minimum=age,maximum=age)
        event.update(id=event_id, formal_chapter_id=chapter_id, title=scene['title'])
        chapters.append(dict(chapter_id=chapter_id,event_ids=[event_id],blocks=[dict(text=scene['quote'])]))
        timeline.append(event)
    return dict(chapters=chapters,timeline=timeline,locale=packet['authority']['locale'],
        title='A life, one journey',fictional=packet.get('fictional',False))


async def checkpoint(fence, stage, signature, value=None):
    from psycopg import AsyncConnection
    async with await AsyncConnection.connect(os.environ['MEMOIR_PUBLICATION_DATABASE_URL'],connect_timeout=2) as connection:
        await connection.execute('set local role service_role')
        await connection.execute("set local lock_timeout='2s'")
        if value is None:
            cursor = await connection.execute('select public.read_story_game_stage(%s,%s,%s,%s)',
                (fence.game_id,fence.token,stage,signature))
        else:
            cursor = await connection.execute('select public.save_story_game_stage(%s,%s,%s,%s,%s::jsonb)',
                (fence.game_id,fence.token,stage,signature,canonical(value)))
        return (await cursor.fetchone())[0]


async def browser_verify(workspace, stage, *, phone=False):
    command = ([sys.executable,str(journey.PACKAGE/'journey_checks.py'),'--output',str(workspace)] if stage=='journey' else
        [sys.executable,str(journey.PACKAGE/'verify.py'),'--output',str(workspace),'--stage',stage])
    if phone: command.append('--phone')
    process = await asyncio.create_subprocess_exec(*command,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
    try:
        stdout,stderr = await asyncio.wait_for(process.communicate(),timeout=300)
    except BaseException:
        process.kill(); await process.wait(); raise
    folder = workspace/('qa' if stage=='production' else 'qa/whitebox')
    if phone: folder = folder/'phone'
    receipt_path=workspace/'qa/journey-checks.json' if stage=='journey' else folder/'verification.json'
    receipt = json.loads(receipt_path.read_text()) if receipt_path.exists() else {}
    assets.write_bytes(workspace,'qa/'+stage+('-phone' if phone else '')+'-process.log',stdout+stderr)
    if process.returncode or receipt.get('status')!='PASS':
        raise ValueError('game_browser_verification_failed')
    return receipt if stage=='journey' else {k:receipt[k] for k in ('status','checks')}


async def model_stage(body, fence, *, transport=None, issue14_admission=None, observer=None,prompt_manifest=None):
    from .issue14_execution_admission import check_issue14_dispatch
    from .lifetime_memory_lane_engine import check_lane_generation
    from .llm_tracing import trace_llm_call, update_llm_trace
    check_issue14_dispatch(issue14_admission,role='tool_loop')
    check_lane_generation()
    base,key = os.getenv('MEMORY_SPARK_LLM_BASE_URL','').rstrip('/'),os.getenv('MEMORY_SPARK_LLM_API_KEY','')
    from urllib.parse import urlsplit
    parsed = urlsplit(base)
    if not key or parsed.scheme not in {'http','https'} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('game_provider_unavailable')
    encoded = canonical(body).encode()
    if observer: observer('request',body)
    request = GameRequestBody(encoded,publisher=GamePublication(os.getenv('MEMOIR_PUBLICATION_DATABASE_URL')),
        fence=fence.model_dump(mode='json'))
    try:
        with trace_llm_call('story.game.novel.'+body['metadata']['stage'],MODEL,
                metadata={'prompt_manifest':prompt_manifest or body['metadata']}) as trace:
            async with httpx.AsyncClient(trust_env=False,follow_redirects=False,timeout=590,
                    **({'transport':transport} if transport is not None else {})) as client:
                async with client.stream('POST',base+'/responses',content=request,
                        headers={'Authorization':'Bearer '+key,'Content-Type':'application/json','Content-Length':str(len(encoded))}) as response:
                    response.raise_for_status()
                    result = None
                    received = 0
                    started,last_update=time.monotonic(),0
                    async for line in response.aiter_lines():
                        received += len(line)
                        if received>2_000_000 or key in line:
                            raise ValueError('game_response_limit_or_secret')
                        if line.startswith('data:') and line[5:].strip()!='[DONE]':
                            event=json.loads(line[5:])
                            if observer and time.monotonic()-last_update>2:
                                observer('progress',dict(stage=body['metadata']['stage'],event=event.get('type'),seconds=round(time.monotonic()-started,1)))
                                last_update=time.monotonic()
                            if event.get('type')=='response.completed':
                                result=event['response']
                                if observer: observer('response',result)
                                break
                            elif event.get('type') in ('error','response.failed','response.incomplete'):
                                if observer: observer('response',event.get('response',event))
                                raise ValueError('incomplete_game_response')
                    if not result or result.get('status')!='completed' or not result.get('id'):
                        raise ValueError('incomplete_game_response')
                    if result.get('model')!=MODEL or (result.get('reasoning') or {}).get('effort')!='max':
                        raise ValueError('game_model_or_effort_mismatch')
                    update_llm_trace(trace,metadata={'response_id':result['id'],'usage':result.get('usage')})
                    return result
    finally:
        await request.aclose()


async def run_novel_game(fence, *, packet_loader=None, transport=None, stage_store=None,
                         verifier=None, output=None, issue14_admission=None):
    from .issue14_execution_admission import check_issue14_dispatch
    from .lifetime_memory_lane_engine import check_lane_generation
    check_issue14_dispatch(issue14_admission,role='tool_loop')
    check_lane_generation()
    fence = GameFence.model_validate(fence)
    packet = await (packet_loader or load_build_packet)(fence)
    selected = selected_scenes(packet)
    brief = validate_brief(packet['brief'],len(selected['scenes']))
    source = confirmed_source(packet)
    dependency = dependency_snapshot()
    store,verify = stage_store or checkpoint,verifier or browser_verify
    with tempfile.TemporaryDirectory(prefix='memoir-novel-') as temporary:
        workspace = Path(output or temporary)
        workspace.mkdir(parents=True,exist_ok=True)
        assets.write_json(workspace,'source/input.json',dict(input=source))
        assets.write_bytes(workspace,'PRODUCT_BRIEF.md',brief['design_brief'].encode())
        artifacts = {'PRODUCT_BRIEF.md':brief['design_brief']}
        receipts = []
        for stage in STAGES:
            assets.write_json(workspace,'progress.json',dict(status='running',stage=stage,completed_stages=len(receipts)))
            config = runner.STAGES[stage]
            paths = [config['skill']+'/SKILL.md']+[config['skill']+'/references/'+p for p in config['refs']]
            upstream = {p:(runner.SKILL/p).read_text() for p in paths}
            managed = ['adapter','journey',stage]
            if stage in ('whitebox','art','production'): managed.append('assets')
            instructions = '\n\n'.join(load_prompt_artifact(prompt_path('memoir/skills/memoir-story-game/novel-to-game/'+n)) for n in managed)
            instructions += '\n\n'+'\n\n'.join('===== '+p+' =====\n'+v for p,v in upstream.items())
            outputs = config['outputs'] if stage!='art' else ['design/ART_DIRECTION.md','design/SCENE_BINDINGS.json']
            payload = dict(stage=stage,source=source,format_contract=runner.FORMAT,saved_artifacts=artifacts,
                allowed_output_paths=outputs,scene_library=scene_library(),stock_catalog=assets.pack_catalog())
            schema = runner.SCHEMA
            manifest = instruction_manifest(instructions,schema,variant='novel-game-'+stage)
            body = dict(model=MODEL,reasoning={'effort':'max'},instructions=instructions,input=canonical(payload),store=False,
                stream=True,max_output_tokens=config['budget'],metadata={**manifest_metadata(manifest),
                    'generation_name':'memoir-story-game-novel-'+stage,'trace_name':'memoir-story-game-build',
                    'stage':stage,'upstream_revision':dependency['revision'],'synthetic':str(source['fictional']).lower()},
                text={'format':{'type':'json_schema','name':'memoir_novel_stage','strict':True,'schema':schema}})
            signature = fingerprint(body)
            cached = await store(fence,stage,signature)
            if cached:
                value,receipt = cached['value'],cached['receipt']
            else:
                assets.write_json(workspace,'stages/'+stage+'/request.json',body)
                result = await model_stage(body,fence,transport=transport,issue14_admission=issue14_admission,prompt_manifest=manifest)
                assets.write_json(workspace,'stages/'+stage+'/response.json',result)
                text=''.join(p.get('text','') for item in result.get('output',[]) if item.get('type')=='message' for p in item.get('content',[]) if p.get('type')=='output_text')
                value=json.loads(text)
                receipt=dict(status='completed',model=result['model'],requested_model=MODEL,reasoning_effort='max',
                    response_id=result['id'],usage=result.get('usage'),prompt_manifest=manifest,stage=stage,
                    upstream_revision=dependency['revision'],request_sha256=signature)
            files = value['files']
            if len(files)!=len(outputs) or {f['path'] for f in files}!=set(outputs):
                raise ValueError('game_stage_outputs_invalid')
            content={f['path']:f['content'] for f in files}
            if any(not isinstance(v,str) or len(v.encode())>50000 for v in content.values()):
                raise ValueError('game_stage_output_limit')
            if stage=='analyze' and not all(c['chapter_id'] in content[outputs[0]] and e['id'] in content[outputs[0]] for c,e in zip(source['chapters'],source['timeline'])):
                raise ValueError('game_analysis_coverage_required')
            if stage=='design': journey.bind_journey(json.loads(content['design/JOURNEY_PLAN.json']),source)
            for path,text in content.items():
                if path.endswith('.css'): validate_style(text)
                assets.write_bytes(workspace,path,text.encode())
            if stage=='art':
                bindings=json.loads(content['design/SCENE_BINDINGS.json'])
                needed={s['scene'] for s in json.loads(artifacts['design/JOURNEY_PLAN.json'])['segments']}
                if not isinstance(bindings,dict) or set(bindings)!=needed or any(cell not in scene_library()['cells'] for cell in bindings.values()):
                    raise ValueError('game_scene_bindings_invalid')
                catalog=assets.pack_catalog()
                for item in catalog['files']: assets.write_bytes(workspace,'build/app/'+item['url'],assets.stock_source(item).read_bytes())
                library=scene_library()
                assets.write_bytes(workspace,'build/app/assets/scenes/places.png',(journey.PACKAGE/'assets/illustrated-places-v1/places.png').read_bytes())
                art=dict(url='assets/scenes/places.png',status='ready',width=library['width'],height=library['height'],
                    columns=library['columns'],rows=library['rows'],scenes=list(bindings),cells={k:library['cells'].index(v) for k,v in bindings.items()})
                assets.write_json(workspace,'build/asset-catalog.json',dict(stock=catalog,scenes=[art]))
            artifacts.update(content)
            if stage in ('design','whitebox','art','production'):
                journey.materialise(workspace,source,runner.public_source(source),require_art=stage=='production')
                artifacts['build/template.html']=(workspace/'build/template.html').read_text()
                artifacts['build/app/journey-runtime.css']=(workspace/'build/app/journey-runtime.css').read_text()
            if not cached: await store(fence,stage,signature,dict(value=value,receipt=receipt))
            receipts.append(receipt)
            assets.write_json(workspace,'stages/'+stage+'/checkpoint.json',dict(value=value,receipt=receipt))
            if stage=='whitebox':
                feedback=await verify(workspace,'whitebox')
                artifacts['whitebox-feedback.json']=canonical(feedback)
                assets.write_json(workspace,'whitebox-feedback.json',feedback)
        assets.write_json(workspace,'progress.json',dict(status='running',stage='browser-qa',completed_stages=len(receipts)))
        qa = dict(desktop=await verify(workspace,'production'),touch=await verify(workspace,'production',phone=True),
            journey=await verify(workspace,'journey'))
        plan=journey.bind_journey(json.loads(artifacts['design/JOURNEY_PLAN.json']),source)
        bundle=validate_bundle(dict(version=1,source=runner.public_source(source),plan=plan,
            css=artifacts['build/app/game.css'],scene_bindings=json.loads(artifacts['design/SCENE_BINDINGS.json'])),selected['scenes'])
        receipt=dict(status='completed',skill='novel-to-game',model=MODEL,requested_model=MODEL,reasoning_effort='max',
            response_id=receipts[-1]['response_id'],response_ids=[r['response_id'] for r in receipts],stages=receipts,
            upstream_revision=dependency['revision'],skill_sha256=fingerprint(dependency),artifact_sha256=fingerprint(bundle),
            runtime_sha256=journey.runtime_hashes(),qa=qa,selection_digest=packet['selection_digest'])
        assets.write_json(workspace,'run-receipt.json',receipt)
        assets.write_json(workspace,'progress.json',dict(status='completed',stage='verified',completed_stages=len(receipts)))
        return dict(webpage=dict(novel_game=bundle),receipt=receipt)
