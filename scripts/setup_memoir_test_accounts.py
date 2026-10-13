#!/usr/bin/env python3
"""Provision the five fixed evaluation accounts; default is read-only planning."""
import argparse
import io
import json
import os
from pathlib import Path
import re
import stat
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from uuid import UUID

PROJECT_REF = 'vpzhimeqmuzyzfozcjnq'
ORIGIN = 'https://' + PROJECT_REF + '.supabase.co'
ACCOUNTS = ('test@test.com', 'test2@test.com', 'test3@test.com', 'test4@test.com', 'test5@test.com')
# These dedicated evaluation accounts always use the user-requested test password.
TEST_PASSWORD = 'test1234'
PAGE_SIZE = 100
MAX_PAGES = 1000


class SetupError(Exception):
    """Only fixed, credential-free messages may cross this boundary."""


class PartialFailure(SetupError):
    def __init__(self, results, current):
        super().__init__('Apply stopped. Earlier successes remain; no write is retried automatically.')
        self.results, self.current = results, current


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def configuration(path, environment=None):
    try:
        from dotenv import dotenv_values
    except ImportError:
        raise SetupError('python-dotenv is unavailable; select an existing prepared Python environment.') from None
    environment = os.environ if environment is None else environment
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, 'r') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) not in (0o400, 0o600):
                raise SetupError('ENV_FILE must be an owned regular0400/0600 file; symlinks are not accepted.')
            values = dotenv_values(stream=io.StringIO(stream.read()), interpolate=False)
    except OSError:
        raise SetupError('Cannot read the private existing ENV_FILE.') from None
    values = {**values, **environment}
    url = str(values.get('SUPABASE_URL') or '').rstrip('/')
    if url != ORIGIN:
        raise SetupError('SUPABASE_URL must match the exact allowlisted HTTPS project.')
    key = values.get('SUPABASE_SECRET_KEY') or values.get('SUPABASE_SERVICE_ROLE_KEY')
    if not isinstance(key, str) or not key or '\n' in key or '\r' in key:
        raise SetupError('Existing server-only Supabase credential is missing or invalid.')
    return values, key


class Auth:
    def __init__(self, key, opener=None):
        self._key = key
        self._opener = opener or build_opener(ProxyHandler({}), NoRedirect())

    def request(self, method, path, payload=None):
        allowed = (method == 'GET' and (re.fullmatch(r'/admin/users\?page=\d+&per_page=100', path)
                   or re.fullmatch(r'/admin/users/[a-f0-9-]{36}', path)))
        allowed = allowed or method == 'POST' and path == '/admin/users'
        allowed = allowed or method == 'PUT' and re.fullmatch(r'/admin/users/[a-f0-9-]{36}', path)
        if not allowed:
            raise SetupError('Auth endpoint is outside the account-only allowlist.')
        if method == 'POST' and (set(payload or {}) != {'email', 'password', 'email_confirm'}
                or payload['email'] not in ACCOUNTS or payload['email_confirm'] is not True or payload['password'] != TEST_PASSWORD):
            raise SetupError('Creation must use an allowlisted address and the confirmed test credentials.')
        if method == 'PUT':
            if set(payload or {}) != {'password', 'email_confirm'} or payload['password'] != TEST_PASSWORD or payload['email_confirm'] is not True:
                raise SetupError('Updates may only set the confirmed test credentials.')
            # Never use a supplied UUID to change an unrelated user's credentials.
            current = user_record(self.request('GET', path))
            if current['id'] != path.rsplit('/', 1)[-1]:
                raise SetupError('Account identity changed before its credential update.')
        data = json.dumps(payload).encode() if payload is not None else None
        request = Request(ORIGIN + '/auth/v1' + path, data=data, method=method,
            headers={'apikey': self._key, 'Authorization': 'Bearer ' + self._key,
                     'Content-Type': 'application/json'})
        try:
            with self._opener.open(request, timeout=10) as response:
                raw = response.read(4 * 1024 * 1024 + 1)
                if len(raw) > 4 * 1024 * 1024:
                    raise SetupError('Auth response exceeded the bounded size.')
                value = json.loads(raw)
                if not isinstance(value, dict):
                    raise SetupError('Auth response shape is invalid.')
                return value
        except HTTPError as error:
            raise SetupError('Auth request rejected (HTTP' + str(error.code) + ').') from None
        except (URLError, OSError, ValueError):
            raise SetupError('Auth transport or JSON response failed; remote write status may be uncertain.') from None
        finally:
            if payload is not None:
                payload.clear()


def user_record(value, expected_email=None):
    try:
        identifier = value['id']
        if not isinstance(identifier, str) or str(UUID(identifier)) != identifier:
            raise ValueError()
        email = str(value['email']).casefold()
        if email not in ACCOUNTS or expected_email is not None and email != expected_email:
            raise ValueError()
        if value.get('is_anonymous') or value.get('deleted_at'):
            raise ValueError()
        return {'email': email, 'id': identifier, 'email_confirmed': bool(value.get('email_confirmed_at'))}
    except (KeyError, ValueError, TypeError):
        raise SetupError('Selected account identity/state is invalid; manual review is required.') from None


def list_accounts(api):
    selected, seen_ids = {}, set()
    for page in range(1, MAX_PAGES + 1):
        value = api.request('GET', '/admin/users?page=' + str(page) + '&per_page=100')
        users = value.get('users')
        if not isinstance(users, list):
            raise SetupError('Auth pagination response is invalid; no writes are safe.')
        if not users:
            return selected
        for user in users:
            if not isinstance(user, dict) or not isinstance(user.get('id'), str):
                raise SetupError('Auth pagination row is invalid.')
            identifier = user['id']
            if identifier in seen_ids:
                raise SetupError('Auth pagination repeated an identity; rerun read-only after the list stabilizes.')
            seen_ids.add(identifier)
            email = str(user.get('email') or '').casefold()
            if email in ACCOUNTS:
                if email in selected:
                    raise SetupError('Duplicate allowlisted email; manual review is required before any writes.')
                selected[email] = user_record(user)
    raise SetupError('Complete pagination exceeded its bound; no partial list will be applied.')


def plan(accounts):
    return [{'email': email, 'action': 'create_confirmed' if email not in accounts else 'configure_test_credentials',
             **accounts.get(email, {})} for email in ACCOUNTS]


def apply(api, operations):
    if (len(operations) != len(ACCOUNTS) or {item.get('email') for item in operations} != set(ACCOUNTS)
            or any(item.get('action') not in {'configure_test_credentials', 'create_confirmed'} for item in operations)):
        raise SetupError('Only configuring the five test accounts is supported.')
    results = []
    for operation in operations:
        email = operation['email']
        try:
            current = list_accounts(api).get(email)
        except SetupError:
            raise PartialFailure(results, {'email': email, 'status': 'inventory_recheck_failed_no_write'}) from None
        if operation.get('id') and (current is None or current['id'] != operation['id']):
            raise PartialFailure(results, {'email': email, 'status': 'identity_changed_no_write'})
        write_started = False
        try:
            write_started = True
            if current is None:
                value = api.request('POST', '/admin/users', {'email': email, 'password': TEST_PASSWORD, 'email_confirm': True})
            else:
                value = api.request('PUT', '/admin/users/' + current['id'], {'password': TEST_PASSWORD, 'email_confirm': True})
            observed = user_record(value, email)
            if current is not None and observed['id'] != current['id']:
                raise SetupError('Existing account identity changed; stop before further writes.')
            verified = user_record(api.request('GET', '/admin/users/' + observed['id']), email)
            if verified['id'] != observed['id']:
                raise SetupError('Account readback did not match; stop before further writes.')
            if not verified['email_confirmed']:
                raise SetupError('Test account is unconfirmed; stop before further writes.')
            results.append({**verified, 'status': 'created_confirmed' if current is None else 'configured_existing'})
        except (KeyboardInterrupt, EOFError):
            raise PartialFailure(results, {'email': email, 'status': 'interrupted_write_status_unknown' if write_started
                                          else 'interrupted_no_write'}) from None
        except SetupError:
            # A timeout may hide a successful write. Reconcile existence only,
            # never repeat the write or claim the password was verified.
            observed = None
            try:
                observed = list_accounts(api).get(email)
            except SetupError:
                pass
            raise PartialFailure(results, {'email': email, 'status': 'write_or_readback_not_verified' if write_started else 'no_write',
                'account_found_on_recheck': observed is not None, 'id': observed['id'] if observed else None}) from None
    return results



class Parser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, 'Invalid arguments; use --help. Passwords are never accepted as arguments.\n')


def main(argv=None):
    parser = Parser(description=__doc__)
    parser.add_argument('--env-file', type=Path, default=Path(__file__).resolve().parents[1] / '.env')
    parser.add_argument('--apply', action='store_true', help='Create missing users and set all five test passwords and email confirmations without prompts.')
    args = parser.parse_args(argv)
    try:
        _, key = configuration(args.env_file)
        api = Auth(key)
        accounts = list_accounts(api)
        operations = plan(accounts)
        print(json.dumps({'mode':'apply_requested' if args.apply else 'dry_run', 'project_ref':PROJECT_REF,
            'operations':operations, 'scope':'Create missing users and set all five test passwords and email confirmations. Existing account IDs and application data are preserved; no email or login flow.'}))
        if not args.apply:
            return 0
        results = apply(api, operations)
        print(json.dumps({'mode':'apply_result','accounts':results}))
        try:
            accounts = list_accounts(api)
        except SetupError:
            raise PartialFailure(results, {'status':'final_inventory_unavailable_no_retry'}) from None
        if len(accounts) != 5 or any(not accounts[row['email']]['email_confirmed']
                or accounts[row['email']]['id'] != row['id'] for row in results):
            raise PartialFailure(results, {'status':'final_account_inventory_incomplete_no_retry'})
        print(json.dumps({'status':'account_setup_complete','account_count':5,
            'accounts_created':sum(row['status'] == 'created_confirmed' for row in results),
            'accounts_configured':sum(row['status'] == 'configured_existing' for row in results),
            'application_data_changes':0}))
        return 0
    except PartialFailure as error:
        print(json.dumps({'status':'partial_failure','completed':error.results,'current':error.current,
                         'reason':str(error),'automatic_write_retry':False}))
        return 1
    except SetupError as error:
        print(json.dumps({'status':'stopped','reason':str(error)}))
        return 1
    except (KeyboardInterrupt, EOFError):
        print(json.dumps({'status':'interrupted','reason':'Setup interrupted; inspect account status read-only before retrying.'}))
        return 1
    except Exception:
        print(json.dumps({'status':'stopped','reason':'Unexpected local failure; no private error details are logged. Recheck read-only before retrying.'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
