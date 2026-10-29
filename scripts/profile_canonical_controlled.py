"""Provider-free canonical comparison candidate; no legacy prompt/resume claims.

This separately versioned diagnostic executes real SQL, runtime and private
workers. Its in-process Responses provider supplies synthetic proposals. Requested
settings and actual canonical reply policy are recorded separately. It
cannot establish model quality, effective provider effort, or latency acceptance.
"""
import argparse
import asyncio
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
from uuid import uuid4
from unittest.mock import patch

import httpx
from apps.api.codex_runtime import CodexRuntime
from apps.api.codex_worker_service import CodexWorker, WorkerTurnInput
from apps.api.lifetime_memory_engine import SUPPORTED_BYTE_BOUND_MODELS
from apps.api.turn_stream import turn_events
from scripts.canonical_turn import canonical_turn, CanonicalTurnFailed
from scripts.controlled_native_state import ROOT, controlled_database, open_case, snapshot_case
from scripts.controlled_lifecycle import ALLOCATION_ROOT_ENV, sigterm_cancellable


class WorkerStream(httpx.AsyncByteStream):
    def __init__(self, events): self.events = events
    async def __aiter__(self):
        async for event in self.events: yield event.encode()
    async def aclose(self): await self.events.aclose()


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


@contextmanager
def offline_settings():
    """Exclude inherited service authority for the whole run, including cleanup."""
    previous = dict(os.environ)
    prerequisites = {'PATH', 'HOME', 'TMPDIR', 'USER', 'LOGNAME', 'LANG', 'LC_ALL',
        'SHELL', 'LD_LIBRARY_PATH', 'MEMOIR_TEST_TEMPORAL_CLI', ALLOCATION_ROOT_ENV}
    environment = {key: value for key, value in previous.items() if key in prerequisites}
    environment.update(PYTHONPATH=str(ROOT), MEMOIR_TEST_POSTGRES_BACKEND='native',
        MEMORY_SPARK_HISTORICAL_NEWS='0', MEMORY_SPARK_DISABLE_PRIVDROP='1')
    os.environ.clear()
    os.environ.update(environment)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(previous)


@contextmanager
def settings(dsn, variant):
    values={'MEMOIR_PUBLICATION_DATABASE_URL':dsn,'MEMORY_SPARK_DISABLE_PRIVDROP':'1',
        'MEMOIR_TWO_LANES':'1',
        'MEMORY_SPARK_COLLECTOR_MODEL':variant['model'],
        'MEMORY_SPARK_COLLECTOR_REASONING_EFFORT':variant['requested_effort'],
        'MEMORY_SPARK_COLLECTOR_PROMPT_VERSION':variant['requested_prompt_version']}
    previous={key:os.environ.get(key) for key in values}
    os.environ.update(values)
    try:yield
    finally:
        for key,value in previous.items():
            if value is None:os.environ.pop(key,None)
            else:os.environ[key]=value


@contextmanager
def controlled_reply_provider():
    from apps.api import conversation_reply_transport, model_request
    send_reply = conversation_reply_transport.stream_reply
    replies = []
    def provider(request):
        body = json.loads(request.content)
        if body.get('stream'):
            replies.append(body)
            output = dict(acknowledgement='We can follow that memory.',
                question='What other details do you remember?', reason='latest_story',
                hint=None, quote=None, recall_limit_quote=None,
                work=dict(mode='extract', name=None), resolved_questions=[])
        else:
            output = dict(complete=True, restrictions=[], reason=None)
        text = json.dumps(output)
        response = dict(id='controlled-response-' + str(uuid4()), status='completed', model=body['model'],
            output=[dict(type='message', status='completed', role='assistant',
                content=[dict(type='output_text', text=text)])])
        if body.get('stream'):
            events = [dict(type='response.output_text.delta', delta=text),
                      dict(type='response.completed', response=response)]
            return httpx.Response(200, headers={'content-type':'text/event-stream'},
                content=''.join('data: ' + json.dumps(event) + '\n\n' for event in events))
        return httpx.Response(200, json=response)
    transport = httpx.MockTransport(provider)
    async def reply(**options):
        return await send_reply(**options, transport=transport)
    async def review(*args, **options):
        options.update(base_url='http://controlled.invalid/v1', api_key='controlled-provider-key', transport=transport)
        return await model_request.complete_json(*args, **options)
    with patch('apps.api.conversation_reply_transport.stream_reply', reply), \
            patch('apps.api.policy_review.complete_json', review):
        yield replies


@sigterm_cancellable
async def canonical_campaign(rounds, *, timeout=20, candidate_model='gpt-5.6-luna-memoir-low'):
    with offline_settings(), controlled_reply_provider():
        return await _canonical_campaign(rounds, timeout=timeout, candidate_model=candidate_model)


async def _canonical_campaign(rounds, *, timeout, candidate_model):
    if (not isinstance(rounds,list) or not 1<=len(rounds)<=50
        or any(not isinstance(text,str) or not text.strip() for text in rounds)
        or candidate_model not in SUPPORTED_BYTE_BOUND_MODELS):
        raise ValueError('Bounded synthetic inputs and a reviewed canonical model are required')
    if type(timeout) not in (int,float) or not 0<timeout<=60:
        raise ValueError('A finite controlled per-turn timeout is required')
    variants={'baseline':dict(model='gpt-5.6-luna-pooled',requested_effort='max',requested_prompt_version='reply-v2'),
        'candidate':dict(model=candidate_model,requested_effort='low',requested_prompt_version='reply-v2')}
    receipt={'schema_version':'memoir-canonical-controlled-comparison/2','status':'started',
        'evidence_mode':'mock_only','provider_requests_started':0,'variants':variants,'results':[],
        'effective_prompt_version':'reply-v2','thread_policy':'responses',
        'semantic_acceptance':'not_run','latency_acceptance':'not_run','effective_provider_effort':None,
        'legacy_prompt_comparison':'blocked_pending_benchmark_definition'}
    try:
        with tempfile.TemporaryDirectory(prefix='memoir-canonical-profile-') as directory:
            root=Path(directory)
            with controlled_database() as baseline_sql:
                baseline_sql('update public.lifetime_two_lane_rollout set enabled=true;')
                case={'id':'canonical-comparison','project_id':'controlled-comparison'}
                baseline,_,legacy=open_case(baseline_sql,case)
                try:
                    baseline.save_profile({'preferred_language':'en-AU'})
                    for ordinal,text in enumerate(rounds,1):
                        before=snapshot_case(baseline_sql,baseline,legacy)
                        state_hash=digest(before['canonical_state'])
                        with controlled_database() as candidate_sql:
                            candidate_sql('update public.lifetime_two_lane_rollout set enabled=true;')
                            candidate,_,_=open_case(candidate_sql,case,before)
                            try:
                                assert digest(snapshot_case(candidate_sql,candidate,legacy)['canonical_state'])==state_hash
                                turn_id=str(uuid4())
                                order=['baseline','candidate'] if ordinal%2 else ['candidate','baseline']
                                for variant in order:
                                    sql,storage=(baseline_sql,baseline) if variant=='baseline' else (candidate_sql,candidate)
                                    worker=CodexWorker(home_root=root/f'{ordinal}-{variant}',api_key='controlled-provider-key',
                                        base_url='http://controlled.invalid/v1',
                                        model=variants[variant]['model'],timeout=timeout,
                                        command=['forbidden-codex'])
                                    contacts=[]
                                    async def provider(request):
                                        payload=WorkerTurnInput.model_validate_json(request.content)
                                        contacts.append(payload.diagnostic_request_id)
                                        return httpx.Response(200,headers={'content-type':'application/x-ndjson'},
                                            stream=WorkerStream(turn_events(lambda emit:worker.turn(payload,on_delta=emit,on_event=emit.event))))
                                    runtime=CodexRuntime(home_root=root/'api',model=worker.model,
                                        base_url=worker.base_url,worker_url='http://controlled.invalid',
                                        worker_secret='synthetic',worker_transport=httpx.MockTransport(provider),timeout=timeout)
                                    timings={};started=time.monotonic()
                                    async def observe(event):
                                        if event['type']=='text_delta' and event.get('text'):
                                            timings.setdefault('first_visible_text_s',time.monotonic()-started)
                                        if event['type']=='conversation_saved':
                                            timings['conversation_saved_s']=time.monotonic()-started
                                    result={'round':ordinal,'variant':variant,'pre_state_sha256':state_hash,'input_sha256':digest(text),
                                        **variants[variant],'effective_prompt_version':'reply-v2','thread_policy':'responses',
                                        'effective_effort':None,'provider_request_count':None}
                                    with settings(sql.publication_dsn,variants[variant]):
                                        try:
                                            async with asyncio.timeout(timeout):
                                                delivered=await canonical_turn(runtime,storage,text,options=dict(project_id=case['project_id'],
                                                    language='en-AU',client_turn_id=turn_id),evaluation={'case_id':'canonical-comparison'},on_event=observe)
                                            result.update(status='saved',appserver_turns=sum(step['action']=='request.turn/start'
                                                for step in delivered['trajectory']['steps']))
                                        except (CanonicalTurnFailed,TimeoutError):
                                            result.update(status='failed',appserver_turns=None)
                                    result.update(timings=timings,private_worker_requests=len(contacts))
                                    receipt['results'].append(result)
                                    if result['status']!='saved':
                                        receipt['status']='incomplete'
                                        return receipt
                            finally:candidate.client.close()
                    receipt['status']='completed'
                finally:baseline.client.close()
        receipt['temporary_homes_removed']=not root.exists()
        return receipt
    finally:
        if 'root' in locals():
            receipt['temporary_homes_removed']=not root.exists()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inputs',type=Path,required=True,help='JSON array of synthetic narrator inputs')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--timeout',type=float,default=20)
    arguments=parser.parse_args()
    result=asyncio.run(canonical_campaign(json.loads(arguments.inputs.read_text()),timeout=arguments.timeout))
    arguments.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'status':result['status'],'evidence_mode':result['evidence_mode'],
        'provider_requests_started':result['provider_requests_started'],'output':str(arguments.output)}))
    raise SystemExit(0 if result['status']=='completed' else 1)
