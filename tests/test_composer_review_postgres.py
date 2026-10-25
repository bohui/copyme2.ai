"""Semantic review must authorize the exact candidate before a private save."""
import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace

import httpx
import pytest

from apps.api.lifetime_memory_composer import execute_lifetime_lane
from apps.api.lifetime_memory_lane_engine import BoundedLaneInput, LanePublication, run_bounded_lane
from test_canonical_composer_provenance import controlled_draft
from test_conversation_reply_transport import events, sse
from test_agent_commit_postgres import as_user
from test_agent_commit_postgres import database as base_database
from test_lifetime_memory_lane_engine import BUDGET
from controlled_composer_review import WHITESPACE_ONLY, controlled_review
from test_composer_runtime_craft import CRAFT_FAULTS, craft_report, corrupt_craft

from test_lifetime_composer_capacity import (sql, event_database, private_database, attachment_database,  # noqa: F401
    seeded_composer, section_result, service, rpc, literal, resolve, create_lane, OWNER)


@pytest.fixture(scope='module')
def database():
    yield from base_database.__wrapped__(publication_tcp=True)


def test_pg_zero_craft_scores_remain_advisory_after_durable_save(sql):
    identity, source, lane, claim = seeded_composer(sql)
    result = section_result(claim)
    unit = dict(section_id='part', field='text', excerpt=source['text'],
        source_refs=result['sections'][0]['source_refs'])
    result['review'].update(contract_version=3, craft=craft_report(dict(prose=[unit],
        contributions=result['review']['contributions'])))
    service(sql, 'commit_lifetime_memoir_lane_page', f"'{lane}','{claim['token']}',0,{literal(result)}")
    service(sql, 'complete_lifetime_memoir_lane', f"'{lane}','{claim['token']}'")
    head = json.loads(sql(as_user("select to_jsonb(public.read_lifetime_private_draft_head("
        + literal(identity['project_id']) + "));", OWNER)).stdout.strip())
    assert head['status'] == 'ready' and head['preview']['text'] == 'I grew up in Chengde.'
    assert 'craft' not in head and 'suggested_follow_up' not in head['preview']


@pytest.mark.parametrize('fault', CRAFT_FAULTS)
def test_pg_craft_contract_and_exact_witnesses_cannot_be_bypassed(sql, fault):
    identity, source, lane, claim = seeded_composer(sql)
    result = section_result(claim)
    unit = dict(section_id='part',field='text',excerpt=source['text'],source_refs=result['sections'][0]['source_refs'])
    result['review']['craft'] = craft_report(dict(prose=[unit],contributions=result['review']['contributions']))
    corrupt_craft(result['review']['craft'],fault)
    with pytest.raises(AssertionError, match='review'):
        service(sql,'commit_lifetime_memoir_lane_page',f"'{lane}','{claim['token']}',0,{literal(result)}")
    assert sql('select count(*) from public.user_lifetime_lane_page_receipt;').stdout.strip() == '0'


@pytest.mark.parametrize('verdict', [None, 'unsupported', 'contradicted', 'uncertainty_lost', 'attribution_lost'])
@pytest.mark.parametrize('severity', ['warning', 'info'])
def test_pg_ready_flag_cannot_authorize_an_unclassified_remove_warning(sql, verdict, severity):
    identity, source, lane, claim = seeded_composer(sql)
    result = section_result(claim, 'I grew up beside a blue river in Chengde.')
    result['review']['findings'] = [dict(severity=severity,
        explanation='Remove the unsupported blue river; no original supplies it.')]
    if verdict is not None:
        result['review']['findings'][0]['verdict'] = verdict
    with pytest.raises(AssertionError, match='review'):
        service(sql, 'commit_lifetime_memoir_lane_page', f"'{lane}','{claim['token']}',0,{literal(result)}")
    assert sql('select count(*) from public.user_lifetime_lane_page_receipt;').stdout.strip() == '0'
    assert rpc(sql, 'read_lifetime_private_draft_head', literal(identity['project_id']))['preview'] is None


def test_pg_empty_findings_cannot_replace_a_prose_and_contribution_audit(sql):
    identity, source, lane, claim = seeded_composer(sql)
    result = section_result(claim, 'I grew up beside a blue river in Chengde.')
    result['review'] = dict(ready_for_user_review=True, publication_approved=False, findings=[])
    with pytest.raises(AssertionError, match='review'):
        service(sql, 'commit_lifetime_memoir_lane_page', f"'{lane}','{claim['token']}',0,{literal(result)}")
    assert sql('select count(*) from public.user_lifetime_lane_page_receipt;').stdout.strip() == '0'


def test_pg_prose_witness_cannot_describe_different_text(sql):
    identity, source, lane, claim = seeded_composer(sql)
    result = section_result(claim)
    ref = {key: str(value) if key == 'version' else value
        for key, value in result['sections'][0]['source_refs'][0].items()}
    result['review'] = dict(contract_version=3, ready_for_user_review=True, publication_approved=False,
        craft=result['review']['craft'],
        findings=[], prose_checks=[dict(section_id='part', field=field, excerpt=text,
            verdict='supported', source_refs=[ref], explanation='Supported by original testimony.')
            for field, text in [('text', 'An entirely different passage.'), ('title', 'Childhood')]],
        contributions=[dict(source_ref=ref, quote=source['text'], disposition='represented',
            prose=[dict(section_id='part', field='text', excerpt=source['text'])], reason='Included in the passage.')])
    with pytest.raises(AssertionError, match='review'):
        service(sql, 'commit_lifetime_memoir_lane_page', f"'{lane}','{claim['token']}',0,{literal(result)}")


@pytest.mark.parametrize('whitespace', WHITESPACE_ONLY)
@pytest.mark.parametrize('deferred', [False, True])
def test_pg_blank_witness_cannot_claim_a_partially_represented_original(sql, whitespace, deferred):
    identity, source, lane, claim = seeded_composer(sql)
    prose = 'I' + whitespace + 'grew up.'
    result = section_result(claim, prose)
    item, = result['review']['contributions']
    if deferred:
        item.update(disposition='deferred', prose=[], reason='The passage omits Chengde; the original is only partly represented.')
        service(sql, 'commit_lifetime_memoir_lane_page', f"'{lane}','{claim['token']}',0,{literal(result)}")
        service(sql, 'complete_lifetime_memoir_lane', f"'{lane}','{claim['token']}'")
        # splitlines() would split legal JSON string content at U+0085/U+2028.
        head = json.loads(sql(as_user("select to_jsonb(public.read_lifetime_private_draft_head("
            + literal(identity['project_id']) + "));", OWNER)).stdout.strip())
        assert head['status'] == 'ready' and head['preview']['text'] == prose
    else:
        item['prose'] = [dict(section_id='part', field='text', excerpt=whitespace)]
        with pytest.raises(AssertionError, match='review'):
            service(sql, 'commit_lifetime_memoir_lane_page', f"'{lane}','{claim['token']}',0,{literal(result)}")
        assert sql('select count(*) from public.user_lifetime_lane_page_receipt;').stdout.strip() == '0'
    assert sql(f"select text from public.user_narrator_source where id='{source['id']}';").stdout.strip() == 'I grew up in Chengde.'


@pytest.mark.parametrize('fault', ['missing_prose', 'duplicate_prose', 'negative_prose', 'missing_contribution',
    'duplicate_contribution', 'wrong_quote', 'foreign_ref', 'false_representation', 'unknown_version'])
def test_pg_ready_audit_must_bind_exact_prose_sources_and_complete_coverage(sql, fault):
    identity, source, lane, claim = seeded_composer(sql)
    result = section_result(claim)
    review = result['review']
    if fault == 'missing_prose':
        review['prose_checks'].pop()
    elif fault == 'duplicate_prose':
        review['prose_checks'].append(deepcopy(review['prose_checks'][0]))
    elif fault == 'negative_prose':
        review['prose_checks'][0]['verdict'] = 'attribution_lost'
    elif fault == 'missing_contribution':
        review['contributions'].clear()
    elif fault == 'duplicate_contribution':
        review['contributions'].append(deepcopy(review['contributions'][0]))
    elif fault == 'wrong_quote':
        review['contributions'][0]['quote'] = 'An invented original.'
    elif fault == 'foreign_ref':
        review['prose_checks'][0]['source_refs'][0]['version'] = '99'
    elif fault == 'false_representation':
        review['contributions'][0]['prose'][0]['excerpt'] = 'A passage that is not in this manuscript.'
    else:
        review['contract_version'] = 99
    with pytest.raises(AssertionError, match='review'):
        service(sql, 'commit_lifetime_memoir_lane_page', f"'{lane}','{claim['token']}',0,{literal(result)}")
    assert sql('select count(*) from public.user_lifetime_lane_page_receipt;').stdout.strip() == '0'


@pytest.mark.parametrize('locale,texts', [
    ('en-AU', ['As a child I repaired bicycles with Father in our shed.',
        'Father told me he repaired neighbours\u2019 bicycles before I was born. I did not witness those years.',
        'A later caption called it a garage. I remember a shed and have not supplied a photograph.']),
    ('zh-CN', ['小时候，我和父亲在棚屋里修自行车。',
        '父亲告诉我，在我出生之前他就替邻居修自行车。我没有亲眼见过那些年。',
        '后来的一条说明称它为车库。我记得是棚屋，也没有提供照片。']),
])
def test_pg_contributions_may_be_explicitly_deferred_but_citations_cannot_hide_omission(sql, locale, texts):
    from uuid import UUID
    identity = resolve(sql)
    sql(f"insert into public.user_profile(user_id,profile) values('{OWNER}',{literal({'preferred_language':locale})}::jsonb) "
        "on conflict(user_id) do update set profile=excluded.profile;")
    sources = [rpc(sql, 'accept_user_narrator_source', f"{literal(identity['project_id'])},'{UUID(int=index+1)}',{literal(text)}")
        for index, text in enumerate(texts)]
    refs = [dict(source_id=source['id'], version=1, char_start=0, char_end=len(source['text']), quote=source['text']) for source in sources]
    rpc(sql, 'apply_user_memory_events', f"{literal(identity['project_id'])},{literal([dict(id=s['id'], version=1) for s in sources])},"
        f"{literal([dict(kind='event', title='Bicycle repairs', source_refs=refs)])}")
    lane = create_lane(sql, identity, 'composer')
    # This SQL-only helper creates a lane with the table's English default;
    # normal receipt scheduling supplies the chosen edition locale explicitly.
    sql(f"update public.user_memoir_lane set locale={literal(locale)} where id='{lane}';")
    claim = service(sql, 'claim_memoir_lane', f"'{lane}',900")
    assert claim['locale'] == locale
    result = section_result(claim, texts[0])
    for item in result['review']['contributions']:
        if item['source_ref']['source_id'] != sources[0]['id']:
            item.update(disposition='deferred', prose=[],
                reason='The attributed pre-birth account or caption conflict is outside this focused childhood passage; it is not represented by a citation.')
    deferred = next(item for item in result['review']['contributions'] if item['source_ref']['source_id'] == sources[1]['id'])
    rating = next(item for item in result['review']['craft']['ratings'] if item['criterion'] == 'fairness')
    rating['source_evidence'] = [dict(source_ref=deepcopy(deferred['source_ref']),excerpt=deferred['quote'][:160])]
    rating['reason'] = 'The attributed account is deferred, so its literary treatment cannot be assessed in this passage.'
    missing = deepcopy(result)
    missing['review']['contributions'].pop()
    with pytest.raises(AssertionError, match='review'):
        service(sql, 'commit_lifetime_memoir_lane_page', f"'{lane}','{claim['token']}',0,{literal(missing)}")
    checkpoint_key = 'b' * 64
    saved_checkpoint = sql(f"set role service_role;select to_jsonb(public.save_memoir_checkpoint("
        f"'{lane}','{claim['token']}','{checkpoint_key}','compose',"
        f"{literal(dict(phase='saving', review=result['review']))},'{claim['page_digest']}'));")
    assert json.loads(saved_checkpoint.stdout.strip()) is True
    service(sql, 'commit_lifetime_memoir_lane_page', f"'{lane}','{claim['token']}',0,{literal(result)}")
    root = service(sql, 'complete_lifetime_memoir_lane', f"'{lane}','{claim['token']}'")
    head = rpc(sql, 'read_lifetime_private_draft_head', literal(identity['project_id']))
    assert head['status'] == 'ready' and head['preview']['text'] == texts[0], json.dumps(dict(
        head=head, root=root, locale=claim['locale'], page=claim['page_number']), ensure_ascii=False)
    # Original quotes remain in the fenced private execution checkpoint, not
    # copied into every reader section (which has narrower dependencies).
    saved = json.loads(sql(f"select value->'review'->'contributions' from public.user_memoir_checkpoint "
        f"where lane_id='{lane}' and key='{checkpoint_key}';").stdout.strip())
    assert sum(item['disposition'] == 'deferred' for item in saved) == 2
    saved_craft = json.loads(sql(f"select value->'review'->'craft' from public.user_memoir_checkpoint "
        f"where lane_id='{lane}' and key='{checkpoint_key}';").stdout.strip())
    assert next(item for item in saved_craft['ratings'] if item['criterion'] == 'fairness')['source_evidence'] == rating['source_evidence']
    rpc(sql, 'change_user_narrator_source', f"{literal(identity['project_id'])},'{sources[1]['id']}',1,'withdraw',null")
    assert sql(f"select count(*) from public.user_memoir_checkpoint where lane_id='{lane}' and key='{checkpoint_key}';").stdout.strip() == '0'


@pytest.mark.parametrize('mode', ['unsupported', 'contradicted', 'uncertainty_lost', 'attribution_lost',
    'negative_prose', 'editorial', 'repair', 'craft_repair', 'legacy_restart', 'legacy_v2'])
def test_semantic_review_repairs_or_saves_through_sql(sql, monkeypatch, tmp_path, mode):
    monkeypatch.setenv('MEMOIR_LIFETIME_MEMORY', 'true')
    monkeypatch.setenv('MEMOIR_COMPOSER_MODEL', BUDGET.model)
    from test_lifetime_composer_capacity import OWNER
    identity, source, lane, claim = seeded_composer(sql)
    publisher = LanePublication(sql.publication_dsn, authenticated_owner=OWNER)
    sent = []
    cancelled = False

    class Broker:
        async def rpc(self, name, **payload):
            nonlocal cancelled
            cancel = (not cancelled and name == 'save_memoir_checkpoint' and
                (mode == 'legacy_restart' and payload['p_value'].get('phase') == 'reviewing'
                 or mode == 'legacy_v2' and payload['p_value'].get('phase') == 'saving'))
            if cancel:
                if mode == 'legacy_v2':
                    payload['p_value']['review'].pop('craft')
                    payload['p_value']['review']['contract_version'] = 2
                else:
                    payload['p_value']['review'] = dict(ready_for_user_review=True, publication_approved=False, findings=[])
            args = ','.join(f'{key}=>{literal(value)}' for key, value in payload.items())
            value = json.loads(sql(f"set role service_role;select coalesce(to_jsonb(public.{name}({args})),'null'::jsonb);").stdout.strip())
            if cancel:
                cancelled = True
                raise asyncio.CancelledError('Legacy saved-review restart fixture')
            return value

    async def worker(request):
        bounded = BoundedLaneInput.model_validate(json.loads(request.content)['bounded_lane'])

        async def provider(incoming):
            body = json.loads(b''.join([chunk async for chunk in incoming.stream]))
            payload = json.loads(body['input'])['payload']
            sent.append(bounded.phase)
            assert 'whole-life' in body['instructions'] and 'Vulnerability' in body['instructions']
            if bounded.phase == 'draft':
                supported = mode in ('editorial', 'legacy_restart', 'legacy_v2', 'craft_repair') or mode == 'repair' and sent.count('draft') > 1
                output = controlled_draft(payload, source['text'] if supported else 'I grew up beside a blue river in Chengde.', 'Childhood')
            else:
                schema = body['text']['format']['schema']
                assert schema['properties']['contract_version']['const'] == 3 and 'craft' in schema['required']
                repaired = mode == 'repair' and sent.count('draft') > 1
                verdict = 'editorial' if mode == 'editorial' else 'unsupported' if mode in ('repair', 'negative_prose', 'legacy_restart') else mode
                findings = [] if repaired or mode in ('negative_prose', 'legacy_restart', 'legacy_v2', 'craft_repair') else [dict(
                    verdict=verdict, severity='warning', explanation='Editorial rhythm suggestion.' if mode == 'editorial' else 'Remove the unsupported river.')]
                output = controlled_review(payload, findings=findings)
                output['craft'] = craft_report(payload['requirements'], score=3)
                if mode == 'craft_repair' and sent.count('review') == 1:
                    output['craft']['ratings'][0]['source_evidence'][0]['source_ref']['version'] = '99'
                if mode == 'craft_repair' and sent.count('review') == 2:
                    assert payload['review_errors'] == ['CRAFT_SOURCE_MISMATCH', 'CRAFT_PROSE_MISMATCH']
                if mode == 'negative_prose':
                    output['prose_checks'][0].update(verdict='unsupported', explanation='The river is absent from originals.')
            return httpx.Response(200, content=sse(events(json.dumps(output))))

        return httpx.Response(200, json=await run_bounded_lane(command=['must-not-start'],
            home_root=tmp_path / 'homes', base_url='https://provider.invalid/v1',
            api_key='fixture-composer-key', model=BUDGET.model, bounded_lane=bounded,
            publisher=publisher, provider_transport=httpx.MockTransport(provider), timeout=5))

    scope = SimpleNamespace(broker=Broker(), worker_url='https://worker.invalid',
        worker_secret='synthetic', worker_transport=httpx.MockTransport(worker), lane_publisher=publisher)
    if mode in ('editorial', 'repair', 'craft_repair', 'legacy_restart', 'legacy_v2'):
        if mode in ('legacy_restart', 'legacy_v2'):
            with pytest.raises(asyncio.CancelledError):
                asyncio.run(execute_lifetime_lane(claim, scope))
            service(sql, 'yield_lifetime_memoir_lane', f"'{lane}','{claim['token']}'")
            claim = service(sql, 'claim_memoir_lane', f"'{lane}',900")
        result = asyncio.run(execute_lifetime_lane(claim, scope))
        assert result['status'] == 'saved' and result['retrieval_complete']
        expected = ['draft', 'review', 'review'] if mode in ('craft_repair', 'legacy_v2') else ['draft', 'review'] * (2 if mode == 'repair' else 1)
        assert sent == expected
        assert rpc(sql, 'read_lifetime_private_draft_head', literal(identity['project_id']))['preview']['text'] == source['text']
        assert sql(f"select count(*) from public.user_memoir_checkpoint where lane_id='{lane}' "
            "and value->'review'->>'contract_version'='3';").stdout.strip() == '1'
    else:
        with pytest.raises(RuntimeError, match='another composition review'):
            asyncio.run(execute_lifetime_lane(claim, scope))
        assert sent == ['draft', 'review'] * 3
        assert sql('select count(*) from public.user_lifetime_lane_page_receipt;').stdout.strip() == '0'
