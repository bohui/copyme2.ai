"""Publish/run the shared synthetic judge answer key; default mode makes no calls."""
import argparse
import asyncio
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))

from scripts.memoir_judge_calibration import DATASET, ORIGIN, SOURCE, TARGET, cases, digest, grade, hosted_item, item_id, judges, normalize, request
from scripts.run_memoir_live_skills import save
from scripts.snapshot_prompt_evaluations import pages, cursor_pages
from scripts.langfuse_dataset_names import score_name

PROJECT='cmut9t75w00071z02n8bdv7it'


def publish(client, rows):
    projects=client.api.projects.get().data
    if len(projects)!=1 or projects[0].id!=PROJECT:raise ValueError('Wrong Langfuse project')
    found=[d for d in pages(client.api.datasets.list) if d.name==DATASET]
    content=digest(rows)
    if found and (found[0].metadata or {}).get('content_sha256')!=content:
        raise ValueError('Shared dataset is frozen; use a new suite version for changed answer keys')
    existing={i.id:i for i in pages(client.api.dataset_items.list,dataset_name=DATASET)} if found else {}
    wanted={item_id(case):case for case in rows}
    if set(existing)-set(wanted):raise ValueError('Unexpected shared calibration item')
    for key,current in existing.items():
        if (current.input!=wanted[key]['input'] or current.expected_output!=wanted[key]['expected_output']
                or str(current.status)!='ACTIVE'):
            raise ValueError('Frozen calibration item differs')
    if not found:
        client.api.datasets.create(name=DATASET,
            description='Shared synthetic rubric answer keys; independently human-reviewed labels are still pending.',
            metadata=dict(target=TARGET,synthetic=True,contains_customer_data=False,label_origin=ORIGIN,
                human_reviewed=False,content_sha256=content,item_count=len(rows)),request_options={'max_retries':0})
    for key,case in wanted.items():
        if key not in existing:
            client.api.dataset_items.create(dataset_name=DATASET,**hosted_item(case),
                request_options={'max_retries':0})
    snapshot=datetime.now(timezone.utc)
    dataset=client.get_dataset(DATASET,version=snapshot)
    actual={i.id:i for i in dataset.items}
    if set(actual)!=set(wanted) or any(actual[key].input!=row['input']
            or actual[key].expected_output!=row['expected_output'] for key,row in wanted.items()):
        raise ValueError('Shared dataset write/readback differs')
    return dataset,snapshot


def evaluations(*, input, output, expected_output, **_kwargs):
    from langfuse.experiment import Evaluation
    result=[]
    definitions=judges()
    for name,row in output['judgments'].items():
        target={'trajectory':'memoir/evaluators/shared/trajectory/system',
            'five-case':'memoir/evaluators/workflows/five-case-memoir/trajectory'}.get(name,definitions[name]['prompts'][-1])
        metadata=dict(judge=name,evaluation_target=target,label_origin=ORIGIN,human_reviewed=False,
            prompt_manifest=row['manifest'],response_id=row.get('response_id'))
        result.append(Evaluation(name=score_name(target,'available'),value=int(row['available']),data_type='NUMERIC',metadata=metadata))
        if row['available']:
            compared=grade(row['actual'],expected_output[name])
            result.append(Evaluation(name=score_name(target,'agreement'),value=int(compared['agreement']),data_type='NUMERIC',
                comment=json.dumps(compared['problems']),metadata=metadata))
    return result


class Runner:
    def __init__(self, client, config, directory, receipt, *, concurrency=4, maximum=256, seconds=1800, timeout=180):
        self.client,self.config,self.directory,self.receipt=client,config,directory,receipt
        self.semaphore=asyncio.Semaphore(concurrency);self.maximum=maximum
        self.deadline=time.monotonic()+seconds;self.timeout=timeout

    async def call(self,name,value):
        import httpx
        from apps.api.llm_tracing import gateway_metadata, gateway_trace_headers, trace_llm_call, update_llm_trace
        built=request(name,value)
        record=dict(case_id=value['case_id'],judge=name,manifest=built['manifest'],available=False)
        async with self.semaphore:
            if len(self.receipt['calls'])>=self.maximum or time.monotonic()>=self.deadline:
                return {**record,'error_type':'budget_exhausted'}
            self.receipt['calls'].append(record)
            started=time.monotonic()
            label='evaluation/memoir-judges.calibration.'+name
            metadata={**gateway_metadata(label,trace_name='evaluation/memoir-judges.calibration'),
                'case_id':value['case_id'],'calibration_split':value['split'],'synthetic':'true'}
            model=self.config['MEMORY_SPARK_LLM_MODEL']
            if built['messages'] is not None:
                body=dict(model=model,messages=built['messages'],temperature=0,max_tokens=2500,
                    response_format=dict(type='json_object'),reasoning_effort=self.config['MEMORY_SPARK_LLM_REASONING_EFFORT'],
                    metadata=metadata,store=False)
                endpoint='chat/completions'
            else:
                body=dict(model=model,instructions=built['instructions'],input=json.dumps(built['packet'],ensure_ascii=False),
                    reasoning=dict(effort=self.config['MEMORY_SPARK_LLM_REASONING_EFFORT']),metadata=metadata,store=False,
                    max_output_tokens=2500,text=dict(format=dict(type='json_schema',name='calibration_judgment',strict=True,schema=built['schema'])))
                endpoint='responses'
            record['request_sha256']=digest(body)
            save(self.directory/'receipt.json',self.receipt)
            with trace_llm_call(label,model,trace_name='evaluation/memoir-judges.calibration',client=self.client,
                    gateway=True,input_summary=body,metadata=dict(prompt_manifest=built['manifest'],
                    case_id=value['case_id'],split=value['split'],label_origin=ORIGIN,human_reviewed=False)) as span:
                record.update(trace_id=getattr(span,'trace_id',None),observation_id=getattr(span,'id',None))
                try:
                    remaining=min(self.timeout,self.deadline-time.monotonic())
                    async with asyncio.timeout(remaining):
                        async with httpx.AsyncClient(trust_env=False,follow_redirects=False,
                                transport=httpx.AsyncHTTPTransport(retries=0)) as http:
                            response=await http.post(self.config['MEMORY_SPARK_LLM_BASE_URL'].rstrip('/')+'/'+endpoint,
                                headers={'Authorization':'Bearer '+self.config['MEMORY_SPARK_LLM_API_KEY'],**gateway_trace_headers()},
                                json=body,timeout=remaining)
                            record['http_status']=response.status_code
                            response.raise_for_status()
                            if len(response.content)>2*1024*1024:raise ValueError('Oversized judge response')
                            if self.config['MEMORY_SPARK_LLM_API_KEY'].encode() in response.content:
                                raise ValueError('Unsafe provider response')
                            raw=response.json()
                    if endpoint=='responses':
                        if raw.get('status')!='completed':raise ValueError('Incomplete provider response')
                        text=''.join(c.get('text','') for r in raw.get('output',[]) if r.get('type')=='message'
                            for c in r.get('content',[]) if c.get('type')=='output_text')
                    else:text=raw['choices'][0]['message']['content']
                    record.update(response_id=raw['id'],served_model=raw.get('model'),usage=raw.get('usage'),
                        raw_judgment=json.loads(text))
                    if built['schema']:
                        from jsonschema import validate
                        validate(record['raw_judgment'],built['schema'])
                    record['actual']=normalize(name,record['raw_judgment'],built['packet'])
                    record['available']=True
                    update_llm_trace(span,output=record['raw_judgment'],metadata=dict(response_id=record['response_id']))
                except Exception as error:
                    record['error_type']=type(error).__name__
                    update_llm_trace(span,level='ERROR',status_message=type(error).__name__)
                finally:
                    record['seconds']=round(time.monotonic()-started,3)
                    save(self.directory/'receipt.json',self.receipt)
        return record

    async def task(self, *, item, **_kwargs):
        names=[n for n in item.input['judge_ids'] if not self.receipt['selected_judges'] or n in self.receipt['selected_judges']]
        values=await asyncio.gather(*(self.call(name,item.input) for name in names))
        output=dict(case_id=item.input['case_id'],judgments=dict(zip(names,values)))
        self.receipt['results'].append(dict(input=item.input,expected_output=item.expected_output,output=output))
        save(self.directory/'receipt.json',self.receipt)
        print(json.dumps(dict(completed_cases=len(self.receipt['results']),judge_calls=len(self.receipt['calls']))),flush=True)
        return output


def summarize(results):
    by_judge=defaultdict(lambda:dict(planned=0,available=0,agreement=0,mistakes=[],unavailable_cases=[]))
    for case in results:
        for name,row in case['output']['judgments'].items():
            group=by_judge[name];group['planned']+=1
            if row['available']:
                group['available']+=1
                compared=grade(row['actual'],case['expected_output'][name])
                group['agreement']+=int(compared['agreement'])
                if not compared['agreement']:group['mistakes'].append(dict(case_id=case['input']['case_id'],
                    family=case['input']['family'],problems=compared['problems'],actual=row['actual'],expected=case['expected_output'][name]))
            else:group['unavailable_cases'].append(dict(case_id=case['input']['case_id'],error_type=row.get('error_type')))
    return dict(by_judge)


def readback(client, experiment_id, dataset_id, results, *, started_at):
    rows=cursor_pages(client.api.experiments.list_items,experiment_id=experiment_id,
        dataset_id=dataset_id,from_start_time=started_at,fields='core,dataset,io,scores',score_limit=50,
        request_options={'timeout_in_seconds':30,'max_retries':0})
    wanted={r['input']['case_id']:r for r in results};seen=set()
    if len(rows)!=len(wanted):return dict(verified=False,reason='experiment_item_count',items=len(rows))
    ids=sorted({s.id for row in rows for s in (row.scores or [])})
    if not ids:return dict(verified=False,reason='scores_pending',items=len(rows))
    # Experiment summaries omit score details in events-only deployments.
    details={}
    for offset in range(0,len(ids),50):
        for score in cursor_pages(client.api.scores_v3.get_many_v3,
                id=','.join(ids[offset:offset+50]),fields='details,subject'):
            if score.id not in ids or score.id in details:
                return dict(verified=False,reason='score_identity',items=len(rows))
            details[score.id]=score
    def decoded(value):return json.loads(value) if isinstance(value,str) else value
    for row in rows:
        content={k:decoded(getattr(row,k)) for k in ('input','output','expected_output')}
        key=content['input'].get('case_id') if isinstance(content['input'],dict) else None
        if key not in wanted or key in seen or row.experiment_dataset_id!=dataset_id:
            return dict(verified=False,reason='experiment_identity',items=len(rows))
        seen.add(key);expected=wanted[key]
        if any(content[k]!=expected[k] for k in ('input','output','expected_output')):
            return dict(verified=False,reason='experiment_content',items=len(rows))
        for score in evaluations(**expected):
            matches=[details[s.id] for s in (row.scores or []) if s.id in details and s.name==score.name]
            if len(matches)!=1 or type(matches[0].value) not in (int,float) or matches[0].value!=score.value:
                return dict(verified=False,reason='missing_or_wrong_named_score',items=len(rows))
            metadata=getattr(matches[0],'metadata',None) or {}
            if any(metadata.get(key)!=value for key,value in score.metadata.items()):
                return dict(verified=False,reason='score_provenance',items=len(rows))
            subject=matches[0].subject
            if subject.kind!='observation' or subject.trace_id!=row.trace_id or subject.id!=row.id:
                return dict(verified=False,reason='score_subject',items=len(rows))
    return dict(verified=seen==set(wanted),items=len(rows))


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--split',choices=['development','holdout','all'],default='all')
    parser.add_argument('--judge',action='append',choices=sorted(judges()))
    parser.add_argument('--case',action='append')
    parser.add_argument('--label',default='calibration')
    parser.add_argument('--credential-file',type=Path,default=Path.home()/'llm_provider/.env')
    parser.add_argument('--env-file',type=Path,default=ROOT/'.env')
    parser.add_argument('--base-url',help='Host-accessible URL of the existing gateway; credentials/model still come from --env-file')
    parser.add_argument('--output-root',type=Path,default=ROOT/'var/judge-calibration')
    parser.add_argument('--max-calls',type=int,default=256)
    parser.add_argument('--timeout',type=float,default=180,help='Per-call seconds, at most 240; recorded in the receipt')
    args=parser.parse_args(argv)
    all_rows=cases()
    selected=[r for r in all_rows if (args.split=='all' or r['input']['split']==args.split)
        and (not args.judge or set(args.judge)&set(r['input']['judge_ids']))
        and (not args.case or r['input']['case_id'] in args.case)]
    calls=sum(len(set(r['input']['judge_ids']) & set(args.judge or judges())) for r in selected)
    if not selected or not 1<=args.max_calls<=256 or calls>args.max_calls or not 0<args.timeout<=240:
        raise ValueError('Invalid or over-budget selection')
    if args.case and set(args.case)!={r['input']['case_id'] for r in selected}:raise ValueError('Unknown selected case')
    if not args.execute:
        print(json.dumps(dict(dataset=DATASET,items=len(all_rows),selected_items=len(selected),judges=len(judges()),
            planned_model_calls=calls,model_calls=0,human_reviewed=False,label_origin=ORIGIN)))
        return 0
    from dotenv import dotenv_values
    from scripts.langfuse_prompt_client import prompt_client
    config=dotenv_values(args.env_file,interpolate=False)
    if args.base_url:config['MEMORY_SPARK_LLM_BASE_URL']=args.base_url
    if config.get('MEMORY_SPARK_LLM_MODEL')!='gpt-6.1-sol':raise ValueError('Calibration uses the requested GPT-6.1 Sol model')
    if not config.get('MEMORY_SPARK_LLM_BASE_URL') or not config.get('MEMORY_SPARK_LLM_API_KEY'):
        raise ValueError('Missing existing gateway configuration')
    config.setdefault('MEMORY_SPARK_LLM_REASONING_EFFORT','low')
    revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    run_id=args.label+'-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid4().hex[:8]
    directory=args.output_root/run_id;directory.mkdir(parents=True,mode=0o700)
    client=prompt_client(args.credential_file)
    try:
        dataset,snapshot=publish(client,all_rows)
        items=[i for i in dataset.items if i.input['case_id'] in {r['input']['case_id'] for r in selected}]
        receipt=dict(schema_version='memoir-shared-judge-calibration-run/1',run_id=run_id,dataset=DATASET,dataset_id=dataset.id,
            source_revision=revision,runner_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            fixture_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),label_origin=ORIGIN,human_reviewed=False,
            model=config['MEMORY_SPARK_LLM_MODEL'],effort=config['MEMORY_SPARK_LLM_REASONING_EFFORT'],split=args.split,
            selected_judges=args.judge,planned_calls=calls,planned_items=len(items),calls=[],results=[],
            limits=dict(max_calls=args.max_calls,concurrency=4,seconds=1800,per_call_seconds=args.timeout,transport_retries=0),
            dataset_version=snapshot.isoformat(),status='running')
        save(directory/'receipt.json',receipt)
        runner=Runner(client,config,directory,receipt,maximum=args.max_calls,timeout=args.timeout)
        result=client.run_experiment(name='evaluation/memoir-judges.calibration',run_name=run_id,data=items,
            task=runner.task,evaluators=[evaluations],max_concurrency=4,_dataset_version=snapshot,
            metadata=dict(synthetic='true',label_origin=ORIGIN,human_reviewed='false',split=args.split,source_revision=revision))
        receipt.update(experiment_id=result.experiment_id,experiment_url=result.dataset_run_url,
            summary=summarize(receipt['results']))
        client.flush()
        for _ in range(12):
            receipt['readback']=readback(client,result.experiment_id,dataset.id,receipt['results'],started_at=snapshot)
            if receipt['readback']['verified']:break
            time.sleep(2)
        complete=len(receipt['results'])==len(items) and len(receipt['calls'])==calls
        receipt['status']='passed' if complete and receipt['readback']['verified'] and all(
            s['planned']==s['available']==s['agreement'] for s in receipt['summary'].values()) else 'failed'
        save(directory/'receipt.json',receipt)
        print(json.dumps(dict(status=receipt['status'],receipt=str(directory/'receipt.json'),
            experiment_url=receipt['experiment_url'],summary=receipt['summary'],readback=receipt['readback'])),flush=True)
        return int(receipt['status']!='passed')
    finally:client.shutdown()


if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as error:
        raise SystemExit('Calibration failed: '+type(error).__name__) from None
