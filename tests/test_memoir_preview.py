import asyncio
import copy
import json
import time

import pytest
from fastapi.testclient import TestClient

from apps.api import memoir_preview
from apps.api.agent_lock import AgentTurnLease
from apps.api.main import create_app
from apps.api.store import MemoryStore
from test_recall import RecallStorage
from test_story_flow import _auth_headers


@pytest.fixture(autouse=True)
def private_queue(monkeypatch, tmp_path):
    monkeypatch.setenv('MEMORY_SPARK_TASK_DB', str(tmp_path / 'preview.sqlite'))


def prepare(client, payload):
    response = client.post('/v1/story/preview', headers=_auth_headers(), json=payload)
    assert response.status_code in {200, 202}, response.text
    result = response.json()
    if result['status'] == 'ready':
        return result
    for _ in range(150):
        result = client.get('/v1/story/preview/' + result['job']['id'], headers=_auth_headers()).json()
        if result['status'] not in {'pending', 'loading'}:
            return result
        time.sleep(.02)
    pytest.fail('Fixture preview did not finish')


@pytest.mark.parametrize('reply', ['{"ready":true}', '```json\n{"ready":true}\n```', '```\n{"ready":true}\n```'])
def test_composer_json_may_have_a_markdown_envelope(reply):
    assert memoir_preview.json_reply(reply) == {'ready': True}


def test_composer_commentary_is_not_accepted_as_a_candidate():
    with pytest.raises(ValueError):
        memoir_preview.json_reply('Here is the result: {"ready":true}')


def test_index_versions_are_bound_to_the_immutable_source_registry():
    request = {'sources': [{'id': 's1', 'version': 'immutable-hash'}],
               'periods': [], 'events': [{'id': 'e1', 'summary': 'Original fact',
                    'source_refs': [{'source_id': 's1', 'version': 'mistyped-hash? no'}]}]}
    bound = memoir_preview.bind_index_sources(request)
    assert bound['events'][0]['source_refs'] == [{'source_id': 's1', 'version': 'immutable-hash'}]
    assert bound['events'][0]['summary'] == 'Original fact'
    assert request['events'][0]['source_refs'][0]['version'] == 'mistyped-hash? no'


@pytest.mark.parametrize('sources', [[], [{'id': 's1', 'version': 'v1'}, {'id': 's1', 'version': 'v2'}]])
def test_index_cannot_bind_unknown_or_ambiguous_source_references(sources):
    request = {'sources': sources, 'periods': [], 'events': [
        {'source_refs': [{'source_id': 's1', 'version': 'invented'}]}]}
    with pytest.raises(ValueError, match='source reference'):
        memoir_preview.bind_index_sources(request)


def test_composition_retry_preserves_rejected_candidate_and_exact_validation(monkeypatch):
    request = {'sources': [], 'periods': [], 'events': []}
    checkpoint = {'request': request}
    rejected = {'text': 'candidate requiring correction'}
    validation = {'ok': False, 'errors': [{'code': 'UNKNOWN_EVENT', 'at': 'event-ledger'}]}
    saved = []
    calls = []
    async def operation(kind, *args):
        return {'ready': True} if kind == 'plan' else validation
    async def progress(phase):
        saved.append(copy.deepcopy(checkpoint))
    async def call(*args):
        calls.append(copy.deepcopy(args[-1]))
        if len(calls) == 1:
            return rejected
        raise TimeoutError('interrupted correction')
    monkeypatch.setattr(memoir_preview, 'skill_operation', operation)
    monkeypatch.setattr(memoir_preview, 'composer_call', call)
    for _ in range(2):
        with pytest.raises(TimeoutError):
            asyncio.run(memoir_preview.compose_candidate(request, None, None, 'p', 'zh-CN',
                        checkpoint=checkpoint, progress=progress))
    assert saved[-1]['repair'] == {'candidate': rejected, 'validation': validation, 'review': None}
    assert calls[-1]['candidate'] == rejected
    assert calls[-1]['validation'] == validation


@pytest.mark.parametrize('phase', ['index', 'draft', 'review'])
def test_composer_wire_schemas_support_chatgpt_strict_output(phase):
    # ChatGPT strict structured output rejects optional object properties,
    # including properties of referenced definitions used by later phases.
    def check(value):
        if isinstance(value, dict):
            if 'const' in value:
                assert 'type' in value
            if value.get('type') == 'object':
                assert set(value.get('required', [])) == set(value.get('properties', {}))
                assert value.get('additionalProperties') is False
            for child in value.values():
                check(child)
        elif isinstance(value, list):
            for child in value:
                check(child)

    check(memoir_preview.composer_output_schema(phase))


@pytest.mark.parametrize('phase', ['index', 'draft'])
def test_composer_transport_accepts_null_offsets_without_changing_domain_refs(phase):
    import httpx
    from types import SimpleNamespace
    from apps.api.codex_runtime import CodexRuntime
    from jsonschema import Draft202012Validator

    original = json.loads((memoir_preview.SKILL / 'examples/focused_trial' /
                           ('request.json' if phase == 'index' else 'draft.json')).read_text())
    expected = {key: original[key] for key in ('periods', 'events')} if phase == 'index' else original
    wire_reply = copy.deepcopy(expected)

    def add_null_offsets(value):
        if isinstance(value, dict):
            if 'source_id' in value and 'version' in value:
                value.setdefault('char_start', None)
                value.setdefault('char_end', None)
            for child in value.values():
                add_null_offsets(child)
        elif isinstance(value, list):
            for child in value:
                add_null_offsets(child)

    add_null_offsets(wire_reply)
    Draft202012Validator(memoir_preview.composer_output_schema(phase)).validate(wire_reply)
    runtime = CodexRuntime(worker_url='http://worker.test', worker_secret='test-only',
                           worker_transport=httpx.MockTransport(lambda request:
                               httpx.Response(200, json={'reply': json.dumps(wire_reply)})))
    result = asyncio.run(memoir_preview.composer_call(runtime, SimpleNamespace(user_id='test-user'),
                                                   'project', 'zh-CN', phase, {}))
    assert result == expected  # Preserve real quote offsets and other nullable fields.


def fixture_storage(name='focused_trial', anonymous=False):
    original = json.loads((memoir_preview.SKILL / f'examples/{name}/request.json').read_text())
    storage = RecallStorage(completed=20, anonymous=anonymous)
    storage._memories = [{
        'id': source['id'], 'kind': 'agent',
        'content': f"Storyteller: {source['text']}\nMemory Spark: Invented assistant biography",
    } for source in original['sources']]
    return storage, original


def model_fixture(monkeypatch, name='focused_trial', *, review_ready=True):
    calls = []
    original = json.loads((memoir_preview.SKILL / f'examples/{name}/request.json').read_text())
    candidate = json.loads((memoir_preview.SKILL / f'examples/{name}/draft.json').read_text())

    async def call(runtime, storage, project_id, language, phase, packet):
        calls.append(phase)
        request = packet if phase == 'index' else packet['request']
        versions = {source['id']: source['version'] for source in request['sources']}
        if phase == 'index':
            versions.update({source['id']: source['version'] for source in request['context'].get('original_source_manifest', [])})

        def rewrite(value):
            if isinstance(value, dict):
                if 'source_id' in value:
                    value['version'] = versions[value['source_id']]
                for child in value.values():
                    rewrite(child)
            elif isinstance(value, list):
                for child in value:
                    rewrite(child)

        if phase == 'index':
            result = copy.deepcopy({key: original[key] for key in ['periods', 'events']})
            rewrite(result)
            assert all('Invented assistant biography' not in source['text'] for source in request['sources'])
            assert request['trigger']['free_round_limit'] == 20
            return result
        if phase == 'review':
            return {'ready_for_user_review': review_ready, 'publication_approved': False, 'findings': []}
        draft = copy.deepcopy(candidate)
        draft['questions_for_mira'] = []
        for chapter in draft['chapters']:
            chapter['blocks'] = [block for block in chapter['blocks'] if block['type'] != 'image']
        rewrite(draft)
        plan = packet['plan']
        draft.update(project_id=project_id, input_snapshot_id=request['snapshot']['id'],
                     input_fingerprint=plan['input_fingerprint'], counter=plan['counter'])
        return draft

    monkeypatch.setattr(memoir_preview, 'composer_call', call)
    return calls


def test_later_preview_reuses_saved_index_and_only_reads_edited_period(monkeypatch):
    storage,_=fixture_storage('broad_trial')
    calls=model_fixture(monkeypatch,'broad_trial')
    with TestClient(create_app(MemoryStore(),story_storage_factory=lambda authorization:storage)) as client:
        assert prepare(client,{'project_id':'project-preview','language':'en-AU'})['status']=='ready'
        original_call=memoir_preview.composer_call
        packets=[]
        async def record(*args):
            if args[-2]=='index':
                packets.append(copy.deepcopy(args[-1]))
            return await original_call(*args)
        monkeypatch.setattr(memoir_preview,'composer_call',record)
        edited=next(r for r in storage._memories if r['id']=='s_child')
        edited['content']=edited['content'].replace('Storyteller: ','Storyteller: I recall this clearly. ',1)
        edited['life_stage']='childhood'
        assert prepare(client,{'project_id':'project-preview','language':'en-AU'})['status']=='ready'
        assert [s['id'] for s in packets[0]['sources']]==['s_child']
        assert packets[0]['context']['changed_source_ids']==['s_child']
        assert {e['id'] for e in packets[0]['context']['previous_index']['events']}=={'e_work','e_sydney'}
        assert calls==['index','draft','review','index','draft','review']


@pytest.mark.parametrize('name,kind', [('focused_trial', 'sample_chapter'), ('broad_trial', 'sample_storyline')])
@pytest.mark.parametrize('anonymous', [False, True])
def test_free_preview_is_composed_reviewed_saved_and_cached(monkeypatch, name, kind, anonymous):
    monkeypatch.setenv('MEMORY_SPARK_FREE_RECALL_ROUNDS', '20')
    storage, _ = fixture_storage(name, anonymous)
    calls = model_fixture(monkeypatch, name)
    with TestClient(create_app(MemoryStore(), story_storage_factory=lambda authorization: storage)) as client:
        result = prepare(client, {'project_id': 'project-preview'})
        assert result['status'] == 'ready'
        assert result['preview']['kind'] == kind
        assert result['preview']['text']
        assert calls == ['index', 'draft', 'review']
        assert storage.completed == 20
        bundle = json.loads(storage._memories[-1]['content'])
        assert bundle['validation']['ok']
        assert bundle['markdown']
        repeat = client.post('/v1/story/preview', headers=_auth_headers(), json={'project_id': 'project-preview'})
        assert repeat.json()['cached'] is True
        assert len(calls) == 3
    assert not storage.held


def test_preview_is_not_started_before_backend_limit(monkeypatch):
    storage, _ = fixture_storage()
    storage.completed = 19
    calls = model_fixture(monkeypatch)
    client = TestClient(create_app(MemoryStore(), story_storage_factory=lambda authorization: storage))
    response = client.post('/v1/story/preview', headers=_auth_headers(), json={'project_id': 'project-preview'})
    assert response.status_code == 409
    assert not calls


def test_failed_evidence_review_never_persists_preview(monkeypatch):
    storage, _ = fixture_storage()
    calls = model_fixture(monkeypatch, review_ready=False)

    async def run():
        async with AgentTurnLease(storage) as lease:
            await memoir_preview.compose_preview(storage, lease, 'project-preview')

    with pytest.raises(RuntimeError, match='composition review'):
        asyncio.run(run())
    assert calls == ['index', 'draft', 'review', 'draft', 'review', 'draft', 'review']
    assert not any(any(path.startswith('memoir-preview:') for path in row.get('source_paths', []))
                   for row in storage._memories)
    assert storage.completed == 20


def test_old_source_edit_invalidates_cached_preview(monkeypatch):
    storage, _ = fixture_storage()
    calls = model_fixture(monkeypatch)
    with TestClient(create_app(MemoryStore(), story_storage_factory=lambda authorization: storage)) as client:
        payload = {'project_id': 'project-preview'}
        first = prepare(client, payload)
        # Edit the narrator portion, not the assistant portion.
        storage._memories[0]['content'] = storage._memories[0]['content'].replace('blue door', 'blue wooden door')
        old = client.get('/v1/story/preview/' + first['job']['id'], headers=_auth_headers()).json()
        assert old['status'] == 'stale'
        assert old['preview'] is None
        second = prepare(client, payload)
        assert second['status'] == 'ready'
        assert first['preview']['id'] != second['preview']['id']
        assert len(calls) == 6


def test_slow_preview_returns_immediately_deduplicates_and_is_owner_scoped(monkeypatch):
    import threading
    storage, _ = fixture_storage()
    entered, release = threading.Event(), threading.Event()
    phases = model_fixture(monkeypatch)
    original = memoir_preview.composer_call

    async def slow(*args):
        if args[4] == 'index':
            entered.set()
            while not release.is_set():
                await asyncio.sleep(.01)
        return await original(*args)

    monkeypatch.setattr(memoir_preview, 'composer_call', slow)
    other, _ = fixture_storage()
    other.user_id = 'another-owner'
    factory = lambda authorization: other if authorization == 'Bearer other-test-user' else storage
    with TestClient(create_app(MemoryStore(), story_storage_factory=factory)) as client:
        started = time.monotonic()
        response = client.post('/v1/story/preview', headers=_auth_headers(), json={'project_id': 'project-preview'})
        assert response.status_code == 202
        assert time.monotonic() - started < 1
        assert entered.wait(1)
        job = response.json()['job']
        duplicate = client.post('/v1/story/preview', headers=_auth_headers(), json={'project_id': 'project-preview'}).json()
        assert duplicate['job']['id'] == job['id']
        assert client.get('/v1/story/preview/' + job['id'], headers={'Authorization': 'Bearer other-test-user'}).status_code == 404
        release.set()
        result = prepare(client, {'project_id': 'project-preview'})
        assert result['status'] == 'ready'
        assert phases == ['index', 'draft', 'review']
    assert not storage.held


def test_failed_review_is_terminal_and_error_logs_omit_private_details(monkeypatch, caplog):
    storage, _ = fixture_storage()
    model_fixture(monkeypatch, review_ready=False)
    with TestClient(create_app(MemoryStore(), story_storage_factory=lambda authorization: storage)) as client:
        result = prepare(client, {'project_id': 'project-preview'})
        assert result['status'] == 'error'
        assert result['job']['status'] == 'FAILED'
        assert result['job']['error'] == 'PREVIEW_UNAVAILABLE'
    assert 'failure_type=RuntimeError' in caplog.text
    assert not any(source['content'] in caplog.text for source in storage._memories)
    assert not storage.held


def test_offline_provider_is_terminal_without_automatic_retry(monkeypatch):
    import httpx
    storage, _ = fixture_storage()
    calls = []
    async def offline(*args):
        calls.append(args[4])
        response = httpx.Response(503, headers={'X-Error-Code':'COMPOSER_PROVIDER_UNAVAILABLE'},
                                  request=httpx.Request('POST','http://worker.test/turn'))
        response.raise_for_status()
    monkeypatch.setattr(memoir_preview, 'composer_call', offline)
    with TestClient(create_app(MemoryStore(), story_storage_factory=lambda authorization: storage)) as client:
        result = prepare(client, {'project_id':'project-preview'})
        assert result['status'] == 'error'
        assert result['job']['error'] == 'PREVIEW_PROVIDER_UNAVAILABLE'
        assert result['job']['attempts'] == 1
        for _ in range(3):
            assert client.get('/v1/story/preview/' + result['job']['id'],headers=_auth_headers()).json()['status'] == 'error'
        assert calls == ['index']
    assert not storage.held


def test_review_retry_reuses_validated_index_and_draft(monkeypatch):
    import httpx
    storage, _ = fixture_storage()
    calls = model_fixture(monkeypatch)
    original = memoir_preview.composer_call
    review_calls = 0

    async def flaky(*args):
        nonlocal review_calls
        if args[4] == 'review':
            review_calls += 1
            if review_calls == 1:
                raise httpx.ReadTimeout('synthetic-private-error-text')
        return await original(*args)

    monkeypatch.setattr(memoir_preview, 'composer_call', flaky)
    with TestClient(create_app(MemoryStore(), story_storage_factory=lambda authorization: storage)) as client:
        result = prepare(client, {'project_id': 'project-preview'})
        assert result['status'] == 'ready'
        assert result['job']['attempts'] == 2
        assert calls == ['index', 'draft', 'review']
    assert storage.completed == 20


@pytest.mark.parametrize('phase', ['index', 'draft', 'review'])
def test_composer_transport_has_separate_bounded_timeout(monkeypatch, phase):
    import httpx
    from apps.api.codex_runtime import CodexRuntime
    observed = []
    def reply(request):
        observed.append(request)
        return httpx.Response(200, json={'reply': '{"periods":[],"events":[]}'})
    runtime = CodexRuntime(worker_url='http://worker.test', worker_secret='test-only', timeout=1,
                           worker_transport=httpx.MockTransport(reply))
    storage, _ = fixture_storage()
    result = asyncio.run(memoir_preview.composer_call(runtime, storage, 'project', 'zh-CN', phase, {}))
    assert result == {'periods': [], 'events': []}
    assert observed[0].extensions['timeout']['read'] == (600 if phase == 'draft' else 240) + 15
    assert len(memoir_preview.composer_instructions('index')) < 2000


def test_shutdown_and_fresh_authenticated_request_resume_review_checkpoint(monkeypatch):
    import threading
    from apps.api.preview_jobs import PreviewJobs
    storage, _ = fixture_storage()
    calls = model_fixture(monkeypatch)
    original = memoir_preview.composer_call
    reviewing = threading.Event()
    block = [True]

    async def interrupted(*args):
        if args[4] == 'review' and block[0]:
            reviewing.set()
            while block[0]:
                await asyncio.sleep(.01)
        return await original(*args)

    monkeypatch.setattr(memoir_preview, 'composer_call', interrupted)
    app = create_app(MemoryStore(), story_storage_factory=lambda authorization: storage)
    with TestClient(app) as client:
        response = client.post('/v1/story/preview', headers=_auth_headers(), json={'project_id': 'project-preview'})
        job_id = response.json()['job']['id']
        assert reviewing.wait(2)
    assert not storage.held
    assert PreviewJobs().get(storage.user_id, job_id)['status'] == 'QUEUED'
    block[0] = False
    with TestClient(app) as client:
        result = prepare(client, {'project_id': 'project-preview'})
        assert result['status'] == 'ready'
        assert result['job']['id'] == job_id
    assert calls == ['index', 'draft', 'review']
    assert not storage.held


def test_thin_context_job_returns_insufficient_context_not_stale(monkeypatch):
    storage, _ = fixture_storage()
    async def empty(*args):
        return {'periods': [], 'events': []}
    monkeypatch.setattr(memoir_preview, 'composer_call', empty)
    with TestClient(create_app(MemoryStore(), story_storage_factory=lambda authorization: storage)) as client:
        result = prepare(client, {'project_id': 'project-preview'})
    assert result['status'] == 'insufficient_context'
    assert result['preview'] is None
    assert result['job']['outcome'] == 'insufficient_context'


def test_source_change_during_review_refuses_late_preview(monkeypatch):
    storage, _ = fixture_storage()
    model_fixture(monkeypatch)
    original = memoir_preview.composer_call
    async def edited(*args):
        result = await original(*args)
        if args[4] == 'review':
            storage._memories[0]['content'] = storage._memories[0]['content'].replace('blue door', 'wooden door')
        return result
    monkeypatch.setattr(memoir_preview, 'composer_call', edited)
    with TestClient(create_app(MemoryStore(), story_storage_factory=lambda authorization: storage)) as client:
        result = prepare(client, {'project_id': 'project-preview'})
    assert result['status'] == 'error'
    assert result['job']['error'] == 'PREVIEW_SOURCE_CHANGED'
    assert not any('memoir-preview:project-preview' in row.get('source_paths', []) for row in storage._memories)


def test_large_index_uses_bounded_packets_and_resumes_saved_batches(monkeypatch):
    import copy
    sources = [{'id': f's{i}', 'version': '1', 'text': f'Original {i}', 'life_stage': 'childhood'} for i in range(18)]
    request = {'sources': sources, 'periods': [], 'events': [], 'context': {}}
    packets = []
    saved = []
    checkpoint = {}
    async def progress(phase):
        saved.append(copy.deepcopy(checkpoint))
    async def call(runtime, storage, project, language, phase, packet):
        packets.append(copy.deepcopy(packet))
        if len(packets) == 2:
            raise TimeoutError('interrupted batch')
        return {'periods': [], 'events': [
            {'id': 'e' + s['id'], 'period_id': None, 'summary': s['text'],
             'source_refs': [{'source_id': s['id'], 'version': s['version']}]}
            for s in packet['sources']]}
    monkeypatch.setattr(memoir_preview, 'composer_call', call)
    with pytest.raises(TimeoutError):
        asyncio.run(memoir_preview.index_sources(request, None, None, 'p', 'zh-CN', checkpoint, progress))
    assert len(checkpoint['index_progress']['source_ids']) == 4
    assert checkpoint['index_batch_size'] == 2
    async def successful(runtime, storage, project, language, phase, packet):
        packets.append(copy.deepcopy(packet))
        return {'periods': [], 'events': [
            {'id': 'e' + s['id'], 'period_id': None, 'summary': s['text'],
             'source_refs': [{'source_id': s['id'], 'version': s['version']}]}
            for s in packet['sources']]}
    monkeypatch.setattr(memoir_preview, 'composer_call', successful)
    result = asyncio.run(memoir_preview.index_sources(request, None, None, 'p', 'zh-CN', checkpoint, progress))
    assert len(result['events']) == 18
    assert all(len(p['sources']) <= 4 for p in packets)
    assert all(len(p['sources']) <= 4 for p in packets[2:])
    assert {r['source_id'] for e in result['events'] for r in e['source_refs']} == {s['id'] for s in sources}
    assert {e['id'] for e in packets[-1]['context']['previous_index']['events']} == {f'es{i}' for i in range(16)}
    assert 'index_progress' not in checkpoint


@pytest.mark.parametrize('kind', ['sample_storyline', 'sample_chapter'])
def test_reader_preview_suppresses_only_leading_title_headings(kind):
    chapter = {'blocks': [
        {'type': 'heading', 'text': ' 从承德到悉尼 '},
        {'type': 'paragraph', 'text': '正文原样保留。'},
        {'type': 'heading', 'text': '晚年的记忆'},
        {'type': 'paragraph', 'text': '从承德到悉尼'},
        {'type': 'heading', 'text': '从承德到悉尼'},
    ]}
    bundle = {'preview': {'kind': kind, 'title': '从承德到悉尼', 'text': 'old rendered text'},
              'draft': {'storyline': chapter}, 'manuscript': {'chapters': [chapter]}}
    original = copy.deepcopy(bundle)
    assert memoir_preview.reader_preview(bundle)['text'] == '正文原样保留。\n\n晚年的记忆\n\n从承德到悉尼\n\n从承德到悉尼'
    assert bundle == original


def test_cached_sample_reprojects_title_without_recomposing():
    bundle = {'snapshot_key': 'k', 'preview': {'kind': 'sample_storyline', 'title': 'Sample', 'text': 'Sample\n\nBody'},
              'draft': {'storyline': {'blocks': [{'type': 'heading', 'text': 'Sample'}, {'type': 'paragraph', 'text': 'Body'}]}}}
    rows = [{'kind': 'memoir', 'source_paths': ['memoir-preview:p'], 'content': json.dumps(bundle)}]
    assert memoir_preview.cached_preview(rows, 'k')['text'] == 'Body'
