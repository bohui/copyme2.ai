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
ROOT = PACKAGE.parents[1]
HERE = ROOT/'var/novel-to-game-rpg-scroller'
SNAPSHOT = PACKAGE/'examples/age-eight-patch'
SKILL = ROOT/'deps/novel-to-game/skills'
MODEL = 'gpt-6.1-sol'
KEY = ''
BASE = 'http://127.0.0.1:4000/v1'
FORMAT = dict(format='rpg-side-scroller', controlled_character='memoir_author',
    navigation='horizontal_with_scrolling_camera', inputs=['keyboard', 'touch'],
    interaction='proximity_characters_and_memory_markers', historical_outcomes='fixed')
SCHEMA = {'type':'object','additionalProperties':False,'required':['files','notes'],'properties':{
    'files':{'type':'array','items':{'type':'object','additionalProperties':False,'required':['path','content'],
        'properties':{'path':{'type':'string'},'content':{'type':'string'}}}},'notes':{'type':'string'}}}
STAGES = {
 'analyze':dict(skill='novel-game-analyze', refs=['gameability-protocol.md'], inputs=['PRODUCT_BRIEF.md'],
    outputs=['analysis/SOURCE_BIBLE.md'], budget=6500,
    task='Analyze the complete ten-chapter fictional age-eight source and its ten linked timeline events for the locked author-controlled RPG side-scroller. Return SOURCE_BIBLE.md, at most 650 words, with one coverage row per chapter/event pair citing its exact chapter_id and event id. Preserve facts, uncertain dates, relationships, quotations, unknown outcomes and all ten source units. Identify supported actions, spaces, visual anchors, constraints and open design space; use immutable/adaptable/open/conflicted boundary labels. Keep gameplay state, scene structure and invented testimony out of this factual handoff. No game implementation or QA claims.'),
 'concept':dict(skill='game-concept', refs=['concept-method.md'], inputs=['PRODUCT_BRIEF.md','analysis/SOURCE_BIBLE.md'],
    outputs=['concepts/CONCEPT.md'], budget=6500,
    task='The format is fixed: a side-scrolling RPG journey where the player moves the author through connected settings and approaches characters or memory markers. Compare quest, route and encounter structures within that format using the complete source; choose one and describe movement, interaction and observable progress. Preserve all ten passages in the text view. Return CONCEPT.md, at most 650 words. No code or QA claims.'),
 'design':dict(skill='game-world-design',refs=['world-design-method.md','narrative-design-method.md'],
    inputs=['PRODUCT_BRIEF.md','analysis/SOURCE_BIBLE.md','concepts/CONCEPT.md'],
    outputs=['design/GAME_DESIGN.md'],budget=7500,
    task='Design the selected side-scrolling RPG and its riskiest whitebox: controllable author, horizontal movement and camera, connected distinct settings, nearby character/memory interactions, exploration progress, ending and restart. Specify keyboard and touch controls, movement bounds, interaction distance and scene transitions. Map all ten source units to playable or contextual treatment; retain all original text. Define stable UI ids and observable movement, camera, scene and progress attributes for real browser verification. The host supports held keyboard or touch movement with action hold, selector, value and duration_ms (50 to 5000), plus clicks, presses and assertions. Keep traversal and interaction concise enough for a replay under 100 steps. Return GAME_DESIGN.md, at most 650 words.'),
 'whitebox':dict(skill='game-build',refs=['build-brief-contract.md'],
    inputs=['PRODUCT_BRIEF.md','analysis/SOURCE_BIBLE.md','concepts/CONCEPT.md','design/GAME_DESIGN.md'],
    outputs=['build/BUILD_BRIEF.md','build/app/index.html','build/app/game.css'],budget=6500,
    task='Implement only the RPG/scroller whitebox layout: index.html, game.css and BUILD_BRIEF below 250 words. Use GAME_DESIGN stable selectors, source marker, a visible player and scenery, distinct scene states, nearby character/memory targets, progress, readable dialogue, full-source dialog, ending and restart. Include keyboard/touch movement and interaction controls with clear data hooks. Load local game.js with defer but do not implement JavaScript or a replay yet; those are separate resumable stages. The host inserts all ten source passages. Keep HTML and CSS together below 12,000 characters. Mark playable QA NOT_RUN.'),
 'whitebox_logic':dict(skill='game-build',refs=['build-brief-contract.md'],
    inputs=['PRODUCT_BRIEF.md','concepts/CONCEPT.md','design/GAME_DESIGN.md','build/BUILD_BRIEF.md','build/template.html','build/app/game.css'],
    outputs=['build/app/game.js'],budget=7000,
    task='Implement only game.js for the existing RPG/scroller markup and approved design. Preserve every DOM hook. Implement a controllable author, held keyboard and touch-button horizontal movement, visible scrolling camera, connected scenes, distance-gated character/memory interactions, meaningful exploration progress, ending and full reset. Read the host-inserted memoir-source JSON and render all original passages with textContent. Expose the design movement, camera, scene and progress state through DOM attributes for host QA. Stop held movement on release, cancel and blur. Keep game rules deterministic and prevent repeated completion credit. Keep JavaScript below 14,000 characters. Return only game.js; no markup, stylesheet, replay or QA claims.'),
 'whitebox_replay':dict(skill='game-build',refs=['build-brief-contract.md'],
    inputs=['design/GAME_DESIGN.md','build/BUILD_BRIEF.md','build/template.html','build/app/game.css','build/app/game.js'],
    outputs=['build/BUILD_BRIEF.md','build/playthrough.json'],budget=4500,
    task='Prepare the ordinary-input browser replay for the actual RPG/scroller implementation. Return build/playthrough.json and BUILD_BRIEF below 250 words. The host executes click, press, hold, assert_text and assert_attr. A hold step has selector, value (keyboard key), duration_ms from 50 to 5000. On phone the same selector receives held touch, so hold a visible movement button; make its keyboard value Enter or Space. Cover real horizontal player and camera movement, a distance-gated interaction, travel between distinct scenes, meaningful progress, the designed ending and restart. Include initial and terminal text, and one assertion checkpoint each in order input, coreLoop, outcome, restart. Use at most 100 steps and modest margins in holds. Assert observed counters/scene data, not hidden JS functions. Leave actual QA NOT_RUN.'),
 'art':dict(skill='game-art-direction',refs=['art-direction-method.md'],
    inputs=['PRODUCT_BRIEF.md','concepts/CONCEPT.md','design/GAME_DESIGN.md','whitebox-feedback.json'],
    outputs=['design/ART_DIRECTION.md'],budget=6000,
    task='Read the RPG/scroller whitebox observations and define its visual direction in at most 600 words. Use original CSS/inline SVG and system fonts: readable player and NPC silhouettes, distinct source-supported scenery, clear interaction cues, progress and phone controls. Preserve horizontal travel, camera, scene transitions and tested rules. Target playable-prototype with no external media services. Include the scope/budget review and untested visual limits. Return ART_DIRECTION.md only.'),
 'production_style':dict(skill='game-build',refs=['build-brief-contract.md'],
    inputs=['design/ART_DIRECTION.md','build/template.html','build/app/game.css','whitebox-feedback.json'],
    outputs=['build/app/game.css'],budget=5500,
    task='Complete one small CSS-only RPG/scroller styling pass. HTML, JavaScript, copy, rules and replay stay frozen. Return game.css below 8,000 characters, applying ART_DIRECTION to the existing player, world, characters, memory markers and controls. Keep the scenery readable while moving, touch targets large, text legible, focus visible and reduced motion supported. Preserve every hidden state and tested behaviour. Use ordinary CSS shapes and gradients, with no external assets or new systems. Return only the stylesheet, with no QA claims.'),
 'production':dict(skill='game-build',refs=['build-brief-contract.md'],
    inputs=['PRODUCT_BRIEF.md','concepts/CONCEPT.md','design/GAME_DESIGN.md','design/ART_DIRECTION.md','build/BUILD_BRIEF.md','build/template.html','build/app/game.css','build/app/game.js','build/playthrough.json','whitebox-feedback.json'],
    outputs=['build/BUILD_BRIEF.md','build/app/index.html','build/app/game.css','build/app/game.js','build/playthrough.json'],budget=12000,
    task='Finish the approved side-scrolling RPG using the tested whitebox runtime and ART_DIRECTION. Preserve the controllable author, horizontal movement/camera, connected scenes, proximity interactions, source-text view, ending and restart. Polish responsive scenery, player/character silhouettes, action cues and keyboard/touch controls. Return changed app files only, plus a concise BUILD_BRIEF and affected playthrough. Keep the source marker in index.html. Prefer one file per repair pass and refer to unchanged files instead of repeating them. The host runs actual QA; leave unobserved results NOT_RUN.')
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
    fixture=json.loads((ROOT/'skills/memoir-story-game/tests/fixtures/age-eight.json').read_text())
    packet=fixture['input']
    assert len(packet['chapters'])==len(packet['timeline'])==10
    source_hash=digest(json.dumps(packet,sort_keys=True,ensure_ascii=False))
    analysis_checkpoint=HERE/'stages/analyze/checkpoint.json'
    sources=[('PRODUCT_BRIEF.md',PACKAGE/'PRODUCT_BRIEF.md'),
                        ('source/memoir.md',SNAPSHOT/'source/memoir.md'),
                        ('source/input.json',ROOT/'skills/memoir-story-game/tests/fixtures/age-eight.json')]
    if not fresh_analysis and not analysis_checkpoint.is_file():
        sources.append(('analysis/SOURCE_BIBLE.md',SNAPSHOT/'analysis/SOURCE_BIBLE.md'))
    for path,source in sources:
        destination=HERE/path
        if not destination.exists():
            destination.parent.mkdir(parents=True,exist_ok=True)
            destination.write_bytes(source.read_bytes())
    if fresh_analysis:
        return packet
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
    return dict(title='The Blue Gate · Age Eight',fictional=True,chapters=[dict(id='C'+str(i+1),
        title=event['title'],text='\n\n'.join(b['text'] for b in chapter['blocks']))
        for i,(chapter,event) in enumerate(zip(packet['chapters'],packet['timeline']))])


def materialise(packet):
    template=HERE/'build/template.html'
    target=HERE/'build/app/index.html'
    if not template.is_file():return
    text=template.read_text()
    assert text.count('<!-- MEMOIR_SOURCE -->')==1
    data=json.dumps(public_source(packet),ensure_ascii=False).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    target.write_text(text.replace('<!-- MEMOIR_SOURCE -->','<script id="memoir-source" type="application/json">'+data+'</script>'))


def run_stage(name, task_override=None, extra_inputs=None, *, dry_run=False):
    packet=initialise(fresh_analysis=name=='analyze')
    revision=dependency_revision()
    config=STAGES[name]
    paths=[config['skill']+'/SKILL.md']+[config['skill']+'/references/'+p for p in config['refs']]
    upstream={p:(SKILL/p).read_text() for p in paths}
    instructions=(PACKAGE/'adapter.md').read_text()+'\n\n'+'\n\n'.join('===== '+p+' =====\n'+v for p,v in upstream.items())
    inputs={p:(HERE/p).read_text() for p in config['inputs']}
    if extra_inputs:inputs.update(extra_inputs)
    # Send every source unit, with compact timeline metadata and stable internal citations.
    source=dict(chapters=packet['chapters'],timeline=[{k:v for k,v in e.items() if k!='source_refs'} for e in packet['timeline']],locale=packet['locale'])
    user=dict(stage=name,task=task_override or config['task'],format_contract=FORMAT,source=source,saved_artifacts=inputs,
        allowed_output_paths=config['outputs'],source_data_contract=dict(shape='{title,fictional,chapters:[{id,title,text}]}',
            chapter_ids=['C'+str(i+1) for i in range(10)],count=10))
    body=dict(model=MODEL,reasoning={'effort':'max'},instructions=instructions,input=json.dumps(user,ensure_ascii=False),
        store=False,max_output_tokens=config['budget'],metadata=dict(generation_name='novel-game-'+name,
        trace_name='memoir-novel-game-age-eight',synthetic='true',stage=name,upstream_revision=revision),
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
        if done['request_sha256']==signature and all((stage/'artifacts'/p).is_file() and digest((stage/'artifacts'/p).read_text())==h for p,h in done['outputs'].items()):
            print(json.dumps(dict(stage=name,status='reused',response_id=done['response_id'])),flush=True)
            materialise(packet)
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
    parser.add_argument('--execute',action='store_true',help='Make one live Sol max stage call; otherwise prepare only')
    parser.add_argument('--env-file',type=Path,default=ROOT/'.env',help='Owner-scoped local gateway credentials')
    args=parser.parse_args()
    HERE=args.output.resolve()
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
