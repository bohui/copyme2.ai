"""Bounded canonical live comparison; synthetic local SQL, existing LLM gateway."""
import asyncio
from contextvars import ContextVar
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from uuid import uuid4

HERE=Path(__file__).resolve().parent
SOURCE=Path(sys.argv[1]).resolve()
ARM=sys.argv[2]
assert ARM in {'baseline','candidate'}
RUN=sys.argv[3] if len(sys.argv)>3 else ARM
assert RUN.startswith(ARM) and '/' not in RUN
OUTPUT=HERE/(RUN+'-live.json')
assert not OUTPUT.exists(), 'Preserve all earlier live evidence'
sys.path[:0]=[str(SOURCE),str(SOURCE/'tests')]
from dotenv import dotenv_values
import httpx
from scripts.evaluation_budget import BudgetedProvider,BudgetLimits
from scripts.controlled_lifecycle import new_native_root,reconcile_native_directory
from test_agent_commit_postgres import database,OWNER
from memoir_postgres_workflow import PostgresRest
from apps.api import policy_review,conversation_reply_transport
from apps.api.codex_runtime import CodexRuntime
from apps.api.model_request import complete_json
from scripts.canonical_turn import canonical_turn,CanonicalTurnFailed

config=dotenv_values(HERE.parents[1]/'.env',interpolate=False)
endpoint=config['MEMORY_SPARK_LLM_BASE_URL'].replace('http://192.168.65.1:4000','http://127.0.0.1:4000').rstrip('/')
key=config['MEMORY_SPARK_LLM_API_KEY']
model=config.get('MEMORY_SPARK_COLLECTOR_MODEL') or config['MEMORY_SPARK_LLM_MODEL']
effort=config.get('MEMORY_SPARK_COLLECTOR_REASONING_EFFORT') or 'low'
os.environ.update(MEMORY_SPARK_LLM_BASE_URL=endpoint,MEMORY_SPARK_LLM_API_KEY=key,
    MEMORY_SPARK_COLLECTOR_MODEL=model,MEMORY_SPARK_COLLECTOR_REASONING_EFFORT=effort,
    MEMORY_SPARK_COLLECTOR_PROMPT_VERSION='reply-v2',MEMOIR_TWO_LANES='1',
    MEMORY_SPARK_EARLY_POLICY_ACK='0',MEMOIR_INTERVIEW_STRATEGY='1',MEMORY_SPARK_TEST_MODE='1',
    MEMORY_SPARK_PARALLEL_POLICY_REVIEW='1' if ARM=='candidate' else '0')
for name in ('MEMORY_SPARK_CODEX_WORKER_URL','MEMORY_SPARK_TEST_MODE','MEMORY_SPARK_TASK_DB'):
    if name!='MEMORY_SPARK_TEST_MODE':os.environ.pop(name,None)
cases=json.loads((HERE/'live-cases.json').read_text())
report=dict(arm=ARM,source_root=str(SOURCE),model=model,requested_effort=effort,effective_effort='unverified',
    cases_sha256=hashlib.sha256((HERE/'live-cases.json').read_bytes()).hexdigest(),
    evidence_scope='Canonical API ASGI + real disposable SQL + live model; local PostgREST adapter, in-process generation, no deployed worker or browser paint.',
    hard_provider_cap_across_arms=80,per_call_timeout_s=60,turn_timeout_s=150,
    calls=[],turns=[],cleanup={},source_sha256={})
for folder in ('apps/api','skills/memoir-interviewer/prompts'):
    for path in sorted((SOURCE/folder).glob('*')):
        if path.is_file() and path.suffix in {'.py','.md','.json'}:
            report['source_sha256'][str(path.relative_to(SOURCE))]=hashlib.sha256(path.read_bytes()).hexdigest()
report['source_sha256']['supabase/migrations/202610180001_initial_schema.sql']=hashlib.sha256((SOURCE/'supabase/migrations/202610180001_initial_schema.sql').read_bytes()).hexdigest()
started=time.monotonic()
active=ContextVar('live_turn')
def save():
    encoded=json.dumps(report,ensure_ascii=False,indent=2,default=str)+'\n'
    assert key not in encoded
    temporary=OUTPUT.with_suffix('.json.tmp');temporary.write_text(encoded);temporary.replace(OUTPUT)


class RequestTap(httpx.AsyncByteStream):
    def __init__(self,source,row):self.source=source;self.row=row;self.data=bytearray()
    async def __aiter__(self):
        async for chunk in self.source:
            self.data.extend(chunk)
            yield chunk
        self.row['request']=json.loads(self.data)
    async def aclose(self):await self.source.aclose()


class ResponseTap(httpx.AsyncByteStream):
    def __init__(self,source,row):self.source=source;self.row=row;self.data=bytearray()
    def snapshot(self):
        raw=self.data.decode('utf-8',errors='replace');self.row['raw_provider_response']=raw
        if raw.startswith('data:'):
            for line in raw.splitlines():
                if not line.startswith('data:'):continue
                try:event=json.loads(line[5:])
                except ValueError:continue
                if event.get('type','').startswith('response.') and isinstance(event.get('response'),dict):
                    self.row['provider_response']=event['response']
        else:
            try:self.row['provider_response']=json.loads(raw)
            except ValueError:pass
    async def __aiter__(self):
        try:
            async for chunk in self.source:
                self.row.setdefault('first_provider_byte_s',time.monotonic()-started)
                self.data.extend(chunk)
                if len(self.data)>600_000:raise ValueError('Live evidence response exceeded bound')
                self.snapshot()
                yield chunk
        finally:
            self.snapshot()
    async def aclose(self):
        self.snapshot()
        await self.source.aclose()


class RecordingTransport(httpx.AsyncBaseTransport):
    def __init__(self,row):self.row=row;self.transport=httpx.AsyncHTTPTransport(retries=0)
    async def handle_async_request(self,request):
        request.stream=RequestTap(request.stream,self.row)
        response=await self.transport.handle_async_request(request)
        self.row['http_status']=response.status_code
        response.stream=ResponseTap(response.stream,self.row)
        return response
    async def aclose(self):await self.transport.aclose()


async def dispatch(kind,operation):
    earlier=sum(len(json.loads(p.read_text())['calls']) for p in HERE.glob('*-live.json') if p!=OUTPUT)
    if earlier+len(report['calls'])>=80:raise RuntimeError('Global live call cap reached')
    if time.monotonic()-started>1200:raise TimeoutError('Live arm deadline reached')
    row=dict(index=len(report['calls']),kind=kind,turn=active.get(),started_s=time.monotonic()-started)
    report['calls'].append(row);save()
    budget=BudgetedProvider(BudgetLimits(max_requests=1,max_input_tokens=200_000,
        max_output_tokens=8192,max_output_tokens_per_request=8192),max_elapsed_seconds=60)
    async def call(max_output_tokens):
        result=await operation(RecordingTransport(row))
        return dict(result=result,usage=row.get('provider_response',{}).get('usage'))
    try:
        result=await budget.call(call,input_tokens_upper_bound=200_000)
        row['status']='completed';return result['result']
    except BaseException as error:
        row.update(status='cancelled' if isinstance(error,asyncio.CancelledError) else 'failed',error_type=type(error).__name__)
        raise
    finally:
        row['finished_s']=time.monotonic()-started;row['budget']=budget.receipt();save()


original_review=policy_review.complete_json
async def review(name,payload,schema,**kwargs):
    return await dispatch('policy',lambda transport:original_review(name,payload,schema,transport=transport,**kwargs))
policy_review.complete_json=review
original_reply=conversation_reply_transport.stream_reply
async def reply(**kwargs):
    return await dispatch('reply',lambda transport:original_reply(**kwargs,transport=transport))
conversation_reply_transport.stream_reply=reply


async def run(sql):
    os.environ['MEMOIR_PUBLICATION_DATABASE_URL']=sql.publication_dsn
    for cohort in cases:
        language=cohort['language']
        sql('truncate public.user_memoir_project cascade; truncate public.user_memory,public.user_agent_turn_lease,public.user_recall_usage cascade;')
        sql("update public.user_profile set profile='{}'; update auth.users set is_anonymous=false;")
        project=None
        for case in cohort['turns']:
            row=dict(id=case['id'],language=language,input=case['text'],quality_rubric=case['quality'],heldout=case.get('heldout',False),
                events=[],started_s=time.monotonic()-started)
            report['turns'].append(row);active.set(language+':'+case['id']);save()
            old=sql('select coalesce(json_agg(json_build_object(\'id\',client_turn_id,\'collector\',collector) order by sequence),\'[]\') from public.user_interview_turn where collector is not null;').stdout
            storage=PostgresRest(sql,OWNER).storage()
            runtime=CodexRuntime(home_root=HERE/(ARM+'-homes'),base_url=endpoint,model=model,timeout=120)
            async def observe(event):
                row['events'].append(dict(elapsed_s=time.monotonic()-started-row['started_s'],event=event))
            try:
                async with asyncio.timeout(150):
                    result=await canonical_turn(runtime,storage,case['text'],options=dict(project_id=project,client_turn_id=str(uuid4()),language=language),on_event=observe)
                row['result']=result;row['status']='completed';project=result['project_id']
            except BaseException as error:
                row.update(status='failed',error_type=type(error).__name__)
                if hasattr(error,'trajectory'):row['trajectory']=error.trajectory
            finally:
                storage.client.close()
                row['finished_s']=time.monotonic()-started
                row['saved_turns']=json.loads(sql('select coalesce(json_agg(json_build_object(\'id\',client_turn_id,\'collector\',collector,\'sequence\',sequence) order by sequence),\'[]\') from public.user_interview_turn;').stdout)
                row['sources']=json.loads(sql('select coalesce(json_agg(json_build_object(\'id\',id,\'text\',text,\'version\',version,\'sequence\',sequence) order by sequence),\'[]\') from public.user_narrator_source;').stdout)
                row['prior_saved_snapshot']=json.loads(old)
                row['pending_policy_count']=int(sql('select count(*) from public.user_lifetime_pending_policy;').stdout)
                save()
                print(json.dumps(dict(arm=ARM,language=language,case=case['id'],status=row['status'],seconds=round(row['finished_s']-row['started_s'],3),calls=len(report['calls']))),flush=True)
            if row['status']!='completed':break


root=new_native_root('memoir-parallel-live-')
generator=database.__wrapped__(deadline=time.monotonic()+1500,directory_root=str(root))
save()
try:
    sql=next(generator)
    asyncio.run(run(sql))
finally:
    try:generator.close()
    finally:
        report['cleanup']=reconcile_native_directory(root,os.environ.copy())
        report['completed_s']=time.monotonic()-started
        save()
