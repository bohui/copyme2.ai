"""Read-only, project-checked Langfuse metadata for the prompt coverage audit."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))

from scripts.langfuse_prompt_client import prompt_client


def pages(fetch, **kwargs):
    result=[]
    for page in range(1,101):
        response=fetch(page=page,limit=100,**kwargs)
        result.extend(response.data)
        if page>=response.meta.total_pages:return result
    raise ValueError('Page limit reached; snapshot is incomplete')


def cursor_pages(fetch, **kwargs):
    result=[];cursor=None;seen=set()
    for _ in range(100):
        response=fetch(cursor=cursor,limit=100,**kwargs)
        result.extend(response.data)
        cursor=response.meta.cursor
        if not cursor:return result
        if cursor in seen:raise ValueError('Repeated cursor; snapshot is incomplete')
        seen.add(cursor)
    raise ValueError('Cursor limit reached; snapshot is incomplete')


def sha(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def snapshot(client, project_id):
    projects=client.api.projects.get().data
    if len(projects)!=1 or projects[0].id!=project_id:
        raise ValueError('Credentials do not resolve to the requested Memoir project')
    prompts=pages(client.api.prompts.list)
    datasets=pages(client.api.datasets.list)
    def inspect(d):
        items=pages(client.api.dataset_items.list,dataset_name=d.name)
        beginning=datetime(1970,1,1,tzinfo=timezone.utc)
        runs=cursor_pages(client.api.experiments.list,from_start_time=beginning,
            dataset_id=d.id,fields='core,scores')
        observations=cursor_pages(client.api.experiments.list_items,from_start_time=beginning,
            dataset_id=d.id,fields='core,dataset,scores') if runs else []
        return dict(id=d.id,name=d.name,metadata={k:v for k,v in (d.metadata or {}).items()
            if k in {'target','content_sha256','synthetic','contains_customer_data','source_dataset_id','suite'}},
            items=[dict(id=i.id,status=str(i.status),case_id=i.input.get('case_id') if isinstance(i.input,dict) else None,
                input_sha256=sha(i.input),expected_sha256=sha(i.expected_output),
                input_keys=sorted(i.input) if isinstance(i.input,dict) else [],
                expected_keys=sorted(i.expected_output) if isinstance(i.expected_output,dict) else []) for i in items],
            runs=[dict(id=r.id,name=r.name) for r in runs],experiment_items=len(observations),
            scored_experiment_items=sum(bool(i.scores) for i in observations))
    with ThreadPoolExecutor(max_workers=4) as pool:
        observed=list(pool.map(inspect,datasets))
    return dict(project_id=project_id,captured_at=datetime.now(timezone.utc).isoformat(),
        scope='Metadata, case hashes and score presence; no trace text, model calls or mutations',
        prompts=[dict(name=p.name,versions=p.versions,labels=p.labels,tags=p.tags) for p in prompts],
        datasets=observed)


def local_hosted_metadata(credential_file, project_id):
    """Explicit local fallback for deployments without the hosted-evaluator API."""
    import psycopg
    from psycopg.rows import dict_row
    from dotenv import dotenv_values
    values=dotenv_values(credential_file,interpolate=False)
    with psycopg.connect(host='127.0.0.1',port=int(values['LANGFUSE_DB_HOST_PORT']),
        dbname=values['LANGFUSE_POSTGRES_DB'],user=values['LANGFUSE_POSTGRES_USER'],
        password=values['LANGFUSE_POSTGRES_PASSWORD'],connect_timeout=3,row_factory=dict_row,
        options='-c default_transaction_read_only=on -c statement_timeout=5000') as connection:
        if not connection.execute('select id from projects where id=%s',(project_id,)).fetchone():
            raise ValueError('Metadata database does not contain the requested project')
        evaluators=connection.execute('select distinct on(e.id) e.id,e.name,e.type,e.block_reason,e.blocked_at,'
            'v.version,v.prompt,v.model,v.provider,v.vars from evaluators e join evaluator_versions v '
            'on v.evaluator_id=e.id where e.project_id=%s order by e.id,v.version desc',(project_id,)).fetchall()
        rules=connection.execute('select id,name,status,filter,target_object,sampling,time_scope '
            'from evaluation_rules where project_id=%s order by name',(project_id,)).fetchall()
        assignments=connection.execute('select id,evaluation_rule_id,evaluator_id,variable_mapping '
            'from evaluation_rule_evaluator_assignments where project_id=%s',(project_id,)).fetchall()
    for item in evaluators:
        item['prompt_sha256']=hashlib.sha256((item.pop('prompt') or '').encode()).hexdigest()
    return dict(source='Project-scoped read-only local Langfuse metadata',project_id=project_id,
        evaluators=evaluators,rules=rules,assignments=assignments)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--credential-file',type=Path,default=Path.home()/'llm_provider/.env')
    parser.add_argument('--metadata-db',action='store_true',help='Also inspect local hosted evaluator/rule metadata in a read-only transaction')
    parser.add_argument('--output',type=Path,default=ROOT/'docs/prompt-audit-live.json')
    args=parser.parse_args(argv)
    project_id=json.loads((ROOT/'config/langfuse-evaluation-bindings.json').read_text())['project_id']
    client=prompt_client(args.credential_file)
    try:
        result=snapshot(client,project_id)
        if args.metadata_db:result['hosted_metadata']=local_hosted_metadata(args.credential_file,project_id)
        from scripts.run_memoir_skill_evaluation import datasets
        from scripts.audit_prompt_coverage import digest
        from scripts.langfuse_dataset_names import dataset_target
        hosted={d['name'] for d in result['datasets']}
        result['local_recipes_not_published']=[dict(name=n,target=dataset_target(n),items=len(r),
            content_sha256=digest(r),source='scripts/run_memoir_skill_evaluation.py:datasets')
            for n,r in datasets().items() if n not in hosted]
        args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str)+'\n')
        print(json.dumps(dict(prompts=len(result['prompts']),datasets=len(result['datasets']),
            experiment_items=sum(d['experiment_items'] for d in result['datasets']),
            scored_items=sum(d['scored_experiment_items'] for d in result['datasets']))))
    finally:
        client.shutdown()


if __name__=='__main__':
    try:
        main()
    except Exception as error:
        # SDK exceptions can contain full HTTP headers/bodies.
        raise SystemExit('Prompt snapshot failed: '+type(error).__name__) from None
