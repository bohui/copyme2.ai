"""Offline admission, visible-input intent and truthful photo/browser receipts."""
import asyncio
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import memoir_fifty_photo as photo


def place(label='Hobart'):
    return {'schema_version': 1, 'place': label, 'hierarchy': ['Earth', 'Australia', label],
            'granularity': 'city', 'latitude': -42.88, 'longitude': 147.32}


@pytest.mark.parametrize('text,period', [
    ('Please show what Hobart looks like now, as a public reference, not as evidence of our house.', ''),
    ('A public photo of Hobart from around 1978 could prompt the setting, but it must be labelled historical.', '1978'),
    ('请找一张成都现在的公共照片作地点提示，不要把它说成我家的证据。', ''),
    ('如果展示成都一九八八年前后的公共老照片，请明确它只是历史参考。', '1988'),
])
def test_visible_positive_intent_uses_current_grounded_place(text, period):
    label = '成都' if '成都' in text else 'Hobart'
    assert photo.photo_intent(text, [place(label)])['period'] == period


@pytest.mark.parametrize('text', [
    'Do not search for another public photograph in this turn; I am only correcting the story.',
    'The Hobart photograph is mine, but its rights are private and its date unknown.',
    'I have no permission to publish the faces in the old Hobart photographs.',
    'My friend asks: "Please find public photos of Hobart now."',
    'I am not sure which town; show public photos of Hobart.',
    '这一轮我不需要公共照片，只想纠正成都和大理之间的时间顺序。',
    '我说的老街不确定是哪一条，请先问我，不要自动创建地点或照片搜索。',
    'I was born in Hobart and remember the harbour.',
    'Please show what Perth looks like now as a public reference.',
])
def test_negative_private_third_party_ambiguous_or_ungrounded_does_not_search(text):
    assert photo.photo_intent(text, [place()]) is None


def test_environment_has_no_inherited_service_or_model_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv('SUPABASE_SECRET_KEY', 'must-not-leak')
    monkeypatch.setenv('MEMORY_SPARK_LLM_API_KEY', 'must-not-leak')
    env = photo.photo_process_environment(tmp_path, {'GOOGLE_CSE_ID': 'existing-engine'}, str(tmp_path))
    assert env['MEMORY_SPARK_PHOTO_WEB_SEARCH'] == '0'
    assert not any('KEY' in key or 'SECRET' in key or 'WORKER_URL' in key for key in env)
    assert env['HOME'] == str(tmp_path)
    with pytest.raises(ValueError):
        photo.photo_process_environment(tmp_path, {'GOOGLE_CSE_API_KEY': 'not-allowed'}, str(tmp_path))


def test_partial_search_is_not_terminal_photo_evidence():
    assert photo.photo_observation({'status': 'SEARCHING', 'items': [], 'searching': True})['status'] == 'unavailable'
    assert photo.photo_observation({'status': 'UNAVAILABLE', 'items': [], 'searching': False})['status'] == 'unavailable'
    assert photo.photo_observation({'status': 'NO_MATCH', 'items': [], 'searching': False})['status'] == 'no_match'


def test_source_rights_and_capture_metadata_are_preserved_without_rights_invention():
    body = {'status': 'PARTIAL', 'searching': False, 'items': [{
        'source_url': 'https://commons.wikimedia.org/wiki/File:Test.jpg',
        'image_url': 'https://upload.wikimedia.org/Test.jpg', 'title': 'Public setting',
        'license': 'Unknown', 'date_expression': '', 'date_basis': 'Unknown capture date',
        'allowed_actions': {'embed': True, 'download': False, 'print': False},
        'search_fallback': 'gps_time'}]}
    observation = photo.photo_observation(body)
    assert observation['status'] == 'observed'
    assert observation['items'][0]['license'] == 'Unknown'
    assert observation['items'][0]['date_expression'] == ''
    assert observation['browser_status'] == 'not_run'
    body['items'][0]['source_url'] = 'http://127.0.0.1/private'
    assert photo.photo_observation(body)['status'] == 'unavailable'


class Run:
    run_id = 'test-run'
    source_revision = 'a' * 40
    case_ids = ('first',)
    def remaining_seconds(self): return 100
    def _begin_dispatch(self): self.started = getattr(self, 'started', 0) + 1; return True
    def _end_dispatch(self): self.started -= 1


def owned(text):
    return SimpleNamespace(run=Run(), evaluation_profile='subscription_fifty', _active=('first', 1),
        _pending=set(), case_plans={'first': {'project_id': 'project'}},
        bridge_for_case=lambda case: SimpleNamespace(driver_inputs=lambda: {'rounds': [text] * 50}))


def test_admission_is_required_before_native_allocation(tmp_path, monkeypatch):
    monkeypatch.setattr(photo, '_assert_session', lambda value: (_ for _ in ()).throw(ValueError('unowned')))
    with pytest.raises(ValueError):
        asyncio.run(photo.FiftyPhotoResearch.admit(session=object(), directory=tmp_path / 'not-created',
            python_binary='/bin/true', python_sha256='0' * 64, existing_public_settings={},
            playwright_browsers_path=str(tmp_path)))
    assert not (tmp_path / 'not-created').exists()


def test_owned_search_scope_dedupe_cap_and_shared_deadline(tmp_path, monkeypatch):
    monkeypatch.setattr(photo, '_assert_session', lambda value: None)
    binary = Path('/bin/true').resolve()
    session = owned('Please show what Hobart looks like now, as a public reference.')
    async def execute(self, request, timeout):
        assert timeout <= session.run.remaining_seconds()
        assert session.run.started == 1
        return {'status': 'NO_MATCH', 'searching': False, 'items': []}
    monkeypatch.setattr(photo.FiftyPhotoResearch, '_execute', execute)
    async def ready(self): return {'status': 'ready'}
    monkeypatch.setattr(photo.FiftyPhotoResearch, '_preflight', ready)
    async def scenario():
        adapter = await photo.FiftyPhotoResearch.admit(session=session, directory=tmp_path / 'photos',
            python_binary=str(binary), python_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
            existing_public_settings={}, playwright_browsers_path=str(tmp_path))
        first = await adapter.observe_round('first', 1, {'place_journeys': [place()]})
        assert first['called'] and first['model_requests_started'] == 0
        assert first['searches_started_case'] == 1
        with pytest.raises(ValueError):
            await adapter.observe_round('first', 1, {'place_journeys': [place()]})
        session._active = ('first', 2)
        await adapter.observe_round('first', 2, {'place_journeys': [place()]})
        session._active = ('first', 3)
        third = await adapter.observe_round('first', 3, {'place_journeys': [place()]})
        assert not third['called'] and third['reason'] == 'photo_search_limit'
        assert session.run.started == 0 and not session._pending
        await adapter.close()
    asyncio.run(scenario())


def test_browser_receipt_requires_real_observation_and_artifact(tmp_path):
    scope = {'run_id': 'run', 'source_revision': 'a' * 40, 'case_id': 'case', 'project_id': 'project',
             'round': 12, 'input_sha256': 'b' * 64}
    with pytest.raises(ValueError):
        photo.validate_browser_receipt({**scope, 'status': 'passed'}, expected_scope=scope, artifact_root=tmp_path)
    picture = tmp_path / 'render.png'
    picture.write_bytes(b'\x89PNG\r\n\x1a\ncontrolled-offline-artifact')
    receipt = {**scope, 'schema_version': 'memoir-fifty-browser-receipt/1',
        'evidence_mode': 'rendered_browser', 'status': 'passed',
        'observations': {'current_input_rendered': True, 'reply_rendered': True,
            'place_scope_matches': True, 'photo_source_labels_visible': True,
            'photo_rights_labels_visible': True, 'photo_date_labels_visible': True,
            'page_errors': [], 'unexpected_network_requests': []},
        'screenshots': [{'path': 'render.png', 'sha256': hashlib.sha256(picture.read_bytes()).hexdigest()}]}
    assert photo.validate_browser_receipt(receipt, expected_scope=scope, artifact_root=tmp_path)['status'] == 'passed'
    receipt['evidence_mode'] = 'fixture'
    with pytest.raises(ValueError):
        photo.validate_browser_receipt(receipt, expected_scope=scope, artifact_root=tmp_path)


def test_all_original_public_requests_and_private_refusals():
    import json
    root = Path(__file__).resolve().parents[1]
    cases = json.loads((root / 'tests/evaluation/memoir_five_case_inputs.json').read_text())['cases']
    labels = [('Hobart', 'Hobart', '1978'), ('成都', '成都', '1988'),
              ('Perth', 'Fremantle', '1989'), ('昆明', '昆明', '1990'), ('Sydney', 'Sydney', '1990')]
    for case, (current, historical, year) in zip(cases, labels):
        for number, label, period in ((12, current, ''), (22, historical, year)):
            intent = photo.photo_intent(case['rounds'][number - 1], [place(label)])
            assert intent is not None, (case['id'], number)
            assert (intent['place'], intent['period']) == (label, period)
        for number in (28, 35, 36, 47, 49):
            assert photo.photo_intent(case['rounds'][number - 1], [place(current), place(historical)]) is None


@pytest.mark.parametrize('url', ['https://example.com/cse?cx=engine',
    'http://cse.google.com/cse?cx=engine', 'https://cse.google.com/cse?cx=engine&redirect=http://localhost',
    'https://cse.google.com:443/anything?cx=engine', 'https://user:password@cse.google.com/cse?cx=engine'])
def test_public_configuration_rejects_custom_or_credential_urls(tmp_path, url):
    with pytest.raises(ValueError):
        photo.photo_process_environment(tmp_path, {'GOOGLE_CSE_URL': url}, str(tmp_path))


def test_no_match_with_failed_sources_is_not_photo_evidence():
    result = photo.photo_observation({'status': 'NO_MATCH', 'searching': False, 'items': [],
        'target_count': 10, 'shortfall': 10, 'failures': [{'provider': 'flickr', 'reason': 'robots_denied'}]})
    assert result['status'] == 'unavailable'
    assert result['failures'][0]['reason'] == 'robots_denied'


async def _test_adapter(tmp_path, monkeypatch, *, binary=None):
    import sys
    monkeypatch.setattr(photo, '_assert_session', lambda value: None)
    async def ready(self): return {'status': 'ready'}
    monkeypatch.setattr(photo.FiftyPhotoResearch, '_preflight', ready)
    binary = binary or Path(sys.executable).resolve()
    return await photo.FiftyPhotoResearch.admit(
        session=owned('Please show public photos of Hobart now.'), directory=tmp_path / 'photos',
        python_binary=str(binary), python_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
        existing_public_settings={}, playwright_browsers_path=str(tmp_path))


def test_mutated_executable_is_rejected_before_process_contact(tmp_path, monkeypatch):
    import shutil
    binary = tmp_path / 'pinned-python'
    shutil.copyfile('/bin/true', binary); binary.chmod(0o700)
    async def scenario():
        adapter = await _test_adapter(tmp_path, monkeypatch, binary=binary)
        binary.write_bytes(b'changed')
        monkeypatch.setattr(photo.subprocess, 'Popen', lambda *args, **kwargs: pytest.fail('No process contact allowed'))
        with pytest.raises(ValueError):
            await adapter._process([str(binary)], timeout=1, cwd=tmp_path, env=adapter.env)
        await adapter.close()
        assert adapter.snapshot()['cleanup_complete']
    asyncio.run(scenario())


def test_owned_process_timeout_and_cancellation_are_joined(tmp_path, monkeypatch):
    async def scenario():
        adapter = await _test_adapter(tmp_path, monkeypatch)
        with pytest.raises(photo.subprocess.TimeoutExpired):
            await adapter._process([adapter.binary, '-c', 'import time; time.sleep(10)'],
                timeout=.05, cwd=adapter.directory, env=adapter.env)
        assert adapter.snapshot()['cleanup_complete'] and adapter.process is None
        job = asyncio.create_task(adapter._process([adapter.binary, '-c', 'import time; time.sleep(10)'],
            timeout=10, cwd=adapter.directory, env=adapter.env))
        while adapter.process is None:
            await asyncio.sleep(.001)
        job.cancel()
        with pytest.raises(asyncio.CancelledError):
            await job
        assert adapter.snapshot()['cleanup_complete'] and adapter.process is None
        adapter.session._closed = True
        await adapter.close(); await adapter.close()
        assert adapter.snapshot()['closed']
    asyncio.run(scenario())


def test_unconfigured_native_capability_records_requested_search_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(photo, '_assert_session', lambda value: None)
    async def missing(self):
        return {'status': 'unavailable', 'reason': 'photo_browser_dependencies_missing'}
    monkeypatch.setattr(photo.FiftyPhotoResearch, '_preflight', missing)
    async def forbidden(*args, **kwargs): pytest.fail('No photo execution when unavailable')
    monkeypatch.setattr(photo.FiftyPhotoResearch, '_execute', forbidden)
    binary = Path('/bin/true').resolve()
    async def scenario():
        adapter = await photo.FiftyPhotoResearch.admit(
            session=owned('Please show public photos of Hobart now.'), directory=tmp_path / 'photos',
            python_binary=str(binary), python_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
            existing_public_settings={}, playwright_browsers_path=str(tmp_path))
        result = await adapter.observe_round('first', 1, {'place_journeys': [place()]})
        assert result['executed'] and not result['called'] and result['status'] == 'unavailable'
        assert result['reason'] == 'photo_browser_dependencies_missing'
        assert adapter.snapshot()['logical_searches_started'] == 0
        await adapter.close()
    asyncio.run(scenario())


def test_cleanup_failure_is_terminal_not_optional_partial(tmp_path, monkeypatch):
    async def scenario():
        adapter = await _test_adapter(tmp_path, monkeypatch)
        async def fail(*args, **kwargs): raise photo.PhotoCleanupError('Controlled failure')
        monkeypatch.setattr(adapter, '_execute', fail)
        with pytest.raises(photo.PhotoCleanupError):
            await adapter.observe_round('first', 1, {'place_journeys': [place()]})
        assert adapter.receipts()[-1]['reason'] == 'photo_cleanup_failed'
        assert not adapter.session._pending and adapter.session.run.started == 0
        await adapter.close()
    asyncio.run(scenario())


def test_public_http_cap_is_atomic_durable_and_cannot_be_refunded(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    path = tmp_path / 'public-http.jsonl'
    budget = photo.PublicHttpBudget(path)
    def reserve(_):
        try:
            budget.reserve('GET', 'commons.wikimedia.org')
            return True
        except ValueError:
            return False
    try:
        with ThreadPoolExecutor(max_workers=16) as pool:
            results = list(pool.map(reserve, range(140)))
        assert sum(results) == 128 and budget.reserved == 128 and budget.exhausted
        assert photo._read_http_reservations(path) == 128
    finally:
        budget.close()
    with pytest.raises(FileExistsError):
        photo.PublicHttpBudget(path)


@pytest.mark.parametrize('method,host,body,headers', [
    ('POST', 'commons.wikimedia.org', None, {}),
    ('GET', '127.0.0.1', None, {}),
    ('GET', 'example.com', None, {}),
    ('GET', 'www.loc.gov', b'payload', {}),
    ('GET', 'www.loc.gov', None, {'Authorization': 'secret'}),
])
def test_unapproved_public_http_requests_are_rejected_before_reservation(tmp_path, method, host, body, headers):
    budget = photo.PublicHttpBudget(tmp_path / 'journal')
    try:
        with pytest.raises(ValueError): budget.reserve(method, host, body, headers)
        assert budget.reserved == 0
    finally:
        budget.close()


def test_counted_socket_seam_counts_robots_and_each_redirect_before_send(tmp_path, monkeypatch):
    from io import BytesIO
    from apps.api.place_photo_browser import _research
    from apps.api import place_photos as providers
    helper = _research()
    journal = tmp_path / 'http-reservations.jsonl'
    contacts, syncs = [], []
    real_fsync = photo.os.fsync
    def sync(fd):
        real_fsync(fd); syncs.append(True)
    monkeypatch.setattr(photo.os, 'fsync', sync)
    monkeypatch.setattr(helper, 'public_addresses', lambda host, port: ['93.184.216.34'])
    monkeypatch.setattr(helper.time, 'sleep', lambda delay: None)
    def request(connection, method, path, **kwargs):
        assert len(syncs) > len(contacts), 'Journal must be durable before send'
        contacts.append(path)
    class Response:
        def __init__(self, status, headers=(), body=b''):
            self.status, self.headers, self.body = status, headers, BytesIO(body)
        def getheaders(self): return self.headers
        def read(self, size): return self.body.read(size)
    responses = iter([Response(404), Response(302, [('Location', '/target')]), Response(200, body=b'{}')])
    monkeypatch.setattr(helper.PinnedHTTPS, 'request', request)
    monkeypatch.setattr(helper.PinnedHTTPS, 'getresponse', lambda self: next(responses))
    with photo.counted_public_catalogues(journal) as budget:
        assert providers._get('https://commons.wikimedia.org/start', {}) == {}
        assert budget.reserved == 3
        for key in ('_google_browser', '_flickr_browser', '_google_cse', '_flickr', '_llm_web_search'):
            with pytest.raises(providers.PhotoResearchUnavailable): getattr(providers, key)('Hobart', '')
        assert budget.reserved == 3
    assert len(contacts) == 3 and contacts[0] == '/robots.txt'
    assert photo._read_http_reservations(journal) == 3


def test_journal_failure_stops_http_before_contact_and_remains_closed(tmp_path, monkeypatch):
    from apps.api.place_photo_browser import _research
    helper = _research()
    contacts = []
    monkeypatch.setattr(helper.PinnedHTTPS, 'request', lambda *a, **kw: contacts.append(True))
    monkeypatch.setattr(photo.os, 'fsync', lambda fd: (_ for _ in ()).throw(OSError('Controlled journal failure')))
    with photo.counted_public_catalogues(tmp_path / 'journal') as budget:
        connection = helper.PinnedHTTPS('commons.wikimedia.org', '93.184.216.34', 443, 1)
        with pytest.raises(OSError): connection.request('GET', '/')
        with pytest.raises(ValueError): connection.request('GET', '/')
        assert budget.failed and not contacts


def test_corrupt_partial_public_http_journal_is_not_accepted(tmp_path):
    journal = tmp_path / 'journal'
    journal.write_bytes(b'{"ordinal":1,"method":"GET"}\n{"ordinal":2')
    with pytest.raises(photo.PhotoCleanupError): photo._read_http_reservations(journal)


@pytest.mark.parametrize('cancelled', [False, True])
def test_failed_or_cancelled_process_keeps_pre_send_reservations(tmp_path, monkeypatch, cancelled):
    async def scenario():
        adapter = await _test_adapter(tmp_path, monkeypatch)
        adapter._counts['first'] = 1
        adapter._http_cases[1] = 'first'
        async def interrupted(command, *, timeout, cwd, env, **kwargs):
            budget = photo.PublicHttpBudget(cwd / 'http-reservations.jsonl')
            budget.reserve('GET', 'commons.wikimedia.org'); budget.reserve('GET', 'www.loc.gov')
            budget.close()
            if cancelled: raise asyncio.CancelledError()
            raise ValueError('Controlled worker failure')
        monkeypatch.setattr(adapter, '_process', interrupted)
        with pytest.raises(asyncio.CancelledError if cancelled else ValueError):
            await adapter._execute({'owner': 'project', 'place': 'Hobart', 'period': ''}, 1)
        saved = adapter.snapshot()
        assert saved['public_http_requests_reserved'] == 2
        assert saved['case_public_http_requests_reserved']['first'] == 2
        assert saved['public_http_requests_completed'] is None
        assert saved['public_http_upstream_cancellation_verified'] is False
        await adapter.close()
    asyncio.run(scenario())


def test_missing_process_journal_is_unknown_never_zero(tmp_path, monkeypatch):
    async def scenario():
        adapter = await _test_adapter(tmp_path, monkeypatch)
        adapter._counts['first'] = 1
        adapter._http_cases[1] = 'first'
        async def failed(*args, **kwargs): raise ValueError('Controlled launch failure')
        monkeypatch.setattr(adapter, '_process', failed)
        with pytest.raises(photo.PhotoCleanupError):
            await adapter._execute({'owner': 'project', 'place': 'Hobart', 'period': ''}, 1)
        saved = adapter.snapshot()
        assert saved['public_http_accounting'] == 'unavailable'
        assert saved['public_http_requests_reserved'] is None
        assert saved['case_public_http_requests_reserved']['first'] is None
        await adapter.close()
    asyncio.run(scenario())


def test_unapproved_or_exhausted_hosts_are_rejected_before_dns(tmp_path, monkeypatch):
    from apps.api.place_photo_browser import _research
    helper = _research()
    contacts = []
    monkeypatch.setattr(helper, 'public_addresses', lambda *args: contacts.append(args))
    with photo.counted_public_catalogues(tmp_path / 'journal') as budget:
        with pytest.raises(ValueError): helper.public_addresses('not-approved.example', 443)
        for _ in range(128): budget.reserve('GET', 'www.loc.gov')
        with pytest.raises(ValueError): helper.public_addresses('www.loc.gov', 443)
    assert not contacts
