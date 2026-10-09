"""Offline contracts only: no Node, Chromium, HTTP server or provider execution."""
import asyncio
from copy import deepcopy
import hashlib
import json
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
    (web / 'package.json').write_text('{"scripts":{"dev":"next dev"}}')
    (web / 'next.config.mjs').write_text('const apiOrigin = process.env.MEMORY_SPARK_API_ORIGIN;')
    (web / 'app').mkdir()
    (web / 'app/page.jsx').write_text('export default function Page() { return null; }')
    deps = tmp_path / 'installed/node_modules'
    deps.mkdir(parents=True)
    paths = {}
    for key in ('node_executable', 'python_executable', 'chromium_executable', 'playwright_module', 'next_cli', 'next_cli_docs'):
        path = deps / key
        path.write_text('next dev --hostname --port --webpack' if key == 'next_cli_docs' else key)
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
