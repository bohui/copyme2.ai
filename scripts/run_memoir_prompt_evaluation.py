#!/usr/bin/env python3
"""Run the full supported campaign and expose every current prompt's evidence gap."""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import subprocess
import time
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))

from scripts.memoir_judge_calibration import SOURCE, cases, grade, request
from scripts.memoir_skill_eval_suite import digest
from scripts.prompt_registry import prompt_registry
from scripts.run_memoir_live_skills import save

TARGET='memoir/workflows/prompt-evaluation'


def calibrated(paths):
    """Require current pins and every development/holdout answer key; no human claim."""
    expected={(r['input']['case_id'],j):(r,j) for r in cases() for j in r['input']['judge_ids']}
    seen={};used=[]
    fixture=hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    receipts=[]
    for path in paths:
        receipt=json.loads(path.read_text())
        if not receipt.get('readback',{}).get('verified') or receipt.get('fixture_sha256')!=fixture:
            continue
        started=datetime.fromisoformat(receipt['dataset_version'])
        if started.tzinfo is None:raise ValueError('Calibration run timestamp needs its timezone')
        receipts.append((started,str(path),receipt))
    for _,path,receipt in sorted(receipts,key=lambda r:(r[0],r[1])):
        valid=[]
        for row in receipt['results']:
            for name,verdict in row['output']['judgments'].items():
                key=(row['input']['case_id'],name)
                if key not in expected:continue
                source,_=expected[key]
                if verdict.get('manifest')==request(name,source['input'])['manifest']:
                    # Latest current-pin attempt owns this key, including failure.
                    seen.pop(key,None)
                    if verdict.get('available') and grade(verdict['actual'],source['expected_output'][name])['agreement']:
                        seen[key]=verdict
                    valid.append(key)
        if valid:used.append(str(path))
    if set(seen)!=set(expected):
        raise ValueError(f'Current judge calibration is incomplete: {len(seen)}/{len(expected)} verified agreements. Run make llm_judge_calibrate.')
    return seen,used


def prompt_rows():
    coverage=json.loads((ROOT/'config/prompt-coverage.json').read_text())['prompts']
    return [dict(input=dict(case_id=name,prompt=name,**{k:pin[k] for k in ('version','sha256')},
                use=coverage[name]['use'],scenario=coverage[name]['scenario']),
            expected_output=dict(current_pin_observed=True))
        for name,path in sorted(prompt_registry().items())
        for pin in [json.loads((ROOT/(path+'.langfuse.json')).read_text())]]


def retained_campaigns(primary,rechecks):
    """Keep earlier experiments; only an identical-input/gold recheck can replace a case."""
    original={r['case_id']:r for r in primary['results']}
    for run in rechecks:
        ids=[r['case_id'] for r in run['results']]
        if not ids or len(ids)!=len(set(ids)) or set(ids)-set(original):
            raise ValueError('Unexpected or duplicate recheck case')
        for row in run['results']:
            if any(not row.get(k) or row[k]!=original[row['case_id']].get(k) for k in ('input_sha256','gold_sha256')):
                raise ValueError('Recheck input or gold differs from the retained campaign')
    from scripts.run_memoir_agent_evaluation import evaluated_status
    runs=deepcopy([primary,*rechecks])
    for run in runs:
        for row in run['results']:
            status=evaluated_status(row,run['calls'])
            if status!=row['status']:row.update(source_status=row['status'],status=status)
    return sorted(runs,key=lambda r:datetime.fromisoformat(r['started_at']))


def evidence(rows, calibration, campaign):
    observations=[]
    for (case_id,judge),call in calibration.items():
        observations.append(dict(manifest=call['manifest'],case_id=case_id,status='pass',
            scope='synthetic judge answer-key agreement',trace_id=call.get('trace_id')))
    runs=campaign if isinstance(campaign,list) else [campaign]
    latest={r['case_id']:run for run in runs for r in run['results']}
    for run in runs:
        current=[r for r in run['results'] if latest[r['case_id']] is run]
        for call in run['calls']:
            if not call.get('provider_response_id'):continue
            # Inline probes supply no managed source to credit.
            case=next((r for r in current if call['case_id']==r['case_id']
                or call['case_id'].startswith(r['case_id']+'/')),None)
            if case:
                observations.append(dict(manifest=call.get('prompt_manifest',{}),case_id=case['case_id'],
                    status=case['status'],scope=case['evidence_mode'],trace_id=call.get('trace_id'),run_id=run.get('run_id')))
        for case in current:
            for call in case.get('replay',{}).get('source_calls',[]):
                observations.append(dict(manifest=call.get('prompt_manifest',{}),case_id=case['case_id'],
                    status=case['status'],scope=case['evidence_mode'],trace_id=call.get('trace_id'),run_id=run.get('run_id'),
                    retained_provider_response=True))
            output=case.get('output') or {}
            if isinstance(output,dict) and output.get('model_invoked') and output.get('skill_receipt'):
                observations.append(dict(manifest=output['skill_receipt'].get('prompt_manifest',{}),
                    case_id=case['case_id'],status=case['status'],scope=case['evidence_mode'],run_id=run.get('run_id')))
    results=[]
    for row in rows:
        source=row['input']
        matches=[{k:v for k,v in o.items() if k!='manifest'} for o in observations if any(
            a['name']==source['prompt'] and a.get('version')==source['version'] and a.get('sha256')==source['sha256']
            for a in o['manifest'].get('artifacts',[]))]
        status=('fail' if any(m['status']=='fail' for m in matches) else
            'pass' if matches and all(m['status']=='pass' for m in matches) else 'unavailable')
        reason=(None if status=='pass' else 'An observed scenario failed or did not complete; see its case evidence.'
            if matches else 'No executed supported scenario supplied this current prompt pin; model-quality coverage remains missing.')
        results.append(dict(case_id=source['case_id'],status=status,current_pin_observed=bool(matches),evidence=matches,reason=reason,
            human_reviewed=False,canonical_delivery=False))
    return results


def scores(*,output,**_kwargs):
    from langfuse import Evaluation
    result=[Evaluation(name='current_pin_observed',value=int(output['current_pin_observed']),data_type='NUMERIC')]
    if output['status'] in {'pass','fail'}:
        result.append(Evaluation(name='observed_scenario_checks_pass',value=int(output['status']=='pass'),data_type='NUMERIC',
            comment='Code contracts or synthetic calibration agreement; no independent human quality acceptance.'))
    return result


def publish(client,rows,outputs,run_id):
    from scripts.run_memoir_skill_evaluation import publish_datasets
    from scripts.run_memoir_judge_calibration import PROJECT
    from scripts.snapshot_prompt_evaluations import cursor_pages
    if [p.id for p in client.api.projects.get().data]!=[PROJECT]:raise ValueError('Wrong Langfuse project')
    name=TARGET+'/golden/pins-'+digest(rows)[:12]
    datasets,_=publish_datasets(client,{name:rows},description='Current prompt pin coverage ledger. Missing scenarios are unavailable; observed pin coverage is not a model-quality score.')
    dataset=datasets[name];by_id={r['case_id']:r for r in outputs}
    started=datetime.now(timezone.utc)
    experiment=dataset.run_experiment(name='evaluation/memoir-prompts.coverage',run_name=run_id,
        task=lambda *,item,**kw:by_id[item.input['case_id']],evaluators=[scores],max_concurrency=1,
        metadata=dict(synthetic=True,human_reviewed=False,evidence_role='coverage ledger, not a model-quality score'))
    client.flush()
    verification=dict(verified=False)
    for attempt in range(15):
        items=cursor_pages(client.api.experiments.list_items,experiment_id=experiment.experiment_id,
            dataset_id=dataset.id,from_start_time=started,fields='core,dataset,io,scores',score_limit=10,
            request_options={'timeout_in_seconds':30,'max_retries':0})
        seen=set();valid=len(items)==len(rows)
        expected={r['input']['case_id']:r for r in rows}
        for item in items:
            values={k:json.loads(v) if isinstance(v,str) else v for k in ('input','output','expected_output')
                for v in [getattr(item,k)]}
            key=values['input'].get('case_id')
            if key not in expected or key in seen:valid=False;continue
            seen.add(key)
            valid &= item.experiment_dataset_id==dataset.id and values['input']==expected[key]['input']
            valid &= values['expected_output']==expected[key]['expected_output'] and values['output']==by_id[key]
            actual={s.name:s.value for s in item.scores or []}
            valid &= all(actual.get(s.name)==s.value for s in scores(output=by_id[key]))
        verification=dict(verified=bool(valid and seen==set(expected)),items=len(items),expected_items=len(rows))
        if verification['verified']:break
        time.sleep(2)
    return dict(dataset=name,dataset_id=dataset.id,experiment_id=experiment.experiment_id,
        experiment_url=experiment.dataset_run_url,readback=verification)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--calibration-receipt',type=Path,action='append')
    parser.add_argument('--agent-receipt',type=Path,help='Publish the retained complete campaign instead of dispatching again')
    parser.add_argument('--recheck-receipt',type=Path,action='append',default=[],help='Overlay selected identical-input/gold rechecks; retain earlier experiments')
    parser.add_argument('--gateway-url')
    parser.add_argument('--env-file',type=Path,default=ROOT/'.env')
    parser.add_argument('--credential-file',type=Path,default=Path.home()/'llm_provider/.env')
    parser.add_argument('--output-root',type=Path,default=ROOT/'var/prompt-evaluation')
    args=parser.parse_args(argv)
    from scripts.memoir_agent_eval_cases import catalog
    rows=prompt_rows();campaign_cases=catalog(full=True)
    if not args.execute:
        print(json.dumps(dict(prompts=len(rows),campaign_cases=len(campaign_cases),model_calls=0,
            prerequisite='make llm_judge_calibrate; complete current synthetic answer keys, Langfuse verified',
            limitations=['Missing executed branches remain unavailable in Langfuse.','Family runner is unwired; game/media outcome checks require their actual workflow.','Independent human calibration remains pending.'])))
        return 0
    calibration,paths=calibrated(args.calibration_receipt or list((ROOT/'var/judge-calibration').glob('*/receipt.json')))
    run_id='prompts-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid4().hex[:6]
    directory=args.output_root/run_id;directory.mkdir(parents=True,mode=0o700)
    if args.agent_receipt:agent_path=args.agent_receipt
    else:
        from scripts.run_memoir_agent_evaluation import main as agent_main
        arguments=['--execute','--publish','--full','--max-calls','400','--seconds','7200','--timeout','150','--workflow-timeout','600',
            '--env-file',str(args.env_file),'--credential-file',str(args.credential_file),'--output-root',str(directory/'agents')]
        if args.gateway_url:arguments+=['--gateway-url',args.gateway_url]
        code=agent_main(arguments)
        print(json.dumps(dict(agent_campaign_exit=code)),flush=True)
        agent_path=next((directory/'agents').glob('*/receipt.json'))
    campaign=json.loads(agent_path.read_text())
    if len(campaign['results'])!=len(campaign_cases) or {r['case_id'] for r in campaign['results']}!={c['id'] for c in campaign_cases}:
        raise ValueError('Full prompt coverage requires the complete campaign; do not pass a selected skill run')
    runs=retained_campaigns(campaign,[json.loads(p.read_text()) for p in args.recheck_receipt])
    outputs=evidence(rows,calibration,runs)
    from scripts.langfuse_prompt_client import prompt_client
    client=prompt_client(args.credential_file)
    try:hosted=publish(client,rows,outputs,run_id)
    finally:client.shutdown()
    receipt=dict(schema_version='memoir-prompt-evaluation/1',run_id=run_id,calibration_receipts=paths,
        source_revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        evaluator_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        agent_receipt_sha256=hashlib.sha256(agent_path.read_bytes()).hexdigest(),
        rechecks=[dict(receipt=str(p),sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in args.recheck_receipt],
        availability_regrades=[dict(run_id=r['run_id'],case_id=row['case_id'],source_status=row['source_status'],status=row['status'])
            for r in runs for row in r['results'] if row.get('source_status') and row['source_status']!=row['status']],
        agent_receipt=str(agent_path),results=outputs,hosted=hosted,human_reviewed=False,
        status='complete_with_gaps' if hosted['readback']['verified'] else 'publication_pending')
    save(directory/'receipt.json',receipt)
    lines=['# Current prompt evaluation','','Human calibration is pending. Observed scenarios are proposals/code contracts, not canonical UI delivery.','',
        '| Prompt | Result | Observed scenarios |','| --- | --- | ---: |']
    lines += [f"| {r['case_id']} | {r['status']} | {len(r['evidence'])} |" for r in outputs]
    (directory/'report.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps(dict(receipt=str(directory/'receipt.json'),hosted=hosted,
        counts={s:sum(r['status']==s for r in outputs) for s in ('pass','fail','unavailable')})),flush=True)
    return int(not hosted['readback']['verified'] or any(r['status']!='pass' for r in outputs))


if __name__=='__main__':
    raise SystemExit(main())
