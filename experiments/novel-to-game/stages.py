"""Branch-only, checkpointed Sol-max RPG/scroller experiment; dry-run by default."""
import argparse
import base64
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import httpx
from dotenv import dotenv_values

PACKAGE = Path(__file__).resolve().parent
sys.path.insert(0, str(PACKAGE))
from game_assets import prepare as prepare_assets, validate_plan, write_bytes
from journey import materialise as materialise_journey, runtime_hashes, validate_journey

ROOT = PACKAGE.parents[1]
HERE = ROOT/'var/novel-to-game-rpg-scroller'
SNAPSHOT = PACKAGE/'examples/age-eight-patch'
SKILL = ROOT/'deps/novel-to-game/skills'
MODEL = 'gpt-6.1-sol'
KEY = ''
BASE = 'http://127.0.0.1:4000/v1'
SOURCE = None
BRIEF = None
FORMAT = dict(format='rpg-side-scroller', controlled_character='memoir_author',
    navigation='bidirectional_continuous_scrolling', route='single_chronological_stream',
    transitions='illustrated_overlap_and_pan', runtime='memoir-linear-v2',
    inputs=['keyboard', 'touch'], interaction='proximity_memories_with_revisits', historical_outcomes='fixed')
SCHEMA = {'type':'object','additionalProperties':False,'required':['files','notes'],'properties':{
    'files':{'type':'array','items':{'type':'object','additionalProperties':False,'required':['path','content'],
        'properties':{'path':{'type':'string'},'content':{'type':'string'}}}},'notes':{'type':'string'}}}
STAGES = {
 'analyze':dict(skill='novel-game-analyze', refs=['gameability-protocol.md'], inputs=['PRODUCT_BRIEF.md'],
    outputs=['analysis/SOURCE_BIBLE.md'], budget=6500,
    task='Analyze all supplied approved chapters and linked timeline events for the locked author-controlled chronological RPG walk. Return SOURCE_BIBLE.md, at most 650 words, with one coverage row per chapter/event pair citing its exact chapter_id and event id. Preserve facts, ages, uncertain dates, relationships, quotations, unknown outcomes and every source unit. Identify supported spaces, visual anchors, constraints and open design space; use immutable/adaptable/open/conflicted boundary labels. Keep invented testimony and implementation out of this factual handoff. No QA claims.'),
 'concept':dict(skill='game-concept', refs=['concept-method.md'], inputs=['PRODUCT_BRIEF.md','analysis/SOURCE_BIBLE.md'],
    outputs=['concepts/CONCEPT.md'], budget=6500,
    task='The format is fixed: one continuous path arranged along the supplied timeline, with forward/backward walking and unlimited nearby rereading, with illustrated places blending smoothly as the author approaches each memory. Compare pacing and encounter treatments within that single chronological stream. Use known chronology and explicitly preserve uncertain order within a life stage. Revisit a place later only as a later segment along the same chronological path. The host runtime owns movement, reading, progress, scene blending and restart; choose stock life-stage/outfit treatment using approved source metadata. Preserve every supplied passage in the text view. Return CONCEPT.md, at most 650 words. No code or QA claims.'),
 'design':dict(skill='game-world-design',refs=['world-design-method.md','narrative-design-method.md'],
    inputs=['PRODUCT_BRIEF.md','analysis/SOURCE_BIBLE.md','concepts/CONCEPT.md'],
    outputs=['design/GAME_DESIGN.md','design/JOURNEY_PLAN.json'],budget=7500,
    task='Design one continuous chronological RPG side-scroller using the supplied journey policy and host runtime. Return GAME_DESIGN.md (at most 650 words) and JOURNEY_PLAN.json. Place each public source chapter C1..Cn exactly once in the supplied timeline order, in contiguous source-supported scenery segments with increasing world positions. Use existing scene IDs for repeated places; a later visit remains further right. Keep uncertain ordering explicit. The runtime handles keyboard/touch movement both ways, camera, repeated proximity reading, unique-memory progress, reversible scene blending, ending and restart. Read again stays available after visiting a memory and after completion. Segment boundaries must also respect life-stage or approved profession changes; the host selects avatars from source metadata. Do not design hubs, travel menus, portals, coordinate resets or new runtime controls. Reading order is free; chronology fixes the layout, not the player direction.'),
 'whitebox':dict(skill='game-build',refs=['build-brief-contract.md'],
    inputs=['PRODUCT_BRIEF.md','analysis/SOURCE_BIBLE.md','concepts/CONCEPT.md','design/GAME_DESIGN.md','design/JOURNEY_PLAN.json','build/template.html','build/app/journey-runtime.css'],
    outputs=['build/BUILD_BRIEF.md','build/app/game.css'],budget=5000,
    task='Prepare whitebox styling for the host-owned continuous walk. Return a short game.css extending the supplied runtime CSS and BUILD_BRIEF below 250 words. The validated journey, HTML, JavaScript, bidirectional movement, camera, repeatable memories, reading dialogs, progress, ending and replay are supplied by the host. Keep the illustrated-panel and avatar hooks, touch controls, dialogue, source view, focus, bounds and reduced-motion support intact. Concentrate on the riskiest spatial/readability question; use simple placeholder scenery until art. Return only allowed files and mark actual QA NOT_RUN.'),
 'art':dict(skill='game-art-direction',refs=['art-direction-method.md'],
    inputs=['PRODUCT_BRIEF.md','concepts/CONCEPT.md','design/GAME_DESIGN.md','design/JOURNEY_PLAN.json','whitebox-feedback.json'],
    outputs=['design/ART_DIRECTION.md','design/SCENE_ART_PLAN.json'],budget=6000,
    task='Read the continuous-walk whitebox observations, validated journey and stock catalog. Return ART_DIRECTION.md (at most 600 words) and SCENE_ART_PLAN.json. Illustrate every journey scene ID using the minimum distinct background images, reusing a location on later visits. Group compatible places into an atlas. Match perspective, ground height, scale and light so the runtime can pan within a place and blend adjacent illustrations smoothly. Reuse stock life-stage/outfit avatars, CSS markers and opt-in music byte-for-byte; only source-supported scene backgrounds are new artwork. Include call count and untested visual limits. Preserve the single path, walking in both directions, rereading and readability. The host generates or restores missing scene assets before production.'),
 'production_style':dict(skill='game-build',refs=['build-brief-contract.md'],
    inputs=['design/ART_DIRECTION.md','design/JOURNEY_PLAN.json','build/template.html','build/app/journey-runtime.css','build/app/game.css','whitebox-feedback.json'],
    outputs=['build/app/game.css'],budget=5500,
    task='Complete one small CSS-only RPG/scroller styling pass after stock art and scene assets have already been integrated into the markup and runtime. HTML, JavaScript, copy, rules and replay stay frozen. Return game.css below 8,000 characters, applying ART_DIRECTION using the exact local asset catalog paths. Preserve the shared sprite animation stylesheet, scenery readability while moving, large touch targets, readable text, visible focus and reduced motion. Preserve every hidden state and tested behaviour. Return only the stylesheet, with no new assets, systems or QA claims.'),
 'production':dict(skill='game-build',refs=['build-brief-contract.md'],
    inputs=['PRODUCT_BRIEF.md','concepts/CONCEPT.md','design/GAME_DESIGN.md','design/JOURNEY_PLAN.json','design/ART_DIRECTION.md','build/BUILD_BRIEF.md','build/template.html','build/app/journey-runtime.css','build/app/game.css','build/playthrough.json','whitebox-feedback.json'],
    outputs=['build/BUILD_BRIEF.md','build/app/game.css'],budget=6500,
    task='Polish the approved continuous illustrated walk within the host-owned runtime. Return game.css and a concise BUILD_BRIEF. The host integrates ready scene illustrations, stock age/outfit avatars and opt-in audio using the validated journey; it owns the HTML, JavaScript and replay. Style the supplied hooks while preserving smooth illustrated overlap/panning, a stable ground baseline, continuous bidirectional travel, repeatable proximity reading with unique progress, unchanged source passages, readable controls/dialogues, visible focus, reduced motion, ending and restart. Use only catalog assets. Keep every hidden/disabled state and tested rule. Do not replace the runtime or return HTML, JavaScript, binary assets or base64. Actual browser QA remains NOT_RUN until executed.')
}


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def dependency_revision():
    if not (SKILL/'novel-to-game/SKILL.md').is_file():
        raise RuntimeError('NovelToGame dependency missing; run make deps-install')
    dependency = SKILL.parent
    if subprocess.check_output(['git', '-C', str(dependency), 'status', '--porcelain'], text=True).strip():
        raise RuntimeError('NovelToGame dependency has local changes; keep Memoir changes in the adapter')
    return subprocess.check_output(['git', '-C', str(dependency), 'rev-parse', 'HEAD'], text=True).strip()


def save(path, value):
    path.parent.mkdir(parents=True,exist_ok=True)
    text=json.dumps(value,ensure_ascii=False,indent=2)+'\n'
    assert not KEY or KEY not in text
    pending=path.with_suffix(path.suffix+'.next')
    pending.write_text(text)
    pending.replace(path)


def initialise(*, fresh_analysis=False):
    HERE.mkdir(parents=True,exist_ok=True)
    profile=HERE/'format-profile.json'
    if profile.exists():
        assert json.loads(profile.read_text())==FORMAT,'Workspace uses a different game format'
    else:
        assert not any(HERE.iterdir()),'Use a fresh output directory for the RPG/scroller stages'
        save(profile,FORMAT)
    saved_source=HERE/'source/input.json'
    source_path=SOURCE or (saved_source if saved_source.exists() else ROOT/'skills/memoir-story-game/tests/fixtures/age-eight.json')
    fixture=json.loads(source_path.read_text())
    packet=fixture['input']
    assert len(packet['chapters'])==len(packet['timeline']) and packet['chapters'], 'Supply linked composer chapters and timeline entries'
    assert 'fictional' not in packet or type(packet['fictional']) is bool, 'Source fictional flag must be a boolean'
    if SOURCE and saved_source.exists():
        assert json.loads(saved_source.read_text())['input']==packet, 'Source changed; use a fresh output directory'
    origin=HERE/'source-origin.json'
    custom=SOURCE is not None or (origin.exists() and json.loads(origin.read_text())['custom'])
    if custom and not BRIEF and not (HERE/'PRODUCT_BRIEF.md').exists():
        raise ValueError('Custom memoir input requires an approved --brief; the age-eight brief is not reused')
    if BRIEF and (HERE/'PRODUCT_BRIEF.md').exists():
        assert (HERE/'PRODUCT_BRIEF.md').read_text()==BRIEF.read_text(), 'Brief changed; update the approved workspace brief explicitly or use a fresh workspace'
    source_hash=digest(json.dumps(packet,sort_keys=True,ensure_ascii=False))
    analysis_checkpoint=HERE/'stages/analyze/checkpoint.json'
    sources=[('PRODUCT_BRIEF.md',BRIEF or PACKAGE/'PRODUCT_BRIEF.md'), ('source/input.json',source_path)]
    if not custom:
        sources.append(('source/memoir.md',SNAPSHOT/'source/memoir.md'))
    if not fresh_analysis and not analysis_checkpoint.is_file() and not custom:
        sources.append(('analysis/SOURCE_BIBLE.md',SNAPSHOT/'analysis/SOURCE_BIBLE.md'))
    for path,source in sources:
        destination=HERE/path
        if not destination.exists():
            destination.parent.mkdir(parents=True,exist_ok=True)
            destination.write_bytes(source.read_bytes())
    save(origin,dict(custom=custom,source_sha256=source_hash))
    if fresh_analysis:
        return packet
    if custom and not analysis_checkpoint.is_file():
        raise ValueError('Run analyze for this memoir before continuing; benchmark analysis cannot be reused')
    bible=(HERE/'analysis/SOURCE_BIBLE.md').read_text()
    assert all(c['chapter_id'] in bible and e['id'] in bible for c,e in zip(packet['chapters'],packet['timeline']))
    if analysis_checkpoint.is_file():
        analysis=json.loads(analysis_checkpoint.read_text())
        assert analysis['source_sha256']==source_hash,'Source analysis does not match the full input'
        assert analysis['outputs']['analysis/SOURCE_BIBLE.md']==digest(bible),'Source analysis changed after generation'
        return packet
    analysis=json.loads((SNAPSHOT/'analysis-reused.json').read_text())
    assert analysis['source_sha256']==source_hash,'Source analysis does not match the full input'
    save(HERE/'analysis-reused.json',dict(status='PASS',origin='examples/age-eight-patch/analysis-reused.json',receipt=analysis['receipt'],
        source_sha256=source_hash))
    return packet


def public_source(packet):
    benchmark=packet==json.loads((ROOT/'skills/memoir-story-game/tests/fixtures/age-eight.json').read_text())['input']
    events={e['formal_chapter_id']:e for e in packet['timeline']}
    return dict(title=packet.get('title','The Blue Gate · Age Eight' if benchmark else 'A life, one journey'),
        fictional=packet.get('fictional',benchmark),chapters=[dict(id='C'+str(i+1),
        title=events[c['chapter_id']]['title'],text='\n\n'.join(b['text'] for b in c['blocks'])) for i,c in enumerate(packet['chapters'])])


def checked_artifact_path(path):
    relative=path.relative_to(HERE)
    if '..' in relative.parts or any((HERE/p).is_symlink() for p in (relative,*relative.parents)):
        raise ValueError('Unsafe checkpoint artifact path: '+relative.as_posix())
    return path


def materialise(packet):
    if (HERE/'design/JOURNEY_PLAN.json').exists():
        materialise_journey(HERE,packet,public_source(packet))
        return
    template=checked_artifact_path(HERE/'build/template.html')
    if not template.is_file():return
    target=checked_artifact_path(HERE/'build/app/index.html')
    text=template.read_text()
    assert text.count('<!-- MEMOIR_SOURCE -->')==1
    data=json.dumps(public_source(packet),ensure_ascii=False).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    write_bytes(HERE,target.relative_to(HERE).as_posix(),text.replace('<!-- MEMOIR_SOURCE -->',
        '<script id="memoir-source" type="application/json">'+data+'</script>').encode())


def reuse_outputs(stage, outputs, allowed):
    # HTML is archived before source insertion, under the same path used at generation.
    allowed={'build/template.html' if p=='build/app/index.html' else p for p in allowed}
    if not outputs or not set(outputs)<=allowed:
        raise ValueError('Checkpoint contains no outputs or disallowed stage output paths')
    if stage.name in ('design','art') and set(outputs)!=allowed:
        raise ValueError('Checkpoint is missing required stage outputs')
    verified={}
    for name,expected in outputs.items():
        archive=checked_artifact_path(stage/'artifacts'/name)
        working=checked_artifact_path(HERE/name)
        if not archive.is_file():
            return False
        content=archive.read_text()
        if digest(content)!=expected:
            return False
        verified[working]=(content,expected)
    # Later build stages share outputs. Preserve their revisions instead of rolling them back.
    # Validate the whole set before restoring any missing handoff.
    missing={}
    for path,(content,expected) in verified.items():
        if path.exists():
            if not path.is_file() or digest(path.read_text())!=expected:
                raise ValueError('Working artifact differs from checkpoint: '+path.relative_to(HERE).as_posix()+
                    '; preserve later-stage edits and reconcile the working file before retrying')
        else:
            missing[path]=content
    for path,content in missing.items():
        path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('x') as target:
            target.write(content)
    return True


def run_stage(name, task_override=None, extra_inputs=None, *, dry_run=False):
    packet=initialise(fresh_analysis=name=='analyze')
    revision=dependency_revision()
    config=STAGES[name]
    paths=[config['skill']+'/SKILL.md']+[config['skill']+'/references/'+p for p in config['refs']]
    upstream={p:(SKILL/p).read_text() for p in paths}
    instructions=(PACKAGE/'adapter.md').read_text()+'\n\n'+'\n\n'.join('===== '+p+' =====\n'+v for p,v in upstream.items())
    if name in ('concept','design','whitebox','art','production','production_style'):
        instructions+='\n\n'+(PACKAGE/'journey-policy.md').read_text()
    if name in ('whitebox','art','production','production_style'):
        if not (HERE/'design/JOURNEY_PLAN.json').is_file():
            raise ValueError('Generate and validate JOURNEY_PLAN.json before building')
        instructions+='\n\n'+(PACKAGE/'asset-policy.md').read_text()
        catalog=prepare_assets(HERE, ROOT/'var/novel-to-game-scene-cache',
            include_scenes=name in ('production','production_style'), require_ready=name in ('production','production_style') and not dry_run)
        materialise_journey(HERE,packet,public_source(packet),require_art=name in ('production','production_style') and not dry_run)
    inputs={p:(HERE/p).read_text() for p in config['inputs']}
    if name in ('whitebox','art','production','production_style'):
        inputs['build/asset-catalog.json']=json.dumps(catalog,ensure_ascii=False,sort_keys=True)
        inputs['build/journey.json']=(HERE/'build/journey.json').read_text()
    if extra_inputs:inputs.update(extra_inputs)
    # Send every source unit, with compact timeline metadata and stable internal citations.
    source=dict(title=public_source(packet)['title'],fictional=public_source(packet)['fictional'],chapters=packet['chapters'],timeline=[{k:v for k,v in e.items() if k!='source_refs'} for e in packet['timeline']],locale=packet['locale'])
    user=dict(stage=name,task=task_override or config['task'],format_contract=FORMAT,source=source,saved_artifacts=inputs,
        allowed_output_paths=config['outputs'],source_data_contract=dict(shape='{title,fictional,chapters:[{id,title,text}]}',
            chapter_ids=['C'+str(i+1) for i in range(len(packet['chapters']))],count=len(packet['chapters'])))
    profile=HERE/'source/character-profile.json'
    if profile.exists():
        user['approved_character_profile']=json.loads(profile.read_text())
    if name in ('whitebox','art','production','production_style'):
        user['host_runtime_sha256']=runtime_hashes()
    body=dict(model=MODEL,reasoning={'effort':'max'},instructions=instructions,input=json.dumps(user,ensure_ascii=False),
        store=False,max_output_tokens=config['budget'],metadata=dict(generation_name='novel-game-'+name,
        trace_name='memoir-novel-game',synthetic=str(public_source(packet)['fictional']).lower(),stage=name,upstream_revision=revision),
        text={'format':{'type':'json_schema','name':'novel_game_stage_files','strict':True,'schema':SCHEMA}})
    if name in ('art','production'):
        frames=[HERE/'qa/whitebox/evidence'/p for p in ('render.png','coreLoop.png')]
        if all(p.is_file() for p in frames):
            body['input']=[{'role':'user','content':[{'type':'input_text','text':body['input']}]+[
                {'type':'input_image','image_url':'data:image/png;base64,'+base64.b64encode(p.read_bytes()).decode(),'detail':'high'}
                for p in frames]}]
    # Planning can also outlast a non-streaming proxy's idle timeout.
    body['stream']=True
    signature=digest(json.dumps(body,sort_keys=True,ensure_ascii=False))
    stage=HERE/'stages'/name
    stage.mkdir(parents=True,exist_ok=True)
    if dry_run:
        save(stage/'preview-request.json',body)
        print(json.dumps(dict(stage=name,status='NOT_RUN',model=MODEL,effort='max',format=FORMAT['format'],calls=0)),flush=True)
        return body
    checkpoint=stage/'checkpoint.json'
    if checkpoint.exists():
        done=json.loads(checkpoint.read_text())
        if done['request_sha256']==signature and reuse_outputs(stage,done['outputs'],config['outputs']):
            materialise(packet)
            print(json.dumps(dict(stage=name,status='reused',response_id=done['response_id'])),flush=True)
            return done
    attempts=list(stage.glob('attempt-*-request.json'))
    ordinal=len(attempts)+1
    prefix=stage/('attempt-'+str(ordinal))
    save(Path(str(prefix)+'-request.json'),body)
    (stage/'instructions.txt').write_text(instructions)
    started=time.monotonic()
    print(json.dumps(dict(stage=name,status='running',model=MODEL,effort='max',attempt=ordinal)),flush=True)
    response=None
    try:
        with httpx.Client(trust_env=False,timeout=590) as client:
            if body.get('stream'):
                data=[];result=None;events={};last_log=0;characters=0
                with client.stream('POST',BASE+'/responses',headers={'Authorization':'Bearer '+KEY},json=body) as response:
                    response.raise_for_status()
                    for line in response.iter_lines():
                        assert KEY not in line
                        if line.startswith('data:'):
                            data.append(line[5:].lstrip())
                        elif not line and data:
                            raw='\n'.join(data);data.clear()
                            if raw=='[DONE]':continue
                            event=json.loads(raw);kind=event.get('type','untyped')
                            events[kind]=events.get(kind,0)+1
                            if isinstance(event.get('delta'),str):characters+=len(event['delta'])
                            if time.monotonic()-last_log>45:
                                progress=dict(stage=name,status='streaming',seconds=round(time.monotonic()-started,1),event=kind,output_characters=characters)
                                print(json.dumps(progress),flush=True);save(stage/'progress.json',progress)
                                last_log=time.monotonic()
                            if kind in ('response.completed','response.incomplete','response.failed'):
                                result=event['response'];break
                            if kind=='error' or 'error' in event:
                                save(Path(str(prefix)+'-stream-error.json'),event)
                                raise RuntimeError('Gateway stream returned an error')
                save(Path(str(prefix)+'-events.json'),events)
                assert result is not None,'Stream ended without a terminal response'
            else:
                response=client.post(BASE+'/responses',headers={'Authorization':'Bearer '+KEY},json=body)
                assert KEY.encode() not in response.content
                result=response.json()
            save(Path(str(prefix)+'-response.json'),result)
            response.raise_for_status()
        assert result.get('status')=='completed' and result.get('model')==MODEL and result.get('id'), 'Incomplete model response'
        assert result.get('reasoning',{}).get('effort')=='max', 'Effective max effort not reported'
        output=''.join(p.get('text','') for i in result.get('output',[]) if i.get('type')=='message' for p in i.get('content',[]) if p.get('type')=='output_text')
        value=json.loads(output)
        files=value['files']
        names=[f['path'] for f in files]
        assert files and len(names)==len(set(names)) and set(names)<=set(config['outputs'])
        if name=='art':
            assert set(names)==set(config['outputs']), 'Art requires direction and the scene-only plan'
            art_plan=validate_plan(json.loads(next(f['content'] for f in files if f['path']=='design/SCENE_ART_PLAN.json')))
            needed={s['scene'] for s in json.loads((HERE/'design/JOURNEY_PLAN.json').read_text())['segments']}
            assert {s for a in art_plan['illustrations'] for s in a['scenes']}==needed, 'Illustrate exactly the journey locations before generating images'
        if name=='design':
            assert set(names)==set(config['outputs']), 'Design requires the continuous journey plan'
            validate_journey(json.loads(next(f['content'] for f in files if f['path']=='design/JOURNEY_PLAN.json')),packet['chapters'],packet['timeline'])
        hashes={}
        for file in files:
            path=HERE/file['path']
            assert path.resolve().is_relative_to(HERE) and not path.is_symlink()
            assert isinstance(file['content'],str) and len(file['content'].encode())<100000 and KEY not in file['content']
            if file['path']=='build/app/index.html':
                assert file['content'].count('<!-- MEMOIR_SOURCE -->')==1
                path=HERE/'build/template.html'
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text(file['content'])
            hashes[path.relative_to(HERE).as_posix()]=digest(file['content'])
            snapshot=stage/'artifacts'/path.relative_to(HERE)
            snapshot.parent.mkdir(parents=True,exist_ok=True)
            snapshot.write_text(file['content'])
        materialise(packet)
        receipt=dict(stage=name,status='PASS',model=result['model'],reasoning=result.get('reasoning'),response_id=result['id'],
            duration_seconds=round(time.monotonic()-started,3),usage=result.get('usage'),request_sha256=signature,
            source_sha256=digest(json.dumps(packet,sort_keys=True,ensure_ascii=False)),
            upstream_revision=revision,upstream_sha256=digest(json.dumps(upstream,sort_keys=True,ensure_ascii=False)),
            outputs=hashes,notes=value['notes'])
        save(checkpoint,receipt)
        if name=='analyze':
            (HERE/'analysis-reused.json').unlink(missing_ok=True)
        print(json.dumps({k:receipt[k] for k in ('stage','status','duration_seconds','outputs')}),flush=True)
        return receipt
    except Exception as error:
        save(Path(str(prefix)+'-failure.json'),dict(stage=name,status='FAIL',error_type=type(error).__name__,
            http_status=response.status_code if response is not None else None,duration_seconds=round(time.monotonic()-started,3)))
        raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage',choices=list(STAGES))
    parser.add_argument('--output',type=Path,default=HERE,help='Fresh isolated workspace, then reuse it to resume')
    parser.add_argument('--source',type=Path,help='Approved JSON with input.chapters and input.timeline; saved for resume')
    parser.add_argument('--brief',type=Path,help='Approved product brief, required for a new custom source')
    parser.add_argument('--execute',action='store_true',help='Make one live Sol max stage call; otherwise prepare only')
    parser.add_argument('--env-file',type=Path,default=ROOT/'.env',help='Owner-scoped local gateway credentials')
    args=parser.parse_args()
    HERE=args.output.resolve()
    SOURCE=args.source.resolve() if args.source else None
    BRIEF=args.brief.resolve() if args.brief else None
    if not args.execute:
        run_stage(args.stage,dry_run=True)
        sys.exit(0)
    settings=dotenv_values(args.env_file,interpolate=False)
    KEY=settings['MEMORY_SPARK_LLM_API_KEY']
    initialise(fresh_analysis=args.stage=='analyze')
    stage=HERE/'stages'/args.stage
    stage.mkdir(parents=True,exist_ok=True)
    with (stage/'worker.lock').open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX | fcntl.LOCK_NB)
        save(stage/'worker.json',dict(pid=os.getpid(),stage=args.stage,status='running'))
        try:
            result=run_stage(args.stage)
            save(stage/'worker.json',dict(pid=os.getpid(),stage=args.stage,status='completed',response_id=result['response_id']))
        except BaseException as error:
            save(stage/'worker.json',dict(pid=os.getpid(),stage=args.stage,status='failed',error_type=type(error).__name__))
            raise
