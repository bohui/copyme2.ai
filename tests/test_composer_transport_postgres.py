"""Direct composer phases cross real SQL admission, proofs and private saves."""
from controlled_composer_review import controlled_review
import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from apps.api.lifetime_memory_composer import execute_lifetime_lane
from apps.api.lifetime_memory_lane_engine import BoundedLaneInput, LanePublication, run_bounded_lane
from apps.api.lifetime_memory_policy import PolicyUnavailable
from apps.api.lifetime_memory_publication import PublicationUnavailable
from test_canonical_composer_provenance import controlled_draft
from test_conversation_reply_transport import events, sse
from test_lifetime_composer_capacity import (sql, event_database, private_database, attachment_database,  # noqa: F401
    database, seeded_composer, rpc, literal, service, OWNER, OTHER)
from test_lifetime_memory_lane_engine import BUDGET


@pytest.mark.parametrize('fault', ['none', 'source_before_prepare', 'owner_before_prepare',
    'missing_prepare_proof', 'missing_draft_proof', 'policy_before_review',
    'policy_after_send', 'review_repair', 'review_blocks', 'cancel_review', 'restart_review'])
def test_direct_composer_keeps_phase_proofs_review_gate_and_sql_save(sql, monkeypatch, tmp_path, fault):
    monkeypatch.setenv('MEMOIR_LIFETIME_MEMORY', 'true')
    # Keep this cohort on semantic summarization so every model-phase fault
    # remains exercised; short lossless preparation has its own SQL cases.
    identity, source, lane, claim = seeded_composer(sql, summary_messages=('Thanks. ' * 160,) * 4)
    publisher = LanePublication(sql.publication_dsn,
        authenticated_owner=OTHER if fault == 'owner_before_prepare' else OWNER)
    attempts, sent, reviews = [], [], []

    class Broker:
        async def rpc(self, name, **payload):
            args = ','.join(f'{key}=>{literal(value)}' for key, value in payload.items())
            return json.loads(sql(f"set role service_role;select coalesce(to_jsonb(public.{name}({args})),'null'::jsonb);").stdout.strip())

    class Provider(httpx.AsyncBaseTransport):
        def __init__(self, bounded):
            self.bounded = bounded

        async def handle_async_request(self, request):
            phase = self.bounded.phase
            if fault == 'source_before_prepare' and phase == 'prepare':
                rpc(sql, 'change_user_narrator_source',
                    f"{literal(identity['project_id'])},'{source['id']}',1,'withdraw',null")
            elif fault == 'missing_prepare_proof' and phase == 'draft':
                sql("delete from public.user_lifetime_lane_output where phase='prepare';")
            elif fault == 'missing_draft_proof' and phase == 'review':
                sql("delete from public.user_lifetime_lane_output where phase='draft';")
            elif fault == 'policy_before_review' and phase == 'review':
                sql('update public.user_memoir_project set policy_epoch=policy_epoch+1;')
            raw = b''.join([chunk async for chunk in request.stream])
            body = json.loads(raw)
            assert body['input'] == self.bounded.packet
            assert body['tools'] == [] and body['tool_choice'] == 'none'
            assert body['metadata']['generation_name'] == 'memoir-composer'
            sent.append(phase)
            payload = json.loads(body['input'])['payload']
            if fault == 'policy_after_send' and phase == 'prepare':
                sql('update public.user_memoir_project set policy_epoch=policy_epoch+1;')
            if phase == 'prepare':
                value = dict(event_id=payload['partition']['id'], context='Original childhood evidence.',
                    source_refs=payload['partition']['source_refs'])
            elif phase == 'draft':
                value = controlled_draft(payload, source['text'], 'Childhood')
            else:
                reviews.append(payload['candidate'])
                if fault == 'cancel_review' or fault == 'restart_review' and len(reviews) == 1:
                    raise asyncio.CancelledError('Controlled review cancellation')
                blocking = fault == 'review_blocks' or fault == 'review_repair' and len(reviews) == 1
                value = controlled_review(payload, findings=[dict(verdict='unsupported', severity='blocking',
                    explanation='Controlled evidence review failure.')] if blocking else [])
                value['ready_for_user_review'] = not blocking
            return httpx.Response(200, content=sse(events(json.dumps(value))))

    async def worker(request):
        bounded = BoundedLaneInput.model_validate(json.loads(request.content)['bounded_lane'])
        attempts.append(bounded.phase)
        return httpx.Response(200, json=await run_bounded_lane(command=['must-not-start'],
            home_root=tmp_path / 'homes', base_url='https://provider.invalid/v1',
            api_key='fixture-composer-key', model=BUDGET.model, bounded_lane=bounded,
            publisher=publisher, provider_transport=Provider(bounded), timeout=5))

    scope = SimpleNamespace(broker=Broker(), worker_url='https://worker.invalid',
        worker_secret='synthetic', worker_transport=httpx.MockTransport(worker), lane_publisher=publisher)

    async def execute(current):
        return await execute_lifetime_lane(current, scope)

    # Bind the same configured byte-token route as the provider fixture.
    monkeypatch.setenv('MEMOIR_COMPOSER_MODEL', BUDGET.model)
    if fault in {'none', 'review_repair', 'restart_review'}:
        if fault == 'restart_review':
            with pytest.raises(asyncio.CancelledError):
                asyncio.run(execute(claim))
            assert sql('select count(*) from public.user_lifetime_lane_page_receipt;').stdout.strip() == '0'
            service(sql, 'yield_lifetime_memoir_lane', f"'{lane}','{claim['token']}'")
            resumed = service(sql, 'claim_memoir_lane', f"'{lane}',900")
            assert resumed['token'] != claim['token']
            outcome = asyncio.run(execute(resumed))
        else:
            outcome = asyncio.run(execute(claim))
        assert outcome['status'] == 'saved' and outcome['retrieval_complete']
        expected = ['prepare', 'draft', 'review']
        if fault == 'review_repair':
            expected += ['draft', 'review']
        elif fault == 'restart_review':
            expected += ['review']
        assert sent == attempts == expected
        head = rpc(sql, 'read_lifetime_private_draft_head', literal(identity['project_id']))
        assert head['status'] == 'ready' and head['preview']['text'] == source['text']
        assert head['publication_approved'] is False
        assert sql('select count(*) from public.user_lifetime_lane_page_receipt;').stdout.strip() == '1'
    else:
        error = asyncio.CancelledError if fault == 'cancel_review' else (
            RuntimeError if fault == 'review_blocks' else (PublicationUnavailable, PolicyUnavailable, AssertionError))
        with pytest.raises(error):
            asyncio.run(execute(claim))
        expected = {
            'source_before_prepare': [], 'owner_before_prepare': [],
            'missing_prepare_proof': ['prepare'], 'missing_draft_proof': ['prepare', 'draft'],
            'policy_before_review': ['prepare', 'draft'], 'policy_after_send': ['prepare'],
            'review_blocks': ['prepare', 'draft', 'review', 'draft', 'review', 'draft', 'review'],
            'cancel_review': ['prepare', 'draft', 'review'],
        }[fault]
        assert sent == expected
        assert sql('select count(*) from public.user_lifetime_lane_page_receipt;').stdout.strip() == '0'
        assert sql("select count(*) from public.user_lifetime_lane_snapshot where state='completed';").stdout.strip() == '0'
    assert not (tmp_path / 'homes').exists()


@pytest.mark.parametrize('fault', ['none', 'source_before_proof', 'policy_before_proof',
    'stale_page_digest', 'missing_prepare_proof', 'owner_before_draft'])
def test_short_original_batch_saves_without_a_summary_provider(sql, monkeypatch, tmp_path, fault):
    monkeypatch.setenv('MEMOIR_LIFETIME_MEMORY', 'true')
    monkeypatch.setenv('MEMOIR_COMPOSER_MODEL', BUDGET.model)
    identity, source, lane, claim = seeded_composer(sql)
    publisher = LanePublication(sql.publication_dsn,
        authenticated_owner=OTHER if fault == 'owner_before_draft' else OWNER)
    drafts = []

    class Broker:
        async def rpc(self, name, **payload):
            if name == 'record_lifetime_lane_output' and payload['p_phase'] == 'prepare':
                if fault == 'source_before_proof':
                    rpc(sql, 'change_user_narrator_source',
                        f"{literal(identity['project_id'])},'{source['id']}',1,'withdraw',null")
                elif fault == 'policy_before_proof':
                    sql('update public.user_memoir_project set policy_epoch=policy_epoch+1;')
                elif fault == 'stale_page_digest':
                    payload['p_page_digest'] = '0' * 64
            args = ','.join(f'{key}=>{literal(value)}' for key, value in payload.items())
            value = json.loads(sql(f"set role service_role;select coalesce(to_jsonb(public.{name}({args})),'null'::jsonb);").stdout.strip())
            if name == 'record_lifetime_lane_output' and payload['p_phase'] == 'prepare' and fault == 'missing_prepare_proof':
                sql("delete from public.user_lifetime_lane_output where phase='prepare';")
            return value

    async def worker(request):
        bounded = BoundedLaneInput.model_validate(json.loads(request.content)['bounded_lane'])

        async def provider(incoming):
            body = json.loads(b''.join([chunk async for chunk in incoming.stream]))
            payload = json.loads(body['input'])['payload']
            if bounded.phase == 'prepare':
                return httpx.Response(503)
            if bounded.phase == 'draft':
                drafts.append(payload)
                output = controlled_draft(payload, source['text'], 'Childhood')
            else:
                output = controlled_review(payload)
            return httpx.Response(200, content=sse(events(json.dumps(output))))

        return httpx.Response(200, json=await run_bounded_lane(command=['must-not-start'],
            home_root=tmp_path / 'homes', base_url='https://provider.invalid/v1',
            api_key='fixture-composer-key', model=BUDGET.model, bounded_lane=bounded,
            publisher=publisher, provider_transport=httpx.MockTransport(provider), timeout=5))

    scope = SimpleNamespace(broker=Broker(), worker_url='https://worker.invalid',
        worker_secret='synthetic', worker_transport=httpx.MockTransport(worker), lane_publisher=publisher)
    if fault != 'none':
        with pytest.raises((PublicationUnavailable, PolicyUnavailable, AssertionError)):
            asyncio.run(execute_lifetime_lane(claim, scope))
        assert drafts == []
        return
    outcome = asyncio.run(execute_lifetime_lane(claim, scope))
    assert outcome['status'] == 'saved' and outcome['retrieval_complete']
    head = rpc(sql, 'read_lifetime_private_draft_head', literal(identity['project_id']))
    assert head['status'] == 'ready' and head['preview']['text'] == source['text']
    assert head['publication_approved'] is False
    summary, = drafts[0]['request']['context']['prepared_partitions']
    assert summary['context'] == source['text']
    assert summary['source_refs'] == claim['batch']['events'][0]['source_refs']
