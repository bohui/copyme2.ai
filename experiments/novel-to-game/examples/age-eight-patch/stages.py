"""Checkpointed live Sol-max stages for the complete fictional age-eight example."""
import argparse
import base64
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sys
import time

import httpx
from dotenv import dotenv_values

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OLD = ROOT/'var/novel-to-game-evaluation-20261025'
SKILL = ROOT/'var/external-skills/novel-to-game-c3075f35cc14'
MODEL = 'gpt-6.1-sol'
REVISION = 'c3075f35cc14d4bc94e2829df2bfcc0d9971229e'
SCHEMA = {'type':'object','additionalProperties':False,'required':['files','notes'],'properties':{
    'files':{'type':'array','items':{'type':'object','additionalProperties':False,'required':['path','content'],
        'properties':{'path':{'type':'string'},'content':{'type':'string'}}}},'notes':{'type':'string'}}}
STAGES = {
 'concept':dict(skill='game-concept', refs=['concept-method.md'], inputs=['PRODUCT_BRIEF.md','analysis/SOURCE_BIBLE.md'],
    outputs=['concepts/CONCEPT.md'], budget=6500,
    task='Choose the game direction from the complete age-eight source. Compare meaningful alternatives briefly, select the strongest coherent game, and establish its real player actions and observable consequences. Return only CONCEPT.md, at most 650 words. No code or QA claims.'),
 'design':dict(skill='game-world-design',refs=['world-design-method.md','narrative-design-method.md'],
    inputs=['PRODUCT_BRIEF.md','analysis/SOURCE_BIBLE.md','concepts/CONCEPT.md'],
    outputs=['design/GAME_DESIGN.md'],budget=7500,
    task='Design the selected complete game and its riskiest executable whitebox. Keep causal rules, prerequisites, feedback, ending and reset precise. Map all ten source units to gameplay, context or intentional omission without forcing ten scenes. Define stable UI ids/data attributes so production styling can preserve the runtime. Return GAME_DESIGN.md, at most 650 words. No implementation or art direction yet.'),
 'whitebox':dict(skill='game-build',refs=['build-brief-contract.md'],
    inputs=['PRODUCT_BRIEF.md','analysis/SOURCE_BIBLE.md','concepts/CONCEPT.md','design/GAME_DESIGN.md'],
    outputs=['build/BUILD_BRIEF.md','build/app/index.html','build/app/game.css','build/app/game.js','build/playthrough.json'],budget=12000,
    task='Implement the smallest complete whitebox of the approved game, with real playable actions, consequences, ending and restart. Return separate concise index.html, game.css, game.js; do not repeat source passages because the host inserts them. Include the ordinary-input playthrough plan and a BUILD_BRIEF below 300 words. Use a semantic DOM and stable ids; source-text view must include all ten injected passages. Keep the complete runtime below 180 JavaScript lines and total app source below 22,000 characters. Return the requested files only; the host performs the whitebox run next.'),
 'art':dict(skill='game-art-direction',refs=['art-direction-method.md'],
    inputs=['PRODUCT_BRIEF.md','concepts/CONCEPT.md','design/GAME_DESIGN.md','whitebox-feedback.json'],
    outputs=['design/ART_DIRECTION.md'],budget=6000,
    task='Read the actual whitebox observations, review remaining scope/budget and define the final game visual direction in at most 600 words. The approved medium is original CSS/inline SVG with system fonts. Choose a distinctive coherent visual identity, readable active game, concrete action/feedback, outcome and phone layout. Preserve the validated rules and DOM contract. Target playable-prototype, with no image-generation or voice service. Return ART_DIRECTION.md only, including the whitebox/scope review and remaining visual limits.'),
 'production_style':dict(skill='game-build',refs=['build-brief-contract.md'],
    inputs=['design/ART_DIRECTION.md','build/template.html','build/app/game.css','whitebox-feedback.json'],
    outputs=['build/app/game.css'],budget=5500,
    task='Production repair after the combined visual build returned an upstream stream error at 902 seconds. Complete ONE small CSS-only stage now. The supplied HTML, game JavaScript, copy, rules and replay are frozen and already tested. Write only game.css, below 8,000 characters. Apply the approved Enamel & Chalk direction to the EXISTING selectors: a warm workbench, enamel basin, charcoal tube, blue biscuit tin, chalk/patch states, compact desktop tools beside basin, single-column phone, legible 16px text, large controls, visible focus and reduced motion. Use ordinary CSS shapes, gradients and pseudo-elements; no SVG encoding, external assets, elaborate animations, layout redesign or new features. Keep all essential text accessible and every [hidden] element hidden. Do not change the game. Return the finished stylesheet directly; no planning document or QA claims.'),
 'production':dict(skill='game-build',refs=['build-brief-contract.md'],
    inputs=['PRODUCT_BRIEF.md','concepts/CONCEPT.md','design/GAME_DESIGN.md','design/ART_DIRECTION.md','build/BUILD_BRIEF.md','build/template.html','build/app/game.css','build/app/game.js','build/playthrough.json','whitebox-feedback.json'],
    outputs=['build/BUILD_BRIEF.md','build/app/index.html','build/app/game.css','build/app/game.js','build/playthrough.json'],budget=12000,
    task='Finish the approved playable prototype using the tested whitebox runtime. Apply ART_DIRECTION with a polished, responsive game interface, clear original CSS/SVG focal art and readable actions/feedback. Preserve stable selectors and tested behaviour. Return changed app files only, plus an updated concise BUILD_BRIEF and playthrough plan if affected. Keep the source marker in index.html. Keep total app source below 25,000 characters; game.js should stay below 180 lines. Do not spend output repeating unchanged game.js. The host will run final QA; leave unobserved results NOT_RUN.')
}


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True,exist_ok=True)
    text=json.dumps(value,ensure_ascii=False,indent=2)+'\n'
    assert not KEY or KEY not in text
    pending=path.with_suffix(path.suffix+'.next')
    pending.write_text(text)
    pending.replace(path)


def initialise():
    HERE.mkdir(exist_ok=True)
    fixture=json.loads((OLD/'source/input.json').read_text())
    packet=fixture['input']
    assert len(packet['chapters'])==len(packet['timeline'])==10
    for path in ['PRODUCT_BRIEF.md','analysis/SOURCE_BIBLE.md','source/input.json']:
        destination=HERE/path
        if not destination.exists():
            destination.parent.mkdir(parents=True,exist_ok=True)
            destination.write_bytes((OLD/path).read_bytes())
    bible=(HERE/'analysis/SOURCE_BIBLE.md').read_text()
    assert all(c['chapter_id'] in bible and e['id'] in bible for c,e in zip(packet['chapters'],packet['timeline']))
    receipt=json.loads((OLD/'receipts-attempt-1.json').read_text())[0]
    save(HERE/'analysis-reused.json',dict(status='PASS',origin=str(OLD/'analysis-response.json'),receipt=receipt,
        source_sha256=digest(json.dumps(packet,sort_keys=True,ensure_ascii=False))))
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


def run_stage(name, task_override=None, extra_inputs=None):
    packet=initialise()
    config=STAGES[name]
    paths=[config['skill']+'/SKILL.md']+[config['skill']+'/references/'+p for p in config['refs']]
    upstream={p:(SKILL/p).read_text() for p in paths}
    instructions=(HERE/'adapter.md').read_text()+'\n\n'+'\n\n'.join('===== '+p+' =====\n'+v for p,v in upstream.items())
    inputs={p:(HERE/p).read_text() for p in config['inputs']}
    if extra_inputs:inputs.update(extra_inputs)
    # Send every source unit, with compact timeline metadata and stable internal citations.
    source=dict(chapters=packet['chapters'],timeline=[{k:v for k,v in e.items() if k!='source_refs'} for e in packet['timeline']],locale=packet['locale'])
    user=dict(stage=name,task=task_override or config['task'],source=source,saved_artifacts=inputs,
        allowed_output_paths=config['outputs'],source_data_contract=dict(shape='{title,fictional,chapters:[{id,title,text}]}',
            chapter_ids=['C'+str(i+1) for i in range(10)],count=10))
    body=dict(model=MODEL,reasoning={'effort':'max'},instructions=instructions,input=json.dumps(user,ensure_ascii=False),
        store=False,max_output_tokens=config['budget'],metadata=dict(generation_name='novel-game-'+name,
        trace_name='memoir-novel-game-age-eight',synthetic='true',stage=name,upstream_revision=REVISION),
        text={'format':{'type':'json_schema','name':'novel_game_stage_files','strict':True,'schema':SCHEMA}})
    if name in ('art','production'):
        frames=[HERE/'qa/whitebox/evidence'/p for p in ('render.png','coreLoop.png')]
        if all(p.is_file() for p in frames):
            body['input']=[{'role':'user','content':[{'type':'input_text','text':body['input']}]+[
                {'type':'input_image','image_url':'data:image/png;base64,'+base64.b64encode(p.read_bytes()).decode(),'detail':'high'}
                for p in frames]}]
    if name in ('whitebox','production','production_style'):
        body['stream']=True
    signature=digest(json.dumps(body,sort_keys=True,ensure_ascii=False))
    stage=HERE/'stages'/name
    stage.mkdir(parents=True,exist_ok=True)
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
            upstream_revision=REVISION,upstream_sha256=digest(json.dumps(upstream,sort_keys=True,ensure_ascii=False)),
            outputs=hashes,notes=value['notes'])
        save(checkpoint,receipt)
        print(json.dumps({k:receipt[k] for k in ('stage','status','duration_seconds','outputs')}),flush=True)
        return receipt
    except Exception as error:
        save(Path(str(prefix)+'-failure.json'),dict(stage=name,status='FAIL',error_type=type(error).__name__,
            http_status=response.status_code if response is not None else None,duration_seconds=round(time.monotonic()-started,3)))
        raise


settings=dotenv_values(ROOT/'.env',interpolate=False)
KEY=settings['MEMORY_SPARK_LLM_API_KEY']
# This runner executes on the host, not on the container bridge configured for Memoir.
BASE='http://127.0.0.1:4000/v1'
if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage',choices=list(STAGES))
    args=parser.parse_args()
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
