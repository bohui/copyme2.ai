"""Account-only fixtures; network is forbidden throughout this module."""
import io
import json
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from uuid import UUID
import pytest
from scripts import setup_memoir_test_accounts as m

MOCK_PASSWORD = 'offline-test-password'
MOCK_KEY = 'offline-service-key'

def record(index=0, email=None, confirmed=False):
    return {'id': str(UUID(int=index + 1)), 'email': email or m.ACCOUNTS[index],
            'email_confirmed_at': 'already-confirmed' if confirmed else None,
            'is_anonymous': False}


class FakeAuth:
    def __init__(self, users=()):
        self.users = {user['id']: dict(user) for user in users}
        self.calls, self.writes = [], []
        self.passwords = {}
        self.pages = None
        self.fail_email = None
        self.commit_before_failure = False
        self.refuse_confirmation = False

    def request(self, method, path, payload=None):
        self.calls.append((method, path, dict(payload) if payload else None))
        if path.startswith('/admin/users?page='):
            page = int(path.split('page=')[1].split('&')[0])
            if self.pages is not None:
                return {'users': self.pages[page - 1] if page <= len(self.pages) else []}
            return {'users': list(self.users.values()) if page == 1 else []}
        if method == 'GET':
            return dict(self.users[path.rsplit('/', 1)[-1]])
        self.writes.append((method, path, dict(payload)))
        if method == 'POST':
            email = payload['email']; user = record(m.ACCOUNTS.index(email), email)
        else:
            user = dict(self.users[path.rsplit('/', 1)[-1]])
            email = user['email']
        user['email_confirmed_at'] = None if self.refuse_confirmation else 'confirmed'
        if email != self.fail_email or self.commit_before_failure:
            self.users[user['id']] = user
            self.passwords[user['id']] = payload['password']
        if email == self.fail_email:
            raise m.SetupError('Sanitized mocked transport failure.')
        return dict(user)


@pytest.fixture(autouse=True)
def prevent_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Offline test attempted live HTTP.')
    monkeypatch.setattr('urllib.request.OpenerDirector.open', forbidden)


def apply(api):
    operations = m.plan(m.list_accounts(api))
    return m.apply(api, operations)


def test_exact_scope_and_post_truncate_restore():
    api = FakeAuth()
    result = apply(api)
    assert [row['email'] for row in result] == list(m.ACCOUNTS)
    assert all(row['status'] == 'created_confirmed' and row['email_confirmed'] for row in result)
    assert len(api.writes) == 5
    assert all(body == {'email': email, 'password': 'test1234', 'email_confirm': True}
               for (method, path, body), email in zip(api.writes, m.ACCOUNTS))
    assert all(path.startswith('/admin/users') for method, path, payload in api.calls)


def test_rerun_preserves_identities_metadata_and_fixed_credentials():
    users = [record(i, confirmed=True) for i in range(5)]
    for user in users:
        user['app_metadata'] = {'retained': True}
        user['user_metadata'] = {'name': 'Existing test owner'}
    api = FakeAuth(users)
    before = {identifier: {key: value for key, value in user.items() if key != 'email_confirmed_at'}
              for identifier, user in api.users.items()}
    api.passwords = {user['id']: 'old-test-password' for user in users}
    result = apply(api)
    assert len(result) == 5
    assert {identifier: {key: value for key, value in user.items() if key != 'email_confirmed_at'}
            for identifier, user in api.users.items()} == before
    assert all(row['status'] == 'configured_existing' for row in result)
    assert set(api.passwords.values()) == {'test1234'}
    after = dict(api.users), dict(api.passwords)
    apply(api)
    assert (api.users, api.passwords) == after
    assert len(api.users) == 5 and all(method == 'PUT' for method, _, _ in api.writes)


def test_partial_missing_accounts_only_are_created():
    api = FakeAuth([record(0), record(3)])
    result = apply(api)
    creations = [body['email'] for method, path, body in api.writes if method == 'POST']
    assert creations == [m.ACCOUNTS[i] for i in (1, 2, 4)]
    assert result[0]['status'] == result[3]['status'] == 'configured_existing'
    assert all(user['email_confirmed_at'] for user in api.users.values())


def test_complete_pagination_does_not_stop_at_a_short_page():
    api = FakeAuth(); api.pages = [[{'id': str(UUID(int=999)), 'email': 'unrelated@example.invalid'}],
                                  [record(4)], []]
    accounts = m.list_accounts(api)
    assert list(accounts) == [m.ACCOUNTS[4]]
    assert len(api.calls) == 3 and not api.writes


def test_pagination_continues_even_after_all_targets_found():
    api = FakeAuth(); api.pages = [[record(i) for i in range(5)], [record(10, m.ACCOUNTS[0])], []]
    with pytest.raises(m.SetupError, match='Duplicate'):
        m.list_accounts(api)
    assert not api.writes


def test_repeated_page_and_pagination_limit_fail_closed(monkeypatch):
    api = FakeAuth(); api.pages = [[record()], [record()]]
    with pytest.raises(m.SetupError, match='repeated'):
        m.list_accounts(api)
    monkeypatch.setattr(m, 'MAX_PAGES', 1)
    api.pages = [[record()]]
    with pytest.raises(m.SetupError, match='Complete pagination'):
        m.list_accounts(api)


def test_malformed_and_unsafe_selected_identities_are_rejected():
    api = FakeAuth(); api.pages = [[{'id': 'not-a-uuid', 'email': m.ACCOUNTS[0]}]]
    with pytest.raises(m.SetupError, match='identity/state'):
        m.list_accounts(api)
    api.pages = [[{**record(), 'is_anonymous': True}]]
    with pytest.raises(m.SetupError):
        m.list_accounts(api)


def test_concurrent_creation_reuses_the_account_with_fixed_credentials():
    api = FakeAuth(); operations = m.plan({})
    api.users[record()['id']] = record()
    result = m.apply(api, operations)
    assert result[0]['status'] == 'configured_existing'
    assert sum(method == 'POST' for method, _, _ in api.writes) == 4
    assert api.passwords[record()['id']] == 'test1234'


def test_changed_existing_identity_stops_before_writes():
    api = FakeAuth([record()]); operations = m.plan(m.list_accounts(api))
    replacement = record(10, m.ACCOUNTS[0])
    api.users = {replacement['id']: replacement}
    with pytest.raises(m.PartialFailure) as error:
        m.apply(api, operations)
    assert error.value.current['status'] == 'identity_changed_no_write'
    assert not api.writes


@pytest.mark.parametrize('operations', [m.plan({})[:-1], m.plan({}) + [m.plan({})[0]],
    [{'email': 'unrelated@example.invalid', 'action': 'create_confirmed'}]])
def test_incomplete_or_foreign_scope_stops_before_network(operations):
    api = FakeAuth()
    with pytest.raises(m.SetupError):
        m.apply(api, operations)
    assert not api.calls


def test_partial_failure_stops_later_accounts_and_never_retries():
    api = FakeAuth(); api.fail_email = m.ACCOUNTS[2]
    with pytest.raises(m.PartialFailure) as error:
        apply(api)
    assert len(error.value.results) == 2 and error.value.current['email'] == m.ACCOUNTS[2]
    assert len(api.writes) == 3
    assert not error.value.current['account_found_on_recheck']


def test_uncertain_success_reconciles_existence_without_repeating_write():
    api = FakeAuth(); api.fail_email = m.ACCOUNTS[0]; api.commit_before_failure = True
    with pytest.raises(m.PartialFailure) as error:
        apply(api)
    assert len(api.writes) == 1 and error.value.current['account_found_on_recheck']
    assert 'password' not in error.value.current


def test_unconfirmed_readback_stops_without_more_writes():
    api = FakeAuth(); api.refuse_confirmation = True
    with pytest.raises(m.PartialFailure):
        apply(api)
    assert len(api.writes) == 1


def private_env(tmp_path, url=m.ORIGIN):
    path = tmp_path / '.env'
    path.write_text('SUPABASE_URL=' + url + '\nSUPABASE_SECRET_KEY=' + MOCK_KEY + '\n')
    path.chmod(0o600)
    return path


@pytest.mark.parametrize('url', ['http://vpzhimeqmuzyzfozcjnq.supabase.co', 'https://other.supabase.co',
    m.ORIGIN + '/path', m.ORIGIN + '?key=private', m.ORIGIN + '@evil.invalid'])
def test_wrong_destination_rejected_before_network(tmp_path, url):
    with pytest.raises(m.SetupError, match='exact allowlisted'):
        m.configuration(private_env(tmp_path, url), environment={})


def test_private_env_conventions_and_no_interpolation(tmp_path):
    path = private_env(tmp_path)
    values, key = m.configuration(path, environment={})
    assert key == MOCK_KEY
    path.write_text('SUPABASE_URL=' + m.ORIGIN + '\nSUPABASE_SERVICE_ROLE_KEY=literal-${UNSET}\n')
    assert m.configuration(path, environment={})[1] == 'literal-${UNSET}'
    path.chmod(0o644)
    with pytest.raises(m.SetupError, match='0400/0600'):
        m.configuration(path, environment={})


def test_symlink_env_refused(tmp_path):
    target = private_env(tmp_path); link = tmp_path / 'linked'; link.symlink_to(target)
    with pytest.raises(m.SetupError, match='Cannot read'):
        m.configuration(link, environment={})


class ErrorOpener:
    def __init__(self, error):
        self.error = error
    def open(self, *args, **kwargs):
        raise self.error


@pytest.mark.parametrize('error', [
    HTTPError(m.ORIGIN, 422, 'backend echoed ' + MOCK_PASSWORD + MOCK_KEY, {}, io.BytesIO(MOCK_PASSWORD.encode())),
    URLError('private detail ' + MOCK_PASSWORD + MOCK_KEY),
    HTTPError(m.ORIGIN, 302, 'private redirect', {'Location': 'https://evil.invalid'}, None)
])
def test_transport_errors_are_sanitized_and_payload_cleared(error):
    api = m.Auth(MOCK_KEY, ErrorOpener(error)); payload = {'email': m.ACCOUNTS[0], 'password': m.TEST_PASSWORD, 'email_confirm': True}
    with pytest.raises(m.SetupError) as failure:
        api.request('POST', '/admin/users', payload)
    assert MOCK_PASSWORD not in str(failure.value) and MOCK_KEY not in str(failure.value)
    assert payload == {}


@pytest.mark.parametrize('path', ['/admin/generate_link', '/invite', '/verify', '/token', 'https://evil.invalid'])
def test_auth_sessions_email_and_foreign_routes_are_not_supported(path):
    with pytest.raises(m.SetupError, match='endpoint'):
        m.Auth(MOCK_KEY).request('POST', path, {})


def test_creation_requires_fixed_password_and_confirmation():
    for payload in [{'email': m.ACCOUNTS[0], 'email_confirm': True},
                    {'email': m.ACCOUNTS[0], 'password': MOCK_PASSWORD, 'email_confirm': True},
                    {'email': m.ACCOUNTS[0], 'password': m.TEST_PASSWORD, 'email_confirm': False},
                    {'email': 'unrelated@example.invalid', 'password': m.TEST_PASSWORD, 'email_confirm': True}]:
        with pytest.raises(m.SetupError, match='confirmed test credentials'):
            m.Auth(MOCK_KEY).request('POST', '/admin/users', payload)


def cli_mocks(monkeypatch, api):
    monkeypatch.setattr(m, 'configuration', lambda path: ({}, MOCK_KEY))
    monkeypatch.setattr(m, 'Auth', lambda key: api)


def test_cli_missing_accounts_are_prepared_without_interactive_input(monkeypatch, capsys):
    api = FakeAuth(); cli_mocks(monkeypatch, api)
    monkeypatch.setattr(sys.stdin, 'isatty', lambda: False)
    monkeypatch.setattr('builtins.input', lambda _: pytest.fail('Setup prompted for input.'))
    assert m.main(['--apply']) == 0
    assert len(api.users) == 5
    assert all(body['password'] == 'test1234' and body['email_confirm'] is True
               for _, _, body in api.writes)
    assert 'account_setup_complete' in capsys.readouterr().out


def test_cli_defaults_to_readonly_plan(monkeypatch, capsys):
    api = FakeAuth(); cli_mocks(monkeypatch, api)
    monkeypatch.setattr(m, 'apply', lambda *a, **k: pytest.fail('Dry-run attempted apply.'))
    assert m.main([]) == 0
    output = capsys.readouterr().out
    assert 'dry_run' in output and 'create_confirmed' in output
    assert MOCK_KEY not in output and not api.writes


def test_cli_argument_errors_never_echo_accidental_secret(capsys):
    with pytest.raises(SystemExit):
        m.main(['--password', MOCK_PASSWORD])
    assert MOCK_PASSWORD not in capsys.readouterr().err


def test_cli_partial_failure_output_contains_no_password_or_key(monkeypatch, capsys):
    api = FakeAuth(); cli_mocks(monkeypatch, api)
    def failed(*a):
        raise m.PartialFailure([{'email': m.ACCOUNTS[0], 'status': 'created_confirmed'}],
                              {'email': m.ACCOUNTS[1], 'status': 'not_verified'})
    monkeypatch.setattr(m, 'apply', failed)
    assert m.main(['--apply']) == 1
    output = capsys.readouterr().out
    assert 'partial_failure' in output and MOCK_PASSWORD not in output and MOCK_KEY not in output


def test_inventory_failure_after_success_reports_partial_results():
    api = FakeAuth(); original = api.request
    def failing(method, path, payload=None):
        if method == 'GET' and path.startswith('/admin/users?page=') and api.writes:
            raise m.SetupError('Sanitized read failure.')
        return original(method, path, payload)
    api.request = failing
    with pytest.raises(m.PartialFailure) as error:
        apply(api)
    assert len(api.writes) == 1 and len(error.value.results) == 1
    assert error.value.current['status'] == 'inventory_recheck_failed_no_write'


def test_interruption_after_success_reports_partial_without_more_writes():
    api = FakeAuth(); original = api.request
    def interrupted(method, path, payload=None):
        if method == 'POST' and payload['email'] == m.ACCOUNTS[1]:
            raise KeyboardInterrupt()
        return original(method, path, payload)
    api.request = interrupted
    with pytest.raises(m.PartialFailure) as error:
        apply(api)
    assert len(api.writes) == 1 and len(error.value.results) == 1
    assert error.value.current['status'] == 'interrupted_write_status_unknown'


@pytest.mark.parametrize('payload', [{'password': m.TEST_PASSWORD}, {'email_confirm': True},
    {'password': MOCK_PASSWORD, 'email_confirm': True},
    {'password': m.TEST_PASSWORD, 'email_confirm': True, 'app_metadata': {}},
    {'password': m.TEST_PASSWORD, 'email_confirm': False}])
def test_updates_only_accept_the_fixed_test_credentials(payload):
    with pytest.raises(m.SetupError, match='confirmed test credentials'):
        m.Auth(MOCK_KEY).request('PUT', '/admin/users/' + str(UUID(int=1)), payload)


class RecordingOpener:
    def __init__(self, user):
        self.user, self.calls = user, []

    def open(self, request, timeout):
        self.calls.append(request)
        return io.BytesIO(json.dumps(self.user).encode())


def test_update_checks_allowlisted_identity_before_submitting_credentials():
    opener = RecordingOpener(record(confirmed=True))
    payload = {'password': m.TEST_PASSWORD, 'email_confirm': True}
    m.Auth(MOCK_KEY, opener).request('PUT', '/admin/users/' + record()['id'], payload)
    assert [request.method for request in opener.calls] == ['GET', 'PUT']
    assert json.loads(opener.calls[1].data) == {'password': 'test1234', 'email_confirm': True}
    assert payload == {}


@pytest.mark.parametrize('user', [record(email='unrelated@example.invalid'), record(1)])
def test_update_refuses_unrelated_or_mismatched_identity(user):
    opener = RecordingOpener(user)
    with pytest.raises(m.SetupError):
        m.Auth(MOCK_KEY, opener).request('PUT', '/admin/users/' + record()['id'],
            {'password': m.TEST_PASSWORD, 'email_confirm': True})
    assert [request.method for request in opener.calls] == ['GET']


def test_deletion_remains_unsupported():
    with pytest.raises(m.SetupError, match='endpoint'):
        m.Auth(MOCK_KEY).request('DELETE', '/admin/users/' + record()['id'])


def test_narrow_cli_rejects_removed_actions_without_loading_credentials(monkeypatch,capsys):
    monkeypatch.setattr(m,'configuration',lambda _:pytest.fail('Unsupported action loaded credentials.'))
    for args in [['--reset-password',m.ACCOUNTS[0]],['--admin-confirm-email'],['--sign-in'],['--check-readiness']]:
        with pytest.raises(SystemExit):m.main(args)
    assert MOCK_PASSWORD not in capsys.readouterr().err


def test_cli_existing_accounts_finish_without_prompts(monkeypatch,capsys):
    api=FakeAuth([record(i) for i in range(5)]);cli_mocks(monkeypatch,api)
    monkeypatch.setattr(sys.stdin,'isatty',lambda:False)
    monkeypatch.setattr('builtins.input',lambda _:pytest.fail('Existing user prompted.'))
    assert m.main(['--apply'])==0 and len(api.writes)==5
    assert 'account_setup_complete' in capsys.readouterr().out


def test_final_inventory_failure_stops_after_success_without_repeating_writes(monkeypatch,capsys):
    api=FakeAuth([record(i) for i in range(5)]);cli_mocks(monkeypatch,api);count=[0]
    original=m.list_accounts
    def inventory(current):
        count[0]+=1
        if count[0]>6:raise m.SetupError('Offline final inventory failure.')
        return original(current)
    monkeypatch.setattr(m,'list_accounts',inventory)
    assert m.main(['--apply'])==1 and len(api.writes)==5
    assert 'final_inventory_unavailable_no_retry' in capsys.readouterr().out


def fixture_make(tmp_path):
    import sys,os
    root=Path(__file__).resolve().parents[1]
    source=next(path for path in (root/'Makefile',root/'Makefile.proposed',root.parent/'Makefile.proposed') if path.exists())
    proposed=source.read_text()
    (tmp_path/'Makefile').write_text(proposed)
    scripts=tmp_path/'scripts';scripts.mkdir()
    # Only stub scripts run in this isolated temporary directory.
    (scripts/'setup_memoir_test_accounts.py').write_text('import os,sys\nfrom pathlib import Path\nwith Path("order.log").open("a") as f:f.write("setup\\n")\nsys.exit(int(os.environ.get("FIXTURE_SETUP_EXIT","0")))\n')
    (scripts/'run_memoir_supabase_evaluation.py').write_text('from pathlib import Path\nwith Path("order.log").open("a") as f:f.write("runner\\n")\n')
    bin_path=tmp_path/'bin';bin_path.mkdir();node=bin_path/'node';node.write_text('#!/bin/sh\nexit 0\n');node.chmod(0o700)
    return ['make','MEMOIR_TEST_ACCOUNTS_PYTHON='+sys.executable,'EVAL_START_BACKEND=0','EVAL_RUN_ID=offline-run',
        'EVAL_RUN_DIR='+str(tmp_path/'run'),'PATH='+str(bin_path)+':'+os.environ.get('PATH','/usr/bin:/bin')]


def test_make_setup_precedes_each_run_and_plan_has_no_setup(tmp_path):
    import subprocess
    args=fixture_make(tmp_path)
    for _ in range(2):
        result=subprocess.run(args+['memoir-live-fifty-test'],cwd=tmp_path,capture_output=True,text=True)
        assert result.returncode==0,result.stderr
    assert (tmp_path/'order.log').read_text().splitlines()==['setup','runner','setup','runner']
    (tmp_path/'order.log').unlink()
    result=subprocess.run(args+['memoir-live-fifty-plan'],cwd=tmp_path,capture_output=True,text=True)
    assert result.returncode==0 and (tmp_path/'order.log').read_text().splitlines()==['runner']


def test_make_failed_setup_prevents_existing_test_recipe(tmp_path,monkeypatch):
    import subprocess
    args=fixture_make(tmp_path);monkeypatch.setenv('FIXTURE_SETUP_EXIT','1')
    result=subprocess.run(args+['memoir-live-fifty-test'],cwd=tmp_path,capture_output=True,text=True)
    assert result.returncode!=0 and (tmp_path/'order.log').read_text().splitlines()==['setup']


def test_make_dry_run_orders_setup_and_preserves_existing_case_flags(tmp_path):
    import subprocess
    args=fixture_make(tmp_path)
    result=subprocess.run(args+['-n','memoir-live-fifty-test','EVAL_CASE_ID=harbour-copper-notebook'],
        cwd=tmp_path,capture_output=True,text=True)
    assert result.returncode==0 and not (tmp_path/'order.log').exists()
    assert result.stdout.index('setup_memoir_test_accounts.py')<result.stdout.index('run_memoir_supabase_evaluation.py')
    assert '--create-confirmed-test-user' in result.stdout and '--case-id' in result.stdout


