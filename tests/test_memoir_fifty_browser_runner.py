"""Offline contracts, including pure Node policy checks; no browser/server/provider."""
import asyncio
from copy import deepcopy
import hashlib
import json
import shutil
import subprocess
import zlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import memoir_fifty_browser_runner as runner


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def config(tmp_path, monkeypatch):
    root = tmp_path / 'repo'
    web = root / 'apps/web'
    web.mkdir(parents=True)
    (web / 'package.json').write_text('{"scripts":{"dev":"next dev","build":"next build","start":"next start"}}')
    (web / 'next.config.mjs').write_text('const apiOrigin = process.env.MEMORY_SPARK_API_ORIGIN;')
    (web / 'app').mkdir()
    (web / 'app/page.jsx').write_text('export default function Page() { return null; }')
    deps = tmp_path / 'installed/node_modules'
    deps.mkdir(parents=True)
    paths = {}
    for key in ('node_executable', 'python_executable', 'chromium_executable', 'playwright_module', 'next_cli', 'next_cli_docs'):
        path = deps / key
        path.write_text('next build --webpack; next start --hostname --port' if key == 'next_cli_docs' else key)
        path.chmod(0o700)
        paths[key] = str(path)
    monkeypatch.setattr(runner, '_tracked_frontend', lambda path: tuple(sorted('apps/web/' + str(p.relative_to(web)) for p in web.rglob('*') if p.is_file())))
    return {'schema_version': runner.CONFIG_SCHEMA, 'source_revision': 'a' * 40,
        'source_root': str(root), 'output_root': str(tmp_path / 'private-output'),
        'node_modules': str(deps), **paths,
        'binary_sha256': {path: sha(Path(path)) for path in paths.values()},
        'frontend_sha256': {name: sha(root / name) for name in runner._tracked_frontend(root)},
        'max_requests': 256, 'public_asset_urls': list(runner.PUBLIC_ASSETS)}


def validate(config):
    return runner.validate_browser_config(config, source_revision='a' * 40, source_root=Path(config['source_root']))


def test_validate_is_offline_detached_and_does_not_copy_or_spawn(config, monkeypatch):
    monkeypatch.setattr(runner.asyncio, 'create_subprocess_exec', lambda *a, **kw: pytest.fail('No execution at admission'))
    result = validate(config)
    assert result == config and result is not config
    result['frontend_sha256'].clear()
    assert config['frontend_sha256']
    assert not Path(config['output_root']).exists()


@pytest.mark.parametrize('mutation', [
    lambda c: c.update(source_revision='b' * 40),
    lambda c: c['frontend_sha256'].pop('apps/web/app/page.jsx'),
    lambda c: c['frontend_sha256'].update({'apps/web/extra.jsx': '1' * 64}),
    lambda c: c.update(max_requests=True),
    lambda c: c.update(max_requests=513),
    lambda c: c.update(public_asset_urls=['https://example.com/anything.js']),
    lambda c: c.update(access_token='secret'),
    lambda c: c['binary_sha256'].update({'/unrequested': '1' * 64}),
])
def test_invalid_or_incomplete_admission_fails_closed(config, mutation):
    mutation(config)
    with pytest.raises(ValueError): validate(config)


def test_source_and_runtime_drift_or_symlink_fails_closed(config):
    path = Path(config['source_root']) / 'apps/web/app/page.jsx'
    path.write_text('modified')
    with pytest.raises(ValueError, match='hash'): validate(config)
    config['frontend_sha256']['apps/web/app/page.jsx'] = sha(path)
    target = path.with_name('target')
    path.rename(target)
    path.symlink_to(target)
    with pytest.raises(ValueError): validate(config)


def test_private_copy_contains_only_pinned_source_and_existing_dependencies(config):
    plan = validate(config)
    (Path(config['source_root']) / 'apps/web/.env.local').write_text('SECRET=do-not-copy')
    copied = runner._copy_frontend(plan)
    assert copied != Path(config['source_root']) / 'apps/web'
    assert (copied / 'app/page.jsx').read_text().startswith('export default')
    assert not (copied / '.env.local').exists()
    assert (copied / 'node_modules').resolve() == Path(config['node_modules'])
    assert not (Path(config['source_root']) / 'apps/web/.next').exists()
    assert Path(config['output_root']).stat().st_mode & 0o777 == 0o700
    with pytest.raises(FileExistsError): runner._copy_frontend(plan)


def test_minimal_child_environment_never_inherits_credentials(config, monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'private')
    monkeypatch.setenv('NODE_OPTIONS', '--require /evil.js')
    monkeypatch.setenv('HTTPS_PROXY', 'https://credential@proxy')
    env = runner._child_environment(Path(config['output_root']))
    assert all(k not in env for k in ('OPENAI_API_KEY', 'NODE_OPTIONS', 'HTTPS_PROXY', 'HOME'))
    assert env['NEXT_TELEMETRY_DISABLED'] == '1'
    assert env['PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD'] == '1'


@pytest.mark.parametrize('method,url,allowed,auth', [
    ('GET', 'http://127.0.0.1:31234/api/v1/memoir/agent/config', True, True),
    ('GET', 'http://127.0.0.1:31234/api/v1/memoir/story/private-draft?project_id=123', False, False),
    ('GET', 'http://127.0.0.1:31234/api/v1/memoir/agent/places/photo', False, False),
    ('GET', 'http://127.0.0.1:31234/api/v1/memoir/agent/places/resolve', False, False),
    ('POST', 'http://127.0.0.1:31234/api/v1/memoir/agent/greeting', False, False),
    ('PATCH', 'http://127.0.0.1:31234/api/v1/memoir/agent/profile', False, False),
    ('GET', 'http://127.0.0.1:31235/api/v1/memoir/agent/profile', False, False),
    ('GET', 'http://localhost:31234/api/v1/memoir/agent/profile', False, False),
    ('GET', 'http://user@127.0.0.1:31234/api/v1/memoir/agent/profile', False, False),
    ('GET', 'http://127.0.0.1:31234/_next/static/chunk.js', True, False),
    ('GET', 'http://127.0.0.1:31234/_next/image?url=https://evil.test', False, False),
    ('GET', 'https://unpkg.com/d3@7.9.0/dist/d3.min.js', True, False),
    ('GET', 'https://unpkg.com/d3@7.9.0/dist/d3.min.js?callback=evil', False, False),
    ('GET', 'https://evil.test/leak', False, False),
])
def test_strict_readonly_network_scope(method, url, allowed, auth):
    decision = runner.request_policy(method, url, frontend_origin='http://127.0.0.1:31234',
        project_id='00000000-0000-0000-0000-000000000001', public_asset_urls=runner.PUBLIC_ASSETS)
    assert decision == {'allowed': allowed, 'synthetic_auth': auth}


_STATIC_PATH_CASES = [
    ('/_next/static/chunks/app/%5B%5B...path%5D%5D/page.js', True),
    ('/_next/static/chunks/main-app.js', True),
    ('/_next/static/%2e%2e/secrets', False),
    ('/_next/static/%2fapi/v1/memoir/agent/turn', False),
    ('/_next/static/%5csecrets', False),
    ('/_next/static/%252e%252e/secrets', False),
    ('/_next/static/../../secrets', False),
    ('/_next/static/chunks/app/[[...path]]/page.js', True),
    ('/_next/static/chunks/app/%5b%5b...path%5d%5d/page.js', True),
    ('/_next/static/chunks/app/%5Bid%5D/page.js', True),
    ('/_next/static/chunks/app/%5B...path%5D/page.js', True),
    ('/_next/static/chunks/app/%255B%255B...path%255D%255D/page.js', False),
    ('/_next/static/chunks/app/%5B%5B%2e%2e%2epath%5D%5D/page.js', False),
    ('/_next/static/chunks/app/%5B%5B...path%5D%5D/%2fpage.js', False),
    ('/_next/static/chunks/app/%5B%5B...path%5D%5D/../main-app.js', False),
    ('/_next/static/chunks/app/%5B%5B...path%5D%5D/%2e%2e/main-app.js', False),
    ('/_next/static/chunks/app/%5B%5B...path%5D%5D/%252fpage.js', False),
    ('/_next/static/chunks/app/%5B%5B...path%5D/page.js', False),
    ('/_next/static/chunks/app/%5B%5B...%5D%5D/page.js', False),
    ('/_next/static/chunks/app/%5B%5B...a/b%5D%5D/page.js', False),
    ('/_next/static/chunks/app/%5B%5B...path%5D%5D/%GG', False),
    ('/_next/static/chunks/app/%5B%5B...path%5D%5Dextra/page.js', False),
    ('/_next/static/chunks/app/%5B%5B...path%5D%5D/%00page.js', False),
    ('/_next/static/chunks/app/%5B%5B...path%5D%5D/%3Fpage.js', False),
    ('/_next/static/chunks/app/%5B%5B...path%5D%5D/%23page.js', False),
    ('/_next/static/chunks/app/a..b/page.js', False),
    ('/_next/static/chunks/./main-app.js', False),
    ('/_next/static/chunks/%2e/main-app.js', False),
    ('/_next/static/chunks/../main-app.js', False),
    ('/_next/static/chunks/.\n./main-app.js', False),
    ('/_next/static/chunks/.\r./main-app.js', False),
    ('/_next/static/chunks/.\t./main-app.js', False),
    ('/_next/static/chunks/app/%5B%5B...path%5D%5D/.\n./page.js', False),
    ('/_next/static/chunks/main-app.js ', False),
    ('/_next/static/chunks/main\x00-app.js', False),
    ('/_next/static/chunks/main\x7f-app.js', False),
    ('/_next/static/chunks\\main-app.js', False),
    ('/static/%5B%5B...path%5D%5D/page.js', False),
    ('/api/v1/memoir/%5B%5B...path%5D%5D', False),
    ('/_next/static/chunks/app/%5B%5B...path%5D%5D/page.js#fragment', False),
]


@pytest.mark.parametrize('path,allowed', _STATIC_PATH_CASES)
def test_next_static_route_brackets_without_traversal(path, allowed):
    origin = 'http://127.0.0.1:31234'
    assert runner.request_policy('GET', origin + path, frontend_origin=origin,
        project_id='00000000-0000-0000-0000-000000000001') == {
            'allowed': allowed, 'synthetic_auth': False}


@pytest.mark.parametrize('method', ['HEAD', 'POST', 'PUT', 'PATCH', 'DELETE'])
def test_next_static_bracket_exception_remains_read_only(method):
    origin = 'http://127.0.0.1:31234'
    path = '/_next/static/chunks/app/%5B%5B...path%5D%5D/page.js'
    assert runner.request_policy(method, origin + path, frontend_origin=origin,
        project_id='00000000-0000-0000-0000-000000000001') == {
            'allowed': method == 'HEAD', 'synthetic_auth': False}


@pytest.mark.skipif(shutil.which('node') is None, reason='Pure embedded-JavaScript policy regression requires existing Node')
def test_actual_embedded_javascript_static_policy_matches_python():
    # Execute the exact embedded decision, not a rewritten JavaScript fixture.
    # No Playwright import, browser, filesystem read, network or provider call.
    origin = 'http://127.0.0.1:31234'
    cases = [('GET', origin + path, allowed) for path, allowed in _STATIC_PATH_CASES]
    cases += [
        ('GET', 'http://127.0.0.1:31235/_next/static/chunks/app/%5B%5B...path%5D%5D/page.js', False),
        ('GET', 'https://evil.test/_next/static/chunks/app/%5B%5B...path%5D%5D/page.js', False),
    ]
    cases += [(method, origin + _STATIC_PATH_CASES[0][0], method == 'HEAD')
        for method in ('HEAD', 'POST', 'PUT', 'PATCH', 'DELETE')]
    config = {'frontend_origin': origin, 'public_asset_urls': [], 'api_paths': [],
        'max_requests': len(cases), 'interview_path': '/memoir/interview/project'}
    script = 'const c = ' + json.dumps(config) + '; const report = {}; let attempts = 0, sent = false;\n'
    script += 'const allowedAssets =' + runner.BROWSER_SCRIPT.split(
        'const allowedAssets =', 1)[1].split('async function quiet', 1)[0]
    script += ('\nprocess.stdout.write(JSON.stringify(' + json.dumps([(method, url) for method, url, _ in cases]) +
        '.map(([method,url]) => decision({url:()=>url, method:()=>method}))));')
    result = subprocess.run([shutil.which('node'), '-e', script], check=True,
        capture_output=True, text=True, timeout=10)
    decisions = json.loads(result.stdout)
    assert [(row['ok'], row.get('api', False)) for row in decisions] == [
        (allowed, False) for _, _, allowed in cases]


def test_source_worker_never_replays_facts_or_launches_unowned_browsers():
    script = runner.BROWSER_SCRIPT
    assert '.fulfill(' not in script and '.launch(' not in script and '.launchServer(' not in script
    assert 'connectOverCDP' in script and 'newContext' in script
    assert 'extraHTTPHeaders' not in script and 'route.continue' in script
    assert 'serviceWorkers: "block"' in script and 'routeWebSocket' in script
    assert 'memoir_five_case_expected' not in script and 'memoir_five_case_truth' not in script
    assert 'setContent' not in script and 'localStorage.setItem' not in script
    assert 'page.screenshot' in script and 'pageerror' in script
    assert all(stage in script for stage in runner.LIFE_STAGES)


def test_png_receipt_requires_actual_file_and_hash(tmp_path):
    path = tmp_path / 'view.png'
    path.write_bytes(b'not-a-png')
    with pytest.raises(ValueError, match='PNG'): runner._png_receipt(path, tmp_path)
    def chunk(kind, data):
        return len(data).to_bytes(4, 'big') + kind + data + zlib.crc32(kind + data).to_bytes(4, 'big')
    path.write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', (1).to_bytes(4, 'big') * 2 + b'\x08\x02\x00\x00\x00')
        + chunk(b'IDAT', zlib.compress(b'\0\xff\0\0')) + chunk(b'IEND', b''))
    receipt = runner._png_receipt(path, tmp_path)
    assert receipt['sha256'] == sha(path) and receipt['width'] == receipt['height'] == 1
    assert receipt['path'] == 'view.png'


def test_case_must_still_own_original_deadline_before_any_native_work(monkeypatch):
    instance = object.__new__(runner.OwnedFiftyBrowserReadback)
    instance._closed = False
    instance._session = SimpleNamespace(run=SimpleNamespace(_active_case=None, remaining_seconds=lambda: 30))
    instance._plans = {'case': {}}
    monkeypatch.setattr(runner, '_assert_session', lambda s: None)
    with pytest.raises(ValueError, match='active case'): instance._remaining('case')


def test_redirects_and_unapproved_browser_targets_fail_closed_before_follow():
    script = runner.BROWSER_SCRIPT
    assert 'requestStage:"Response"' in script
    assert 'Fetch.failRequest' in script
    assert '[301,302,303,307,308].includes' in script
    assert 'request.frame() === page.mainFrame()' in script
    assert 'extra !== page' in script and 'download.cancel()' in script
    assert script.index('await cdp.send("Fetch.enable"') < script.index('await page.goto(')
    assert 'api_responses_are_owned' in script and 'terminal_network_scope_valid' in script


def test_real_product_wrapper_is_forwarded_without_rewriting():
    script = runner.BROWSER_SCRIPT
    assert 'c.turn.allowed_texts.includes(body.text)' in script
    assert 'body.conversation_text !== c.turn.text' in script
    assert 'provider_input_sha256:sha(body.text)' in script
    assert 'postData:' not in script
    assert 'body.first_reply_localization && c.turn.ordinal !== 1' in script


def test_owned_process_is_new_group_and_no_inherited_environment(monkeypatch, tmp_path):
    calls = []
    process = SimpleNamespace(pid=1234, returncode=None)
    async def spawn(*args, **kwargs):
        calls.append((args, kwargs))
        return process
    monkeypatch.setattr(runner.asyncio, 'create_subprocess_exec', spawn)
    instance = object.__new__(runner.OwnedFiftyBrowserReadback)
    instance._processes = []
    result = asyncio.run(instance._spawn(['/pinned/node', 'reviewed.js'], cwd=tmp_path,
        env=runner._child_environment(tmp_path), kind='browser_worker'))
    assert result is process and instance._processes == [('browser_worker', process)]
    assert calls[0][1]['start_new_session'] is True
    assert calls[0][1]['stdin'] == asyncio.subprocess.DEVNULL
    assert 'HOME' not in calls[0][1]['env']


def test_cleanup_kills_original_group_and_joins_even_if_leader_already_exited(monkeypatch):
    signals, waits = [], []
    async def wait():
        waits.append(True)
        return 0
    process = SimpleNamespace(pid=4321, returncode=0, wait=wait)
    instance = object.__new__(runner.OwnedFiftyBrowserReadback)
    instance._processes = [('frontend', process)]
    instance._cleanup = []
    monkeypatch.setattr(runner, '_TERM_GRACE_SECONDS', 0)
    def killpg(pid, sig):
        if sig == 0:
            if any(s == runner.signal.SIGKILL for _, s in signals): raise ProcessLookupError
            return
        signals.append((pid, sig))
    monkeypatch.setattr(runner.os, 'killpg', killpg)
    asyncio.run(instance._stop('frontend', process))
    assert signals == [(4321, runner.signal.SIGTERM), (4321, runner.signal.SIGKILL)]
    assert waits and instance._processes == []
    assert instance._cleanup[0]['joined'] is True
    assert instance._cleanup[0]['group_gone'] is True


def test_cleanup_attempts_every_owned_group_when_one_fails():
    instance = object.__new__(runner.OwnedFiftyBrowserReadback)
    instance._processes = [('frontend', 1), ('chromium', 2), ('browser_worker', 3)]
    attempted = []
    async def stop(kind, process):
        attempted.append(process)
        if process == 3: raise RuntimeError('join failed')
    instance._stop = stop
    with pytest.raises(RuntimeError, match='join failed'): asyncio.run(instance._close_case())
    assert attempted == [3, 2, 1]


def operation_owner(*, turns=True):
    instance = object.__new__(runner.OwnedFiftyBrowserReadback)
    instance._config = {'allow_browser_turns': turns}
    instance._processes = []
    instance._busy = False
    instance._observed_cases = set()
    instance._turn_ordinals = {}
    instance._observations = []
    instance._check = lambda case: 1
    calls = []
    async def ensure(case): calls.append(('ensure', case))
    async def close(): calls.append(('close',))
    instance._ensure_case = ensure
    instance._close_case = close
    return instance, calls


def test_readonly_mode_never_arms_turn_or_allocates_native_resources():
    instance, calls = operation_owner(turns=False)
    assert instance.turns_enabled is False
    with pytest.raises(ValueError, match='separate admission'):
        asyncio.run(instance.turn('case', 1, 'original'))
    assert calls == []


def test_browser_turn_uses_one_original_form_and_retains_actual_runtime_result():
    instance, calls = operation_owner()
    result = {'reply': 'Actual runtime reply', 'accepted_source_id': 'actual-source'}
    def arm(case, ordinal):
        calls.append(('arm', case, ordinal))
        return {'text': 'Original source', 'allowed_texts': ('Original source', 'Real frontend wrapper')}
    async def wait(case, ordinal):
        calls.append(('wait', case, ordinal))
        return result
    async def operation(case, *, turn):
        calls.append(('operation', case, deepcopy(turn)))
        return {'status': 'observed', 'checks': {'ui_form_submitted_once': True,
            'ui_original_text_visible': True, 'ui_new_reply_visible': True},
            'views': [{'dom': {'assistants': ['Actual runtime reply']}}]}
    instance._api = SimpleNamespace(arm_turn=arm, wait_turn=wait)
    instance._operation = operation
    actual = asyncio.run(instance.turn('case', 1, 'Original source'))
    assert actual is result
    assert calls == [('ensure', 'case'), ('arm', 'case', 1), ('operation', 'case', {
        'ordinal': 1, 'text': 'Original source', 'allowed_texts': ('Original source', 'Real frontend wrapper')}), ('wait', 'case', 1)]
    assert instance._turn_ordinals == {'case': 1}
    with pytest.raises(ValueError, match='sequential'):
        asyncio.run(instance.turn('case', 1, 'Original source'))


def test_missing_ui_submission_cannot_be_upgraded_by_runtime_receipt():
    instance, calls = operation_owner()
    instance._api = SimpleNamespace(arm_turn=lambda *a: {'text': 'Original', 'allowed_texts': ['Original']},
        wait_turn=lambda *a: pytest.fail('No hidden fallback to retained runtime'))
    async def operation(*args, **kwargs): return {'status': 'incomplete', 'checks': {}}
    instance._operation = operation
    with pytest.raises(ValueError, match='not observed'):
        asyncio.run(instance.turn('case', 1, 'Original'))
    assert ('close',) in calls
    assert instance._observations[-1]['status'] == 'incomplete'
    assert instance._turn_ordinals == {}


def test_observation_timeout_preserves_incomplete_receipt_and_closes_owned_processes():
    instance, calls = operation_owner()
    instance._check = lambda case: .01
    async def operation(*args, **kwargs): await asyncio.sleep(1)
    instance._operation = operation
    with pytest.raises(TimeoutError): asyncio.run(instance.observe_case('case'))
    assert calls == [('close',)]
    assert instance._observations[-1]['failure_type'] == 'TimeoutError'
    assert instance._observations[-1]['screenshots_verified'] is False
    with pytest.raises(ValueError, match='repeat'): asyncio.run(instance.observe_case('case'))


def test_close_always_closes_api_despite_group_cleanup_failure():
    instance, calls = operation_owner()
    instance._closed = False
    async def close_case():
        calls.append(('groups',))
        raise RuntimeError('group failure')
    async def close_api(): calls.append(('api',))
    instance._close_case = close_case
    instance._api = SimpleNamespace(close=close_api)
    with pytest.raises(RuntimeError, match='group failure'): asyncio.run(instance.close())
    assert calls == [('groups',), ('api',)]
    assert instance._closed is True


def test_admission_fixes_source_root_instead_of_trusting_config_path(config, monkeypatch):
    monkeypatch.setattr(runner, '_assert_session', lambda value: None)
    session = SimpleNamespace(run=SimpleNamespace(source_revision='a' * 40))
    with pytest.raises(ValueError, match='source root'):
        runner.OwnedFiftyBrowserReadback.admit(session, config)


def test_parent_exit_with_surviving_descendant_is_fatal_and_stays_pending(monkeypatch):
    signals = []
    async def wait(): return 0
    process = SimpleNamespace(pid=5432, returncode=0, wait=wait)
    instance = object.__new__(runner.OwnedFiftyBrowserReadback)
    instance._processes = [('chromium', process)]
    instance._cleanup = []
    monkeypatch.setattr(runner, '_TERM_GRACE_SECONDS', 0)
    monkeypatch.setattr(runner, '_KILL_GRACE_SECONDS', 0)
    monkeypatch.setattr(runner.os, 'killpg', lambda pid, sig: signals.append((pid, sig)))
    with pytest.raises(RuntimeError, match='group remains'):
        asyncio.run(instance._stop('chromium', process))
    assert (5432, runner.signal.SIGKILL) in signals
    assert instance._processes == [('chromium', process)]
    assert instance._cleanup[-1]['group_gone'] is False
    assert instance._cleanup[-1]['failure_type'] == 'RuntimeError'


def test_repeated_cancellation_does_not_cancel_the_cleanup_join():
    async def exercise():
        instance = object.__new__(runner.OwnedFiftyBrowserReadback)
        started, finish = asyncio.Event(), asyncio.Event()
        joined = []
        async def cleanup():
            started.set()
            await finish.wait()
            joined.append(True)
        work = asyncio.create_task(cleanup())
        waiter = asyncio.create_task(instance._join_cleanup(work))
        await started.wait()
        waiter.cancel()
        await asyncio.sleep(0)
        waiter.cancel()
        await asyncio.sleep(0)
        assert not work.cancelled() and not waiter.done()
        finish.set()
        with pytest.raises(asyncio.CancelledError): await waiter
        assert joined == [True] and work.done() and not work.cancelled()
    asyncio.run(exercise())


def test_actual_reply_must_match_rendered_dom_not_just_successful_post():
    instance, calls = operation_owner()
    instance._api = SimpleNamespace(arm_turn=lambda *a: {'text': 'Original', 'allowed_texts': ['Original']})
    async def wait(*args): return {'reply': 'Actual runtime reply'}
    instance._api.wait_turn = wait
    async def operation(*args, **kwargs):
        return {'status': 'observed', 'checks': {'ui_form_submitted_once': True,
            'ui_original_text_visible': True, 'ui_new_reply_visible': True},
            'views': [{'dom': {'assistants': ['An unrelated fallback message']}}]}
    instance._operation = operation
    with pytest.raises(ValueError, match='runtime reply differs'):
        asyncio.run(instance.turn('case', 1, 'Original'))
    assert ('close',) in calls and instance._turn_ordinals == {}


def test_visible_reply_uses_only_actual_product_presentation_filters():
    assert runner._visible_reply('Hello\n [[MEMORY_SPARK_PROFILE]]private-marker[[/MEMORY_SPARK_PROFILE]]  world<!-- profile: {} -->') == 'Hello world'
    assert runner._visible_reply('Visible [words] stay.') == 'Visible [words] stay.'


def test_cancelled_allocation_keeps_owned_child_handle_for_finally_cleanup(monkeypatch, tmp_path):
    async def exercise():
        started, finish = asyncio.Event(), asyncio.Event()
        process = SimpleNamespace(pid=6543)
        async def spawn(*args, **kwargs):
            started.set()
            await finish.wait()
            return process
        monkeypatch.setattr(runner.asyncio, 'create_subprocess_exec', spawn)
        instance = object.__new__(runner.OwnedFiftyBrowserReadback)
        instance._processes = []
        pending = asyncio.create_task(instance._spawn(['/pinned/node'], cwd=tmp_path, env={}, kind='frontend'))
        await started.wait()
        pending.cancel()
        await asyncio.sleep(0)
        assert not pending.done()
        finish.set()
        with pytest.raises(asyncio.CancelledError): await pending
        assert instance._processes == [('frontend', process)]
    asyncio.run(exercise())


def test_api_provenance_check_uses_exact_admitted_mode_and_requires_observed_response():
    assert 'n.fixture === c.expected_api_fixture' in runner.BROWSER_SCRIPT
    assert 'ownedResponses.length > 0' in runner.BROWSER_SCRIPT
    import inspect
    operation = inspect.getsource(runner.OwnedFiftyBrowserReadback._operation)
    assert "'owned-fifty-armed-api' if self.turns_enabled else 'owned-fifty-readback-only'" in operation


def production_routes(api_origin):
    return {'version': 3, 'rewrites': {'beforeFiles': [], 'afterFiles': [
        {'source': '/api/v1/memoir/:path*', 'destination': api_origin + '/api/v1/memoir/:path*', 'regex': '^/api/v1/memoir'},
        {'source': '/api/v1/memoir', 'destination': api_origin + '/api/v1/memoir', 'regex': '^/api/v1/memoir$'},
        {'source': '/static/:path*', 'destination': '/:path*', 'regex': '^/static'}], 'fallback': []}}


def write_routes(web, origin):
    target = web / '.next/routes-manifest.json'
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps(production_routes(origin)))
    return target


def test_each_case_gets_clean_verified_frontend_without_prior_build_rewrites(config):
    template = runner._copy_frontend(validate(config))
    write_routes(template, 'http://127.0.0.1:31234/cases/previous-case')
    (template / '.env.local').write_text('SHOULD_NOT_COPY=1')
    first = Path(config['output_root']) / 'first-case'
    second = Path(config['output_root']) / 'second-case'
    first.mkdir(); second.mkdir()
    first_web = runner._copy_case_frontend(config, template, first)
    second_web = runner._copy_case_frontend(config, template, second)
    assert first_web != second_web and first_web != template
    assert first_web == first / 'frontend' and second_web == second / 'frontend'
    for web in (first_web, second_web):
        assert not (web / '.next').exists() and not (web / '.env.local').exists()
        assert (web / 'node_modules').resolve() == Path(config['node_modules'])
        assert (web / 'app/page.jsx').read_bytes() == (template / 'app/page.jsx').read_bytes()
    with pytest.raises(FileExistsError): runner._copy_case_frontend(config, template, first)


def test_generated_manifest_requires_exact_case_specific_api_rewrites(tmp_path):
    origin = 'http://127.0.0.1:31234/cases/first-case'
    path = write_routes(tmp_path, origin)
    result = runner._verify_routes_manifest(tmp_path, origin)
    assert result['sha256'] == sha(path) and result['api_origin'] == origin
    assert result['api_rewrites_verified'] is True
    with pytest.raises(ValueError, match='rewrites'):
        runner._verify_routes_manifest(tmp_path, 'http://127.0.0.1:31234/cases/second-case')


@pytest.mark.parametrize('mutation', [
    lambda value: value['rewrites']['afterFiles'][0].update(destination='http://127.0.0.1:8000/api/v1/memoir/:path*'),
    lambda value: value['rewrites']['afterFiles'][1].update(destination='https://unapproved.test/api/v1/memoir'),
    lambda value: value['rewrites']['beforeFiles'].append({'source': '/:path*', 'destination': 'https://unapproved.test/:path*'}),
    lambda value: value['rewrites']['afterFiles'].append({'source': '/api/other', 'destination': 'http://127.0.0.1:8000'}),
    lambda value: value['rewrites']['afterFiles'].pop(),
    lambda value: value['rewrites']['afterFiles'][0].update(has=[{'type': 'header', 'key': 'authorization'}]),
])
def test_stale_extra_or_conditionally_different_rewrites_fail_before_start(tmp_path, mutation):
    origin = 'http://127.0.0.1:31234/cases/first-case'
    path = write_routes(tmp_path, origin)
    value = json.loads(path.read_text()); mutation(value); path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match='rewrites'):
        runner._verify_routes_manifest(tmp_path, origin)


def build_owner(config, tmp_path, *, exit_code=0, wait_gate=None):
    instance = object.__new__(runner.OwnedFiftyBrowserReadback)
    instance._config = config
    instance._frontend_builds = []
    instance._check = instance._remaining = lambda case: 30
    calls = []
    async def wait():
        calls.append(('wait',))
        if wait_gate is not None: await wait_gate.wait()
        return exit_code
    process = SimpleNamespace(pid=4567, returncode=exit_code, wait=wait)
    async def spawn(command, **kwargs):
        calls.append(('spawn', command, kwargs))
        return process
    async def stop(kind, child):
        calls.append(('stop', kind, child.pid))
    instance._spawn, instance._stop = spawn, stop
    return instance, calls


def test_owned_build_completes_and_joins_before_start_can_run(config, tmp_path):
    origin = 'http://127.0.0.1:31234/cases/first-case'
    web = tmp_path / 'frontend'
    write_routes(web, origin)
    instance, calls = build_owner(config, tmp_path)
    env = runner._child_environment(tmp_path)
    env.update(NODE_ENV='production', MEMORY_SPARK_API_ORIGIN=origin)
    result = asyncio.run(instance._build_frontend('first-case', web, env))
    assert calls[0] == ('spawn', [config['node_executable'], config['next_cli'], 'build', '--webpack'],
        {'cwd': web, 'env': env, 'kind': 'frontend_build'})
    assert calls[-1] == ('stop', 'frontend_build', 4567)
    assert result['status'] == 'completed' and result['process_group_joined'] is True
    assert result['routes_manifest']['api_origin'] == origin
    assert instance._frontend_builds == [result]


def test_failed_build_is_joined_and_never_reports_completed(config, tmp_path):
    instance, calls = build_owner(config, tmp_path, exit_code=1)
    with pytest.raises(ValueError, match='production build failed'):
        asyncio.run(instance._build_frontend('first-case', tmp_path,
            {'MEMORY_SPARK_API_ORIGIN': 'http://127.0.0.1:31234/cases/first-case', 'NODE_ENV': 'production'}))
    assert calls[-1] == ('stop', 'frontend_build', 4567)
    assert instance._frontend_builds[0]['status'] == 'incomplete'
    assert instance._frontend_builds[0]['returncode'] == 1


def test_build_expiry_preserves_original_deadline_and_joins(config, tmp_path):
    async def exercise():
        instance, calls = build_owner(config, tmp_path, wait_gate=asyncio.Event())
        instance._remaining = instance._check = lambda case: .01
        with pytest.raises(TimeoutError):
            await instance._build_frontend('first-case', tmp_path,
                {'MEMORY_SPARK_API_ORIGIN': 'http://127.0.0.1:31234/cases/first-case', 'NODE_ENV': 'production'})
        assert calls[-1] == ('stop', 'frontend_build', 4567)
        assert instance._frontend_builds[0]['failure_type'] == 'TimeoutError'
        assert instance._frontend_builds[0]['status'] == 'incomplete'
    asyncio.run(exercise())


def test_build_cleanup_failure_overrides_success(config, tmp_path):
    origin = 'http://127.0.0.1:31234/cases/first-case'
    web = tmp_path / 'frontend'; write_routes(web, origin)
    instance, _ = build_owner(config, tmp_path)
    async def stop(*args): raise RuntimeError('group remains')
    instance._stop = stop
    with pytest.raises(RuntimeError, match='group remains'):
        asyncio.run(instance._build_frontend('first-case', web,
            {'MEMORY_SPARK_API_ORIGIN': origin, 'NODE_ENV': 'production'}))
    assert instance._frontend_builds[0]['status'] == 'incomplete'
    assert instance._frontend_builds[0]['process_group_joined'] is False


def test_launch_source_uses_production_build_start_instead_of_dev():
    import inspect
    source = inspect.getsource(runner.OwnedFiftyBrowserReadback._ensure_case)
    assert "'dev'" not in source
    assert "'start', '--hostname', '127.0.0.1', '--port'" in source
    assert source.index('await self._build_frontend(') < source.index("kind='frontend')")
    assert '_copy_case_frontend(' in source and "env['NODE_ENV'] = 'production'" in source


def test_two_case_startup_builds_each_origin_after_stopping_previous_frontend(config, monkeypatch):
    """Exercise real orchestration with every process/socket/HTTP boundary mocked."""
    import httpx
    from urllib.parse import urlsplit
    instance = object.__new__(runner.OwnedFiftyBrowserReadback)
    instance._config = config
    instance._session = SimpleNamespace(run=SimpleNamespace(source_revision=config['source_revision']))
    instance._web = instance._template_web = instance._case = instance._frontend = instance._chromium = None
    instance._processes, instance._cleanup, instance._startup_requests, instance._frontend_builds = [], [], [], []
    instance._check = instance._remaining = lambda case: 30
    events = []
    async def start_api(): events.append(('api_start',))
    async def prepare(case): events.append(('prepare', case))
    instance._api = SimpleNamespace(start=start_api, prepare_project=prepare,
        origin_for_case=lambda case: 'http://127.0.0.1:31234/cases/' + case)
    monkeypatch.setattr(runner, 'ROOT', Path(config['source_root']))
    class Socket:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def bind(self, target): assert target == ('127.0.0.1', 0)
        def getsockname(self): return ('127.0.0.1', 41234)
    monkeypatch.setattr(runner, 'socket', SimpleNamespace(AF_INET=runner.socket.AF_INET,
        SOCK_STREAM=runner.socket.SOCK_STREAM, socket=lambda *args: Socket()))
    class Client:
        def __init__(self, **kwargs): assert kwargs == {'trust_env': False, 'follow_redirects': False}
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return False
        async def get(self, url, **kwargs):
            marker = instance._web / 'public' / urlsplit(url).path.removeprefix('/')
            return SimpleNamespace(status_code=200, text=marker.read_text())
    monkeypatch.setattr(httpx, 'AsyncClient', Client)
    async def spawn(command, *, cwd, env, kind):
        events.append(('spawn', kind, str(cwd), env.get('MEMORY_SPARK_API_ORIGIN'), command))
        async def wait(): return 0
        process = SimpleNamespace(pid=1000 + len(events), returncode=None, wait=wait)
        if kind == 'frontend_build':
            assert command[-2:] == ['build', '--webpack'] and env['NODE_ENV'] == 'production'
            write_routes(cwd, env['MEMORY_SPARK_API_ORIGIN'])
        elif kind == 'frontend':
            assert command[2:5] == ['start', '--hostname', '127.0.0.1']
            assert env['NODE_ENV'] == 'production'
            runner._verify_routes_manifest(cwd, env['MEMORY_SPARK_API_ORIGIN'])
        elif kind == 'chromium':
            profile = Path(next(arg.split('=', 1)[1] for arg in command if arg.startswith('--user-data-dir=')))
            (profile / 'DevToolsActivePort').write_text('51234\n/devtools/browser/owned\n')
        instance._processes.append((kind, process))
        return process
    async def stop(kind, process):
        events.append(('stop', kind, process.pid))
        instance._processes = [(name, child) for name, child in instance._processes if child is not process]
    instance._spawn, instance._stop = spawn, stop
    async def exercise():
        await instance._ensure_case('first-case')
        await instance._ensure_case('first-case')  # Same case retains its one completed build.
        await instance._ensure_case('second-case')
        await instance._close_case()
    asyncio.run(exercise())
    builds = [event for event in events if event[:2] == ('spawn', 'frontend_build')]
    assert len(builds) == 2 and builds[0][2] != builds[1][2]
    assert [entry['api_origin'] for entry in instance._frontend_builds] == [
        'http://127.0.0.1:31234/cases/first-case', 'http://127.0.0.1:31234/cases/second-case']
    first_server = next(event for event in events if event[:2] == ('spawn', 'frontend'))
    first_stopped = next(event for event in events if event[:2] == ('stop', 'frontend'))
    assert events.index(first_server) < events.index(first_stopped) < events.index(builds[1])
    assert events.count(('api_start',)) == 1
    assert not instance._processes


def test_build_manifest_is_checked_only_after_last_descendant_is_joined(config, tmp_path):
    origin = 'http://127.0.0.1:31234/cases/first-case'
    web = tmp_path / 'frontend'; write_routes(web, origin)
    instance, calls = build_owner(config, tmp_path)
    async def stop(kind, process):
        calls.append(('stop', kind, process.pid))
        # Model a descendant's final write during shutdown, before join returns.
        path = web / '.next/routes-manifest.json'
        path.write_text(json.dumps(production_routes('http://127.0.0.1:31234/cases/stale-case')))
    instance._stop = stop
    with pytest.raises(ValueError, match='rewrites'):
        asyncio.run(instance._build_frontend('first-case', web,
            {'MEMORY_SPARK_API_ORIGIN': origin, 'NODE_ENV': 'production'}))
    assert calls[-1] == ('stop', 'frontend_build', 4567)
    assert instance._frontend_builds[0]['status'] == 'incomplete'
    assert instance._frontend_builds[0]['process_group_joined'] is True


def test_non_object_routes_manifest_has_clear_failure(tmp_path):
    path = write_routes(tmp_path, 'http://127.0.0.1:31234/cases/first-case')
    path.write_text('[]')
    with pytest.raises(ValueError, match='manifest must be an object'):
        runner._verify_routes_manifest(tmp_path, 'http://127.0.0.1:31234/cases/first-case')


def test_cancelled_build_is_joined_before_cancellation_returns(config, tmp_path):
    async def exercise():
        instance, calls = build_owner(config, tmp_path, wait_gate=asyncio.Event())
        pending = asyncio.create_task(instance._build_frontend('first-case', tmp_path,
            {'MEMORY_SPARK_API_ORIGIN': 'http://127.0.0.1:31234/cases/first-case', 'NODE_ENV': 'production'}))
        while ('wait',) not in calls: await asyncio.sleep(0)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError): await pending
        assert calls[-1] == ('stop', 'frontend_build', 4567)
        assert instance._frontend_builds[0]['failure_type'] == 'CancelledError'
        assert instance._frontend_builds[0]['status'] == 'incomplete'
        assert instance._frontend_builds[0]['process_group_joined'] is True
    asyncio.run(exercise())
