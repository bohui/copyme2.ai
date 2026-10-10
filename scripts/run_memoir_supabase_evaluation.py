#!/usr/bin/env python3
"""Backend-only original fifty-round conversations, retained in remote Supabase.

Planning never contacts a service. Execution uses the normal authenticated API
and RLS readbacks; it does not start PostgreSQL, a browser, or a frontend.
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
import html
import json
import math
import os
from pathlib import Path
import stat
import subprocess
import sys
import time
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.memoir_fifty_readback import CASE_IDS, CHECKPOINTS, DATASET_SHA256, FiftyReadback, case_plans_for_run
from scripts.issue14_subscription_runner import _canonical_state, _saved_checkpoint, _readback_call
from scripts.run_issue14_subscription_evaluation import local_checkout_snapshot, verify_execution_source


class EvaluationError(ValueError):
    """Only fixed safe reasons enter stdout or saved evidence."""


def base_url(value):
    parsed = urlsplit(value)
    if (parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username
            or parsed.password or parsed.query or parsed.fragment or parsed.path not in {'', '/'}):
        raise EvaluationError('A plain HTTP(S) service origin is required')
    return value.rstrip('/')


def save(path, value):
    path = Path(path)
    # Atomic writes keep the last complete partial receipt after interruption.
    temporary = path.with_name(path.name + '.tmp')
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, 'w') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    os.replace(temporary, path)


def output_directory(directory):
    directory = Path(directory).resolve()
    if directory == ROOT or ROOT in directory.parents or directory.exists():
        raise EvaluationError('Use a fresh output directory outside the checkout')
    directory.mkdir(parents=True, mode=0o700)
    return directory


def configuration(env_file):
    values = {}
    path = Path(env_file)
    if path.exists():
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) not in {0o400, 0o600}):
            raise EvaluationError('ENV_FILE must be an owned private 0400/0600 regular file')
        values = dotenv_values(path, interpolate=False)
    return {**values, **os.environ}


def build_plan(*, run_id, source_revision, case_id, api_base, web_base,
               max_seconds, max_case_seconds, max_backend_requests, user_email,
               settle_seconds=600, poll_seconds=2):
    if str(UUID(run_id)) != run_id or case_id is not None and case_id not in CASE_IDS:
        raise EvaluationError('A canonical UUID and original case ID are required')
    for value, maximum in ((max_seconds, 7200 if case_id else 36000),
                           (max_case_seconds, 7200), (settle_seconds, 1800), (poll_seconds, 30)):
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= maximum:
            raise EvaluationError('Finite positive bounded evaluation times are required')
    if type(max_backend_requests) is not int or not 0 < max_backend_requests <= 100000:
        raise EvaluationError('A bounded backend HTTP request ceiling is required')
    if not user_email or '@' not in user_email or any(c in user_email for c in '\r\n'):
        raise EvaluationError('Set EVAL_USER_EMAIL to the intended UI account')
    api_base, web_base = base_url(api_base), base_url(web_base)
    cases = case_plans_for_run(run_id)
    cases = {key: {**value, 'owner_id': None,
        'ui_url': web_base + '/memoir/interview/' + value['project_id']}
        for key, value in cases.items() if case_id is None or key == case_id}
    return {'schema_version': 'memoir-subscription-evaluation-plan/1',
        'evaluation_profile': 'subscription_fifty', 'storage_backend': 'remote_supabase',
        'run_id': run_id, 'source_revision': source_revision,
        'local_checkout_source': local_checkout_snapshot(source_revision),
        'case_ids': list(cases), 'cases': cases, 'rounds_per_case': 50,
        'checkpoints': list(CHECKPOINTS), 'dataset_sha256': DATASET_SHA256,
        'user_email': user_email, 'api_base': api_base, 'web_base': web_base,
        'max_elapsed_seconds': max_seconds, 'max_case_elapsed_seconds': max_case_seconds,
        'max_backend_requests': max_backend_requests, 'settle_seconds': settle_seconds,
        'poll_seconds': poll_seconds, 'execution_started': False,
        'concurrency': 1, 'browser_started': False, 'local_postgres_started': False,
        'actual_upstream_provider_requests': None, 'hard_token_cap_verified': False,
        'hard_dollar_cap_verified': False, 'model_request_ceiling_verified': False}


class Requests:
    def __init__(self, client, maximum, seconds):
        self.client, self.maximum = client, maximum
        self.deadline = time.monotonic() + seconds
        self.case_deadline = self.deadline
        self.reserved = 0

    def remaining(self):
        return min(self.deadline, self.case_deadline) - time.monotonic()

    async def json(self, method, url, **kwargs):
        remaining = self.remaining()
        if remaining <= 0 or self.reserved >= self.maximum:
            raise EvaluationError('Backend request or elapsed-time ceiling reached')
        self.reserved += 1
        timeout = min(kwargs.pop('timeout', 30), remaining)
        try:
            response = await self.client.request(method, url, timeout=timeout, **kwargs)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as error:
            raise EvaluationError('HTTP request failed with status ' + str(error.response.status_code)) from None
        except (httpx.RequestError, ValueError):
            raise EvaluationError('HTTP request failed or returned invalid JSON') from None


@dataclass
class SupabaseAccount:
    requests: Requests
    url: str
    public_key: str
    secret_key: str
    user: dict | None = None
    access_token: str | None = None
    refresh_token: str | None = None
    expires_at: float = 0

    def admin_headers(self):
        return {'apikey': self.secret_key, 'Authorization': 'Bearer ' + self.secret_key}

    async def auth(self, method, path, *, admin=False, **kwargs):
        return await self.requests.json(method, self.url + '/auth/v1' + path,
            headers=self.admin_headers() if admin else {'apikey': self.public_key}, **kwargs)

    async def ensure_user(self, email, *, create_confirm=False):
        found = None
        for page in range(1, 101):
            users = (await self.auth('GET', '/admin/users', admin=True,
                params={'page': page, 'per_page': 100})).get('users', [])
            found = next((user for user in users if str(user.get('email', '')).casefold() == email.casefold()), None)
            if found or len(users) < 100:
                break
        else:
            raise EvaluationError('Auth user lookup exceeded its bounded page limit')
        if found is None:
            if not create_confirm:
                raise EvaluationError('UI account is missing; run make memoir-live-fifty-login to create and confirm it')
            try:
                found = await self.auth('POST', '/admin/users', admin=True,
                    json={'email': email, 'email_confirm': True})
            except EvaluationError:
                # A timed-out create may have succeeded. Reconcile by email,
                # without repeating the account write or changing a password.
                return await self.ensure_user(email, create_confirm=False)
        if found.get('is_anonymous'):
            raise EvaluationError('A permanent UI account is required')
        owner = str(UUID(found['id']))
        if not found.get('email_confirmed_at'):
            if not create_confirm:
                raise EvaluationError('UI email is unconfirmed; run make memoir-live-fifty-login')
            found = await self.auth('PUT', '/admin/users/' + owner, admin=True,
                json={'email_confirm': True})
        verified = await self.auth('GET', '/admin/users/' + owner, admin=True)
        if (verified.get('id') != owner or str(verified.get('email', '')).casefold() != email.casefold()
                or not verified.get('email_confirmed_at') or verified.get('is_anonymous')):
            raise EvaluationError('Confirmed UI account readback did not match')
        self.user = verified
        return owner

    async def generate_link(self, destination):
        result = await self.auth('POST', '/admin/generate_link', admin=True,
            json={'type': 'magiclink', 'email': self.user['email'], 'redirect_to': destination})
        link = result.get('action_link')
        parsed = urlsplit(link or '')
        if (parsed.scheme != urlsplit(self.url).scheme or parsed.netloc != urlsplit(self.url).netloc
                or parsed.path != '/auth/v1/verify' or result.get('id') != self.user['id']):
            raise EvaluationError('Generated login link did not match the intended Supabase user')
        return result

    async def sign_in(self):
        generated = await self.generate_link(self.url)
        await self.set_session(await self.auth('POST', '/verify',
            json={'type': 'magiclink', 'token_hash': generated['hashed_token']}))

    async def set_session(self, value):
        if (value.get('user', {}).get('id') != self.user['id']
                or not value.get('access_token') or not value.get('refresh_token')):
            raise EvaluationError('Authenticated session did not match the intended UI owner')
        self.access_token, self.refresh_token = value['access_token'], value['refresh_token']
        self.expires_at = time.monotonic() + max(1, value.get('expires_in', 3600) - 60)

    async def headers(self):
        if time.monotonic() >= self.expires_at:
            await self.set_session(await self.auth('POST', '/token',
                params={'grant_type': 'refresh_token'}, json={'refresh_token': self.refresh_token}))
        return {'apikey': self.public_key, 'Authorization': 'Bearer ' + self.access_token}

    async def read(self, path, *, method='GET', **kwargs):
        return await self.requests.json(method, self.url + path, headers=await self.headers(), **kwargs)

    async def rpc(self, name, **payload):
        return await self.read('/rest/v1/rpc/' + name, method='POST', json=payload)

    async def login_file(self, directory, destination):
        generated = await self.generate_link(destination)
        if parse_qs(urlsplit(generated['action_link']).query).get('redirect_to') != [destination]:
            raise EvaluationError('Allow WEB_BASE in Supabase Auth redirect URLs before creating a UI login link')
        path = directory / 'ui-login.html'
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, 'w') as stream:
            stream.write('<!doctype html><meta charset="utf-8"><meta name="referrer" content="no-referrer">'
                '<title>Memoir test sign-in</title><p>Private, expiring, one-time sign-in link.</p>'
                '<a href="' + html.escape(generated['action_link'], quote=True) + '">Sign in to Memoir</a>')
        return path


async def backend(requests, account, plan, method, path, **kwargs):
    return await requests.json(method, plan['api_base'] + '/api' + path,
        headers=await account.headers(), **kwargs)


async def preflight(account, plan):
    requests = account.requests
    config = await backend(requests, account, plan, 'GET', '/v1/agent/config')
    if (config.get('auth_mode') != 'supabase' or base_url(config.get('supabase_url', '')) != account.url
            or config.get('private_draft_cadence') != 5):
        raise EvaluationError('Backend must use the configured remote Supabase with five-round draft cadence')
    state = await backend(requests, account, plan, 'GET', '/v1/story/state')
    if state.get('user_id') != account.user['id'] or state.get('is_anonymous'):
        raise EvaluationError('Backend authenticated owner did not match')
    recall = state.get('recall_status') or {}
    needed = len(plan['case_ids']) * 50
    if not recall.get('paid') and recall.get('free_rounds', 0) - recall.get('rounds_completed', 0) < needed:
        raise EvaluationError('Account allowance is too small; enable EVAL_START_BACKEND=1 for the scoped local test allowance')
    return {'family_features_enabled': state.get('family_features_enabled', False),
            'recall_status': recall, 'backend_auth_mode': config['auth_mode']}


async def wait_for_backend(requests, plan):
    deadline = min(requests.deadline, time.monotonic() + 120)
    while time.monotonic() < deadline:
        try:
            health = await requests.json('GET', plan['api_base'] + '/health', timeout=5)
            if health.get('status') == 'ok':
                return
        except EvaluationError:
            if requests.remaining() <= 0 or requests.reserved >= requests.maximum:
                raise
        await asyncio.sleep(min(2, max(0, deadline - time.monotonic())))
    raise EvaluationError('Local backend did not become healthy before its deadline')


async def run_cases(account, plan, directory, receipt):
    requests = account.requests
    for case_id, binding in plan['cases'].items():
        requests.case_deadline = min(requests.deadline, time.monotonic() + plan['max_case_elapsed_seconds'])
        project = binding['project_id']
        case = {'case_id': case_id, 'project_id': project, 'owner_id': binding['owner_id'],
                'ui_url': binding['ui_url'], 'status': 'running', 'rounds': [], 'checkpoints': []}
        receipt['evaluation']['cases'].append(case)
        save(directory / 'receipt.json', receipt)
        print(f"Case {case_id}: {project}\nUI: {binding['ui_url']}", file=sys.stderr, flush=True)
        initial = await account.rpc('read_user_memory_events', p_project_id=project)
        if initial.get('sources') or initial.get('completed_rounds') or initial.get('events'):
            raise EvaluationError('Evaluation project must be fresh')
        inputs = FiftyReadback(case_id=case_id, run_id=plan['run_id'], project_id=project,
                               source_revision=plan['source_revision']).driver_inputs()
        accepted = []
        for ordinal, text in enumerate(inputs['rounds'], 1):
            record = {'round': ordinal, 'client_turn_id': str(uuid4()), 'status': 'submitting',
                      'background_settled': False}
            case['rounds'].append(record)
            receipt['backend_turn_submissions'] += 1
            save(directory / 'receipt.json', receipt)
            # Exactly one original submission. Failures never trigger a POST retry.
            result = await backend(requests, account, plan, 'POST', '/v1/agent/turn', timeout=600,
                json={'project_id': project, 'language': binding['language'], 'text': text,
                    'conversation_text': text, 'source_kind': 'narrator_chat',
                    'client_turn_id': record['client_turn_id']})
            if (result.get('project_id') != project or not result.get('accepted_source_id')
                    or not isinstance(result.get('reply'), str) or not result['reply'].strip()
                    or result.get('cached') or result.get('task_errors')):
                raise EvaluationError('Original conversation was not freshly delivered and saved')
            record.update(status='delivered', accepted_source_id=result['accepted_source_id'], reply=result['reply'])
            accepted.append(result['accepted_source_id'])
            save(directory / 'receipt.json', receipt)
            settle_deadline = min(requests.case_deadline, time.monotonic() + plan['settle_seconds'])
            while True:
                if time.monotonic() >= settle_deadline:
                    raise EvaluationError('Background extraction or saved checkpoint did not settle before its deadline')
                view = await account.rpc('read_user_memory_events', p_project_id=project)
                if (view.get('completed_rounds') == ordinal
                        and view.get('processing', {}).get('extracted_through') == ordinal
                        and view.get('processing', {}).get('pending_inputs') == 0):
                    _readback_call(record, 'canonical', _canonical_state, view, inputs, accepted)
                    if ordinal in CHECKPOINTS:
                        draft = await account.rpc('read_user_memoir_draft',
                            p_project_id=project, p_locale=binding['language'], p_cadence=5)
                        if draft.get('error') or draft.get('status') == 'failed':
                            raise EvaluationError('Saved checkpoint failed; explicit review is required')
                        if draft.get('status') != 'ready' or draft.get('covered_round') != ordinal or draft.get('updating'):
                            await asyncio.sleep(min(plan['poll_seconds'], max(0, settle_deadline - time.monotonic())))
                            continue
                        _readback_call(record, 'checkpoint', _saved_checkpoint, draft, ordinal, binding['language'])
                        case['checkpoints'].append({'milestone': ordinal, 'draft': draft})
                    break
                await asyncio.sleep(min(plan['poll_seconds'], max(0, settle_deadline - time.monotonic())))
            record.update(status='completed', background_settled=True, canonical_state=view)
            save(directory / 'receipt.json', receipt)
            print(f'{case_id}: round {ordinal}/50 saved', file=sys.stderr, flush=True)
        # Exercise the same authenticated recovery route the UI uses.
        shell = await backend(requests, account, plan, 'GET', '/v1/projects/' + project)
        if shell.get('id') != project or not shell.get('requires_supabase_auth'):
            raise EvaluationError('Normal UI project recovery did not match the retained project')
        case.update(status='completed', ui_recovery_verified=True)
        save(directory / 'receipt.json', receipt)


async def execute(plan, directory, settings, *, start_backend=False, create_confirm=False):
    directory = output_directory(directory)
    save(directory / 'plan.json', plan)
    receipt = {'schema_version': 'memoir-supabase-evaluation-receipt/1',
        'run_id': plan['run_id'], 'source_revision': plan['source_revision'],
        'local_checkout_source': plan['local_checkout_source'], 'status': 'incomplete',
        'storage_backend': 'remote_supabase', 'data_retained': True,
        'browser_started': False, 'local_postgres_started': False, 'execution_started': False,
        'backend_turn_submissions': 0,
        'semantic_acceptance': 'human_review_required', 'actual_upstream_provider_requests': None,
        'evaluation': {'status': 'running', 'cases': []}}
    save(directory / 'receipt.json', receipt)
    stage = 'authentication'
    async with httpx.AsyncClient(follow_redirects=False, trust_env=False) as client:
        requests = Requests(client, plan['max_backend_requests'], plan['max_elapsed_seconds'])
        try:
            account = SupabaseAccount(requests, base_url(settings.get('SUPABASE_URL', '')),
                settings['SUPABASE_PUBLISHABLE_KEY'], settings.get('SUPABASE_SECRET_KEY') or settings['SUPABASE_SERVICE_ROLE_KEY'])
            owner = await account.ensure_user(plan['user_email'], create_confirm=create_confirm)
            await account.sign_in()
            for binding in plan['cases'].values():
                binding['owner_id'] = owner
            save(directory / 'plan.json', plan)
            if start_backend:
                stage = 'backend_startup'
                usage = await account.read('/rest/v1/user_recall_usage',
                    params={'select': 'rounds_completed', 'user_id': 'eq.' + owner, 'limit': '1'})
                limit = (int(usage[0]['rounds_completed']) if usage else 0) + len(plan['case_ids']) * 50
                environment = {**settings, 'MEMORY_SPARK_EVAL_RECALL_OWNER_ID': owner,
                    'MEMORY_SPARK_EVAL_RECALL_LIMIT': str(limit),
                    'SUPABASE_SECRET_KEY': account.secret_key,
                    'MEMORY_SPARK_API_PORT': str(urlsplit(plan['api_base']).port or 80)}
                if urlsplit(plan['api_base']).hostname not in {'localhost', '127.0.0.1'}:
                    raise EvaluationError('Automatic backend startup requires a local API origin')
                result = await asyncio.to_thread(subprocess.run,
                    ['make', '--no-print-directory', 'memoir-live-fifty-backend'], cwd=ROOT,
                    env={k: str(v) for k, v in environment.items() if v is not None},
                    stdout=sys.stderr, stderr=sys.stderr, timeout=min(180, requests.remaining()))
                if result.returncode:
                    raise EvaluationError('Backend startup failed; see the backend output')
                await wait_for_backend(requests, plan)
            stage = 'backend_preflight'
            receipt['preflight'] = await preflight(account, plan)
            verify_execution_source(plan['source_revision'], plan['local_checkout_source'])
            stage = 'conversation'
            receipt['execution_started'] = True
            await run_cases(account, plan, directory, receipt)
            receipt['status'] = receipt['evaluation']['status'] = 'completed'
        except (Exception, asyncio.CancelledError) as error:
            receipt['status'] = receipt['evaluation']['status'] = 'incomplete'
            receipt['evaluation']['failure_stage'] = stage
            receipt['stop_reason'] = str(error) if isinstance(error, EvaluationError) else 'Backend evaluation failed; inspect retained evidence'
            cases = receipt['evaluation']['cases']
            if cases and cases[-1]['status'] != 'completed':
                cases[-1]['status'] = 'incomplete'
                if cases[-1]['rounds'] and cases[-1]['rounds'][-1]['status'] != 'completed':
                    cases[-1]['rounds'][-1].update(status='incomplete', failure_summary={'reason': receipt['stop_reason']})
        finally:
            requests.case_deadline = requests.deadline
            if 'account' in locals() and account.user:
                try:
                    cases = receipt['evaluation']['cases']
                    destination = cases[-1]['ui_url'] if cases and cases[-1]['rounds'] else plan['web_base'] + '/memoir/start'
                    await account.login_file(directory, destination)
                    receipt['ui_login_file'] = 'ui-login.html'
                except Exception:
                    receipt['ui_login_file'] = None
            receipt['request_accounting'] = {'backend_http_requests_reserved': requests.reserved,
                'actual_upstream_provider_requests': None, 'model_request_ceiling_verified': False}
            try:
                verify_execution_source(plan['source_revision'], plan['local_checkout_source'])
                receipt['local_checkout_unchanged'] = True
            except Exception:
                receipt['local_checkout_unchanged'] = False
                receipt['status'] = receipt['evaluation']['status'] = 'incomplete'
                receipt['stop_reason'] = 'source_changed_during_run'
            save(directory / 'receipt.json', receipt)
    return receipt


async def prepare_user(settings, email, directory, web_base, project_id=None):
    directory = output_directory(directory)
    async with httpx.AsyncClient(follow_redirects=False, trust_env=False) as client:
        account = SupabaseAccount(Requests(client, 1000, 120), base_url(settings['SUPABASE_URL']),
            settings['SUPABASE_PUBLISHABLE_KEY'], settings.get('SUPABASE_SECRET_KEY') or settings['SUPABASE_SERVICE_ROLE_KEY'])
        owner = await account.ensure_user(email, create_confirm=True)
        destination = base_url(web_base) + ('/memoir/interview/' + project_id if project_id else '/memoir/start')
        path = await account.login_file(directory, destination)
        return {'email': email, 'owner_id': owner, 'email_confirmed': True, 'ui_login_file': str(path)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--execute', action='store_true')
    modes.add_argument('--prepare-user', action='store_true')
    parser.add_argument('--start-backend', action='store_true')
    parser.add_argument('--create-confirmed-test-user', action='store_true')
    parser.add_argument('--env-file', type=Path, default=ROOT / '.env')
    parser.add_argument('--user-email', default=os.getenv('MEMOIR_EVAL_USER_EMAIL'))
    parser.add_argument('--case-id', choices=CASE_IDS)
    parser.add_argument('--project-id')
    parser.add_argument('--api-base', default='http://127.0.0.1:8010')
    parser.add_argument('--web-base', default='http://127.0.0.1:3010')
    parser.add_argument('--run-id', default=None)
    parser.add_argument('--run-dir', type=Path)
    parser.add_argument('--source-revision')
    parser.add_argument('--max-elapsed-seconds', type=float)
    parser.add_argument('--max-case-elapsed-seconds', type=float, default=7200)
    parser.add_argument('--max-backend-requests', type=int)
    parser.add_argument('--settle-seconds', type=float, default=600)
    parser.add_argument('--poll-seconds', type=float, default=2)
    args = parser.parse_args(argv)
    try:
        run_id = args.run_id or str(uuid4())
        directory = args.run_dir or Path.home() / 'memoir-test-results' / run_id
        settings = configuration(args.env_file) if args.execute or args.prepare_user else {}
        email = args.user_email or settings.get('MEMOIR_EVAL_USER_EMAIL') or 'test@test.com'
        if args.prepare_user:
            if args.project_id and (len(args.project_id) > 128 or not all(c.isalnum() or c in '_-' for c in args.project_id)):
                raise EvaluationError('A valid project ID is required')
            result = asyncio.run(prepare_user(settings, email, directory,
                                             args.web_base, args.project_id))
            print(json.dumps(result))
            return 0
        revision = args.source_revision or subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
        plan = build_plan(run_id=run_id, source_revision=revision, case_id=args.case_id,
            api_base=args.api_base, web_base=args.web_base, user_email=email,
            max_seconds=args.max_elapsed_seconds if args.max_elapsed_seconds is not None else (7200 if args.case_id else 36000),
            max_case_seconds=args.max_case_elapsed_seconds,
            max_backend_requests=args.max_backend_requests if args.max_backend_requests is not None else (20000 if args.case_id else 100000),
            settle_seconds=args.settle_seconds, poll_seconds=args.poll_seconds)
        if not args.execute:
            print(json.dumps(plan, sort_keys=True))
            return 0
        print('Evidence directory: ' + str(directory), file=sys.stderr, flush=True)
        result = asyncio.run(execute(plan, directory, settings,
            start_backend=args.start_backend, create_confirm=args.create_confirmed_test_user))
        print(json.dumps({'run_id': run_id, 'status': result['status'], 'receipt_path': str(directory / 'receipt.json'),
                         'stop_reason': result.get('stop_reason'), 'projects': plan['cases']}))
        return 0 if result['status'] == 'completed' else 3
    except (Exception, KeyboardInterrupt) as error:
        print(json.dumps({'status': 'blocked', 'reason': str(error) if isinstance(error, EvaluationError)
                         else 'Remote evaluation configuration or preparation failed'}))
        return 3


if __name__ == '__main__':
    raise SystemExit(main())
