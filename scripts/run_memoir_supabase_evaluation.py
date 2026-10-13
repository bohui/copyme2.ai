#!/usr/bin/env python3
"""Backend-only original fifty-round conversations, retained in remote Supabase.

Planning never contacts a service. Execution uses the normal authenticated API
and RLS readbacks; it does not start PostgreSQL, a browser, or a frontend.
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass, field
import html
import json
import math
import os
import re
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

from apps.api.namespaces import memoir_url
from scripts.memoir_fifty_readback import CASE_IDS, CHECKPOINTS, DATASET_SHA256, FiftyReadback, case_plans_for_run
from scripts.issue14_subscription_runner import _canonical_state, _saved_checkpoint, _readback_call
from scripts.run_issue14_subscription_evaluation import local_checkout_snapshot, verify_execution_source
from scripts.backend_operation_lock import BackendInUseError, LOCK_FD_ENV, backend_operation_lock


CASE_EMAILS = dict(zip(CASE_IDS, ('test@test.com', 'test2@test.com', 'test3@test.com', 'test4@test.com', 'test5@test.com')))
BUDGET_FIELDS = ('max_elapsed_seconds','max_case_elapsed_seconds','max_backend_requests','settle_seconds','poll_seconds')
READ_ONLY_REVALIDATION_SECONDS = 120


def selected_cases(value):
    cases = list(CASE_IDS) if value is None else [value] if isinstance(value, str) else list(value)
    if not cases or len(set(cases)) != len(cases) or any(case not in CASE_EMAILS for case in cases):
        raise EvaluationError('Select distinct original case IDs; account mapping is fixed by case ID')
    return cases


def validate_case_bindings(plan, *, bound=False):
    cases = selected_cases(plan['case_ids'])
    if list(plan['cases']) != cases:
        raise EvaluationError('Case order differs from the selected plan')
    for case_id, binding in plan['cases'].items():
        if binding.get('case_id') != case_id or binding.get('user_email') != CASE_EMAILS[case_id]:
            raise EvaluationError('Case-to-account mapping differs from the fixed original mapping')
        if bound:
            if (str(UUID(binding['owner_id'])) != binding['owner_id'] or str(UUID(binding['conversation_id'])) != binding['conversation_id']
                    or not isinstance(binding.get('project_id'), str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', binding['project_id'])):
                raise EvaluationError('Verified canonical owner/conversation/project binding is required')
    if bound and any(len({b[key] for b in plan['cases'].values()}) != len(cases) for key in ('owner_id','conversation_id','project_id')):
        raise EvaluationError('Cases must have distinct verified owners and canonical projects')


class EvaluationError(ValueError):
    """Only fixed safe reasons enter stdout or saved evidence."""

    def __init__(self, message, *, diagnostic=None):
        super().__init__(message)
        self.diagnostic = diagnostic


def base_url(value):
    parsed = urlsplit(value)
    if (parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username
            or parsed.password or parsed.query or parsed.fragment or parsed.path not in {'', '/'}):
        raise EvaluationError('A plain HTTP(S) service origin is required')
    return value.rstrip('/')


def save(path, value):
    path = Path(path)
    # Atomic writes keep the last complete partial receipt after interruption.
    temporary = path.with_name(path.name + '.' + str(uuid4()) + '.tmp')
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'w') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    os.replace(temporary, path)


def _checkpoint_error_is_terminal(draft):
    """Only stop on a durable checkpoint failure, not a retryable lane error."""
    if draft.get('status') in {'failed', 'stale'}:
        return True
    composition = (draft.get('progress') or {}).get('composition') or {}
    if composition.get('state') == 'retry_required':
        return True
    if not draft.get('error'):
        return False
    return not (draft.get('updating') is True
                and composition.get('state') in {'pending', 'running'}
                and composition.get('pending') is True)


def _extraction_error_is_terminal(draft):
    """Surface an exhausted extraction lane before the settle deadline."""
    extraction = (draft.get('progress') or {}).get('extraction') or {}
    return extraction.get('state') == 'retry_required'


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
               settle_seconds=600, poll_seconds=2, original_case_ids=None):
    selection = selected_cases(case_id)
    budget_selection = selected_cases(original_case_ids) if original_case_ids is not None else selection
    if any(case not in budget_selection for case in selection):
        raise EvaluationError('Selected case is outside the original saved campaign')
    if str(UUID(run_id)) != run_id:
        raise EvaluationError('A canonical run UUID is required')
    for value, maximum in ((max_seconds, 7200 if len(budget_selection) == 1 else 36000),
                           (max_case_seconds, 7200), (settle_seconds, 1800), (poll_seconds, 30)):
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= maximum:
            raise EvaluationError('Finite positive bounded evaluation times are required')
    if type(max_backend_requests) is not int or not 0 < max_backend_requests <= 100000:
        raise EvaluationError('A bounded backend HTTP request ceiling is required')
    if user_email is not None and (len(selection) != 1 or user_email.casefold() != CASE_EMAILS[selection[0]]):
        raise EvaluationError('A shared or conflicting UI-account override is forbidden for fixed case owners')
    api_base, web_base = base_url(api_base), base_url(web_base)
    originals = case_plans_for_run(run_id)
    cases = {key: {**originals[key], 'owner_id': None, 'conversation_id': None, 'project_id': None,
        'user_email': CASE_EMAILS[key], 'ui_url': None} for key in selection}
    return {'schema_version': 'memoir-subscription-evaluation-plan/2',
        'evaluation_profile': 'subscription_fifty', 'storage_backend': 'remote_supabase',
        'run_id': run_id, 'source_revision': source_revision,
        'local_checkout_source': local_checkout_snapshot(source_revision),
        'case_ids': list(cases), 'cases': cases, 'rounds_per_case': 50,
        'checkpoints': list(CHECKPOINTS), 'dataset_sha256': DATASET_SHA256,
        'user_email': None, 'case_user_emails': {key: CASE_EMAILS[key] for key in cases}, 'api_base': api_base, 'web_base': web_base,
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
        self.submission_deadline = self.deadline
        self.revalidation_deadline = None
        self.read_only = False
        self.reserved = 0
        self.on_reserve = None

    def remaining(self):
        return min(self.deadline, self.case_deadline) - time.monotonic()

    async def json(self, method, url, **kwargs):
        remaining = self.remaining()
        if remaining <= 0 or self.reserved >= self.maximum:
            raise EvaluationError('Backend request or elapsed-time ceiling reached')
        self.reserved += 1
        if self.on_reserve is not None:
            self.on_reserve(self.reserved)
        timeout = min(kwargs.pop('timeout', 30), remaining)
        started = time.monotonic()
        response = None
        error_code = None
        try:
            response = await self.client.request(method, url, timeout=timeout, **kwargs)
            response.raise_for_status()
            if self.remaining()<=0:
                raise EvaluationError('Backend request completed after its admission deadline')
            return response.json()
        except httpx.HTTPStatusError as error:
            reason = 'HTTP request failed with status ' + str(error.response.status_code)
            failure_type = 'HTTPStatusError'
            if urlsplit(url).path == '/rest/v1/rpc/resolve_lifetime_conversation':
                try:
                    database_error = error.response.json()
                except ValueError:
                    database_error = None
                if (isinstance(database_error, dict) and database_error.get('code') == '55000'
                        and database_error.get('message') == 'LIFETIME_REALTIME_CLEARANCE_REQUIRED'):
                    error_code = 'LIFETIME_REALTIME_CLEARANCE_REQUIRED'
                    reason = ('Development database requires the canonical-only conversation migration; '
                              'run make migrate before retrying')
        except httpx.RequestError as error:
            failure_type = type(error).__name__
            reason = 'HTTP request failed (' + failure_type + ')'
        except EvaluationError:
            raise
        except ValueError:
            failure_type = 'invalid_json'
            reason = 'HTTP response was not valid JSON'
        # Only this exact public gate code may supplement transport metadata.
        # Other bodies, exception text and query strings remain private.
        diagnostic = {
            'failure_type': failure_type, 'method': method, 'path': urlsplit(url).path,
            'http_status': response.status_code if response is not None else None,
            'elapsed_ms': max(0, round((time.monotonic() - started) * 1000)),
        }
        if error_code is not None:
            diagnostic['error_code'] = error_code
        raise EvaluationError(reason, diagnostic=diagnostic) from None


@dataclass
class SupabaseAccount:
    requests: Requests
    url: str
    public_key: str = field(repr=False)
    secret_key: str = field(repr=False)
    user: dict | None = field(default=None, repr=False)
    access_token: str | None = field(default=None, repr=False)
    refresh_token: str | None = field(default=None, repr=False)
    verified_owner: str | None = field(default=None, repr=False)
    expires_at: float = 0

    def admin_headers(self):
        return {'apikey': self.secret_key, 'Authorization': 'Bearer ' + self.secret_key}

    async def auth(self, method, path, *, admin=False, **kwargs):
        return await self.requests.json(method, self.url + '/auth/v1' + path,
            headers=self.admin_headers() if admin else {'apikey': self.public_key}, **kwargs)

    async def ensure_user(self, email, *, create_confirm=False, allow_create=True):
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
            if not create_confirm or not allow_create:
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
        self.user = {'id': owner, 'email': email.casefold(), 'email_confirmed_at': verified['email_confirmed_at'], 'is_anonymous': False}
        self.verified_owner = owner
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
        owner = self.verified_owner or (self.user or {}).get('id')
        if (not owner or not self.user or self.user.get('id') != owner or value.get('user', {}).get('id') != owner
                or not isinstance(value.get('access_token'), str) or not value['access_token']
                or not isinstance(value.get('refresh_token'), str) or not value['refresh_token']):
            raise EvaluationError('Authenticated session did not match the intended UI owner')
        observed = await self.requests.json('GET', self.url + '/auth/v1/user',
            headers={'apikey': self.public_key, 'Authorization':'Bearer ' + value['access_token']})
        if (not isinstance(observed, dict) or observed.get('id') != owner
                or str(observed.get('email', '')).casefold() != self.user['email'] or observed.get('is_anonymous')):
            raise EvaluationError('Authenticated token subject did not match its case owner')
        expires = value.get('expires_in', 3600)
        if type(expires) not in (int,float) or not math.isfinite(expires) or expires <= 0:
            raise EvaluationError('Authenticated session expiry is invalid')
        self.access_token, self.refresh_token = value['access_token'], value['refresh_token']
        self.expires_at = time.monotonic() + max(1, expires - 60)

    def assert_owner(self, binding):
        if (not self.user or self.user.get('id') != self.verified_owner or self.verified_owner != binding['owner_id']
                or self.user.get('email') != binding['user_email'] or not self.access_token):
            raise EvaluationError('Case session owner differs from the verified binding')

    def close(self):
        self.access_token = self.refresh_token = None
        self.secret_key = ''
        self.expires_at = 0

    async def headers(self):
        if not self.user or self.user.get('id') != self.verified_owner or not self.access_token:
            raise EvaluationError('A verified case session is required')
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
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, 'w') as stream:
            stream.write('<!doctype html><meta charset="utf-8"><meta name="referrer" content="no-referrer">'
                '<title>Memoir test sign-in</title><p>Private, expiring, one-time sign-in link.</p>'
                '<a href="' + html.escape(generated['action_link'], quote=True) + '">Sign in to Memoir</a>')
        return path


async def backend(requests, account, plan, method, path, **kwargs):
    if requests.read_only and method!='GET':
        raise EvaluationError('Read-only completed-case verification cannot mutate or submit another turn')
    return await requests.json(method, plan['api_base'] + memoir_url(path),
        headers=await account.headers(), **kwargs)


async def preflight(account, plan, *, needed_rounds=50):
    requests = account.requests
    config = await backend(requests, account, plan, 'GET', '/v1/agent/config')
    if (config.get('auth_mode') != 'supabase' or base_url(config.get('supabase_url', '')) != account.url
            or config.get('private_draft_cadence') != 5):
        raise EvaluationError('Backend must use the configured remote Supabase with five-round draft cadence')
    state = await backend(requests, account, plan, 'GET', '/v1/story/state')
    if state.get('user_id') != account.user['id'] or state.get('is_anonymous'):
        raise EvaluationError('Backend authenticated owner did not match')
    recall = state.get('recall_status') or {}
    if type(needed_rounds) is not int or not 0 <= needed_rounds <= 50:
        raise EvaluationError('Verified remaining original rounds are required')
    if needed_rounds and not recall.get('paid') and recall.get('free_rounds', 0) - recall.get('rounds_completed', 0) < needed_rounds:
        raise EvaluationError('Account allowance is too small; enable EVAL_START_BACKEND=1 for the scoped local test allowance')
    return {'family_features_enabled': state.get('family_features_enabled', False),
            'recall_status': recall, 'backend_auth_mode': config['auth_mode']}


async def canonical_binding(account, plan, case_id, previous=None):
    identity = await account.rpc('read_lifetime_project_identity', p_project_id=None)
    if identity is None:
        if previous is not None:
            raise EvaluationError('Saved canonical identity is unavailable; resume cannot allocate another project')
        resolved = await account.rpc('resolve_lifetime_conversation', p_project_id=None)
        if not isinstance(resolved, dict) or resolved.get('outcome') != 'resolved':
            raise EvaluationError('Canonical mapping/authority requires explicit resolution; no legacy fallback')
        identity = await account.rpc('read_lifetime_project_identity', p_project_id=None)
    if (not isinstance(identity, dict) or identity.get('owner_id') != account.verified_owner
            or identity.get('product') != 'memoir' or str(UUID(identity['conversation_id'])) != identity['conversation_id']
            or not isinstance(identity.get('project_id'), str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', identity['project_id'])):
        raise EvaluationError('Server-issued canonical identity does not match the case account')
    binding = {**plan['cases'][case_id], 'owner_id': account.verified_owner,
        'project_id': identity['project_id'], 'conversation_id': identity['conversation_id']}
    if previous is not None and any(previous.get(key) != binding[key] for key in ('user_email','owner_id','project_id','conversation_id')):
        raise EvaluationError('Retry/resume owner or canonical project changed; no account reassignment')
    binding['ui_url'] = plan['web_base'] + '/memoir/interview/' + binding['project_id']
    return binding


async def bind_accounts(requests, plan, settings, accounts, *, create_confirm, previous=None, origins=None, read_only_cases=()):
    validate_case_bindings(plan)
    owners = {account.verified_owner for case,account in accounts.items() if case not in plan['case_ids']}
    for case_id in plan['case_ids']:
        if case_id in read_only_cases:set_case_deadline(requests,plan,None,read_only=True)
        else:set_case_deadline(requests,plan,(origins or {}).get(case_id))
        account = SupabaseAccount(requests, base_url(settings.get('SUPABASE_URL','')),
            settings['SUPABASE_PUBLISHABLE_KEY'], settings.get('SUPABASE_SECRET_KEY') or settings['SUPABASE_SERVICE_ROLE_KEY'])
        accounts[case_id] = account
        owner = await account.ensure_user(CASE_EMAILS[case_id], create_confirm=create_confirm and case_id not in read_only_cases, allow_create=False)
        if owner in owners:
            raise EvaluationError('Distinct cases resolved to the same Auth owner; no conversation may start')
        owners.add(owner)
    for case_id in plan['case_ids']:
        account=accounts[case_id]
        if case_id in read_only_cases:set_case_deadline(requests,plan,None,read_only=True)
        else:set_case_deadline(requests,plan,(origins or {}).get(case_id))
        await account.sign_in()
        plan['cases'][case_id] = await canonical_binding(account, plan, case_id,
            (previous or {}).get('cases', {}).get(case_id) if previous else None)
    validate_case_bindings(plan, bound=True)


def readback_shape(view, binding):
    if (not isinstance(view, dict) or view.get('project_id') != binding['project_id']
            or not isinstance(view.get('sources'), list) or type(view.get('completed_rounds')) is not int
            or not isinstance(view.get('processing'), dict)
            or any(type(view['processing'].get(key)) is not int for key in ('extracted_through','pending_inputs'))):
        raise EvaluationError('Canonical source/checkpoint readback interface is unavailable; no unverified turn may start')


def checkpoint_head_shape(head,binding):
    if (not isinstance(head,dict) or any(head.get(key)!=binding[key] for key in ('owner_id','conversation_id','project_id'))
            or head.get('locale')!=binding['language'] or head.get('status') not in {'pending','ready','insufficient_context'}):
        raise EvaluationError('Bounded canonical checkpoint identity/readback interface is unavailable')


def validate_checkpoint(head,pages,binding,ordinal,accepted):
    checkpoint_head_shape(head,binding)
    if (head.get('status')!='ready' or head.get('snapshot_state')!='completed'
            or head.get('approval_required') is not False or head.get('retrieval_complete') is not True
            or head.get('updating') is not False or head.get('error') is not None
            or head.get('coverage_round')!=ordinal or type(head.get('revision')) is not int or head['revision']<=0
            or any(type(head.get(key)) is not int or head[key]<0 for key in
                ('source_revision','current_source_revision','event_revision','current_event_revision','policy_epoch'))
            or head.get('source_revision')!=head.get('current_source_revision')
            or head.get('event_revision')!=head.get('current_event_revision')
            or not isinstance(head.get('root_digest'),str) or not re.fullmatch('[a-f0-9]{64}',head['root_digest'])
            or str(UUID(head['snapshot_id']))!=head['snapshot_id'] or not pages):
        raise EvaluationError('Canonical checkpoint is incomplete, stale or requires human approval')
    seen,records=set(),[]
    for index,page in enumerate(pages):
        if (not isinstance(page,dict) or any(page.get(key)!=head.get(key) for key in
                ('owner_id','conversation_id','project_id','snapshot_id','root_digest','locale','source_revision','event_revision','policy_epoch','snapshot_state'))
                or page.get('snapshot_complete') is not True or page.get('approval_required') is not False
                or page.get('complete') is not (index==len(pages)-1) or not isinstance(page.get('records'),list)):
            raise EvaluationError('Canonical checkpoint page differs from its owned frozen snapshot')
        for record in page['records']:
            preview=record.get('preview') or {}
            refs=record.get('source_refs')
            if (not isinstance(record.get('id'),str) or record['id'] in seen or record.get('approval_required') is not False
                    or record.get('original_withheld') is not False or preview.get('locale')!=binding['language']
                    or not isinstance(preview.get('text'),str) or not preview['text'].strip()
                    or not isinstance(refs,list) or not refs
                    or any(ref.get('source_id') not in accepted or ref.get('version')!=1 for ref in refs)):
                raise EvaluationError('Canonical draft record provenance differs from the case sources')
            seen.add(record['id']);records.append(record)
    if not records:
        raise EvaluationError('Canonical checkpoint has no retrieved draft records')


async def saved_canonical_checkpoint(account,binding,ordinal,accepted):
    head=await account.rpc('read_lifetime_private_draft_head',p_project_id=binding['project_id'],p_locale=binding['language'])
    checkpoint_head_shape(head,binding)
    if head.get('snapshot_state')=='proposed' or head.get('error')=='LIFETIME_LEGACY_MANUSCRIPT_MIGRATION_REQUIRED':
        raise EvaluationError('Canonical checkpoint requires human policy/migration review')
    if head['status']!='ready' or head.get('coverage_round')!=ordinal or head.get('updating'):
        return None
    pages,cursor,seen=[],None,set()
    for _ in range(128):
        page=await account.rpc('read_lifetime_private_draft_page',p_project_id=binding['project_id'],
            p_snapshot_id=head['snapshot_id'],p_after=cursor,p_limit=8)
        if not isinstance(page,dict):
            raise EvaluationError('Canonical checkpoint page shape is invalid')
        pages.append(page)
        if page.get('complete') is True:break
        cursor=page.get('next_cursor')
        if not isinstance(cursor,str) or not cursor or cursor in seen:
            raise EvaluationError('Canonical checkpoint cursor is missing/repeated; no partial acceptance')
        seen.add(cursor)
    else:raise EvaluationError('Canonical checkpoint pagination bound reached; no partial acceptance')
    validate_checkpoint(head,pages,binding,ordinal,accepted)
    return {'milestone':ordinal,'draft':head,'pages':pages,'readback_protocol':'lifetime_private_draft_pages'}


async def start_case_backend(requests, account, plan, settings, backend_lock_fd, *, ledger, directory, receipt):
    publication_url = settings.get('MEMOIR_PUBLICATION_DATABASE_URL') or settings.get('SUPABASE_DB_URL')
    if not isinstance(publication_url, str) or not publication_url.strip():
        raise EvaluationError('Canonical evaluation requires a publication database connection in MEMOIR_PUBLICATION_DATABASE_URL or SUPABASE_DB_URL')
    if str(settings.get('MEMOIR_LIFETIME_GENERATION_PAUSED') or '0').lower() in {'1', 'true', 'yes'}:
        raise EvaluationError('Local canonical generation is paused; review MEMOIR_LIFETIME_GENERATION_PAUSED before running the evaluation')
    usage = await account.read('/rest/v1/user_recall_usage',
        params={'select':'rounds_completed','user_id':'eq.' + account.verified_owner,'limit':'1'})
    used = int(usage[0]['rounds_completed']) if usage else 0
    remaining=50-len(ledger['rounds'])
    if 'original_recall_round_limit' not in ledger:
        ledger['original_recall_round_limit']=used+remaining
        save(directory/'receipt.json',receipt)
    limit=ledger['original_recall_round_limit']
    if type(limit) is not int or limit<used:
        raise EvaluationError('Original case allowance is exhausted or invalid; no replacement allowance')
    environment = {**settings, 'MEMORY_SPARK_EVAL_RECALL_OWNER_ID': account.verified_owner,
        'MEMORY_SPARK_EVAL_RECALL_LIMIT':str(limit), 'SUPABASE_SECRET_KEY':account.secret_key,
        'MEMOIR_PUBLICATION_DATABASE_URL':publication_url,
        LOCK_FD_ENV:str(backend_lock_fd), 'MEMORY_SPARK_API_PORT':str(urlsplit(plan['api_base']).port or 80)}
    if urlsplit(plan['api_base']).hostname not in {'localhost','127.0.0.1'}:
        raise EvaluationError('Automatic backend startup requires a local API origin')
    result = await asyncio.to_thread(subprocess.run, ['make','--no-print-directory','memoir-live-fifty-backend'],
        cwd=ROOT, env={key:str(value) for key,value in environment.items() if value is not None},
        pass_fds=(backend_lock_fd,), stdout=sys.stderr, stderr=sys.stderr, timeout=min(180,requests.remaining()))
    if result.returncode:
        raise EvaluationError('Backend startup failed; see the backend output')
    await wait_for_backend(requests,plan)


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


async def verified_case_ledger(account, plan, directory, receipt, case_id):
    binding=plan['cases'][case_id]
    account.assert_owner(binding)
    project=binding['project_id']
    case = next((item for item in receipt['evaluation']['cases'] if item['case_id'] == case_id), None)
    if case is None:
        case = {'case_id':case_id, 'user_email':binding['user_email'], 'project_id':project,
            'conversation_id':binding['conversation_id'], 'owner_id':binding['owner_id'],
            'ui_url':binding['ui_url'], 'status':'running','rounds':[],'checkpoints':[]}
        receipt['evaluation']['cases'].append(case)
    if any(case.get(key) != binding[key] for key in ('user_email','owner_id','conversation_id','project_id')):
        raise EvaluationError('Saved case evidence belongs to a different owner or canonical project')
    save(directory / 'receipt.json',receipt)
    initial = await account.rpc('read_user_memory_events',p_project_id=project)
    readback_shape(initial,binding)
    inputs = FiftyReadback(case_id=case_id, run_id=plan['run_id'],project_id=project,
        source_revision=plan['source_revision']).driver_inputs()
    if not case['rounds'] and (initial['sources'] or initial['completed_rounds'] or initial.get('events')):
        raise EvaluationError('Canonical history already exists; use its saved resume receipt, never allocate a replacement project')
    client_ids = set()
    for index,record in enumerate(case['rounds'],1):
        if record.get('round') != index or str(UUID(record['client_turn_id'])) != record['client_turn_id'] or record['client_turn_id'] in client_ids:
            raise EvaluationError('Saved original round/client identity is invalid')
        client_ids.add(record['client_turn_id'])
        if not record.get('accepted_source_id'):
            recovered = await account.rpc('read_lifetime_reply',p_conversation_id=binding['conversation_id'],p_client_turn_id=record['client_turn_id'])
            if (not isinstance(recovered,dict) or recovered.get('project_id') != project
                    or recovered.get('client_turn_id') != record['client_turn_id'] or not recovered.get('conversation_saved')
                    or recovered.get('context_rebuild_required') or not recovered.get('accepted_source_id')
                    or not isinstance(recovered.get('reply'),str) or not recovered['reply'].strip()):
                raise EvaluationError('Prior submission cannot be safely recovered; no original input will be resubmitted')
            record.update(status='delivered',accepted_source_id=recovered['accepted_source_id'],reply=recovered['reply'])
    if case['rounds']:
        accepted_ids = [record['accepted_source_id'] for record in case['rounds']]
        if len(initial['sources']) != len(accepted_ids):
            raise EvaluationError('Saved receipt/source history differs; preserve it without replay')
        for index,source in enumerate(initial['sources']):
            if (source.get('id') != accepted_ids[index] or source.get('project_id') != project
                    or source.get('text') != inputs['rounds'][index] or source.get('language') != binding['language']
                    or source.get('kind') != 'narrator_chat' or source.get('status') != 'active' or source.get('version') != 1):
                raise EvaluationError('Saved source evidence is foreign, changed or outside the original case')
        for checkpoint in case['checkpoints']:
            if checkpoint.get('milestone') not in CHECKPOINTS:
                raise EvaluationError('Saved checkpoint ordinal is invalid')
            if checkpoint.get('readback_protocol')!='lifetime_private_draft_pages':
                raise EvaluationError('Resume requires original canonical checkpoint evidence')
            validate_checkpoint(checkpoint['draft'],checkpoint['pages'],binding,checkpoint['milestone'],accepted_ids[:checkpoint['milestone']])
    save(directory/'receipt.json',receipt)
    return case,inputs,initial


async def run_cases(accounts, plan, directory, receipt):
    for case_id, binding in plan['cases'].items():
        account=accounts[case_id]
        requests=account.requests
        project=binding['project_id']
        case,inputs,initial=await verified_case_ledger(account,plan,directory,receipt,case_id)
        accepted = []
        for ordinal, text in enumerate(inputs['rounds'], 1):
            account.assert_owner(binding)
            if ordinal <= len(case['rounds']):
                record = case['rounds'][ordinal-1]
                accepted.append(record['accepted_source_id'])
                if record['status'] == 'completed':
                    continue
            else:
                record = {'round':ordinal,'client_turn_id':str(uuid4()),'status':'submitting','background_settled':False}
                case['rounds'].append(record)
                receipt['backend_turn_submissions'] += 1
                save(directory / 'receipt.json',receipt)
                # Exactly one original POST; resume recovers by this same UUID.
                result = await backend(requests,account,plan,'POST','/v1/agent/turn',timeout=600,
                    json={'project_id':project,'language':binding['language'],'text':text,'conversation_text':text,
                        'source_kind':'narrator_chat','client_turn_id':record['client_turn_id']})
                if (result.get('project_id') != project or not result.get('accepted_source_id')
                        or not isinstance(result.get('reply'),str) or not result['reply'].strip()
                        or result.get('cached') or result.get('task_errors')):
                    raise EvaluationError('Original conversation was not freshly delivered and saved')
                record.update(status='delivered',accepted_source_id=result['accepted_source_id'],reply=result['reply'])
                accepted.append(result['accepted_source_id'])
                save(directory / 'receipt.json',receipt)
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
                        checkpoint=await saved_canonical_checkpoint(account,binding,ordinal,accepted)
                        if checkpoint is None:
                            await asyncio.sleep(min(plan['poll_seconds'],max(0,settle_deadline-time.monotonic())))
                            continue
                        case['checkpoints']=[item for item in case['checkpoints'] if item['milestone']!=ordinal]
                        case['checkpoints'].append(checkpoint)
                    break
                draft = await account.rpc('read_user_memoir_draft',
                    p_project_id=project, p_locale=binding['language'], p_cadence=5)
                if _extraction_error_is_terminal(draft):
                    raise EvaluationError('Background extraction failed; explicit review is required')
                await asyncio.sleep(min(plan['poll_seconds'], max(0, settle_deadline - time.monotonic())))
            if record.get('failure_summary'):
                record['previous_failure_summary']=record.pop('failure_summary')
            record.update(status='completed', background_settled=True, canonical_state=view)
            save(directory / 'receipt.json', receipt)
            print(f'{case_id}: round {ordinal}/50 saved', file=sys.stderr, flush=True)
        final_view=await account.rpc('read_user_memory_events',p_project_id=project)
        _canonical_state(final_view,inputs,accepted)
        if sorted(item['milestone'] for item in case['checkpoints']) != list(CHECKPOINTS):
            raise EvaluationError('Saved case checkpoints are incomplete; no completed status may be reused')
        current=await saved_canonical_checkpoint(account,binding,50,accepted)
        if current is None:
            raise EvaluationError('Current canonical private draft is pending or updating; saved checkpoints cannot establish current acceptance')
        final_view=await account.rpc('read_user_memory_events',p_project_id=project)
        _canonical_state(final_view,inputs,accepted)
        head=await account.rpc('read_lifetime_private_draft_head',p_project_id=project,p_locale=binding['language'])
        validate_checkpoint(head,current['pages'],binding,50,accepted)
        if any(head.get(key)!=current['draft'].get(key) for key in
                ('snapshot_id','root_digest','revision','source_revision','event_revision','policy_epoch','coverage_round')):
            raise EvaluationError('Current canonical draft changed during final retrieval; no stale completion may be reused')
        case['current_checkpoint']={**current,'validated_at_unix':time.time()}
        # Exercise the same authenticated recovery route the UI uses.
        shell = await backend(requests, account, plan, 'GET', '/v1/projects/' + project)
        if (shell.get('id') != project or shell.get('owner_id') != binding['owner_id']
                or not shell.get('requires_supabase_auth')):
            raise EvaluationError('Normal UI project recovery did not match the retained project')
        case.update(status='completed', ui_recovery_verified=True, evidence_validated=True, validation_attempt_id=receipt['attempt_id'])
        case.pop('validation_failure',None)
        save(directory / 'receipt.json', receipt)


def private_json(path):
    descriptor = os.open(path,os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor) as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
            raise EvaluationError('Resume evidence must be owned private0600 regular files')
        value = json.load(stream)
    if not isinstance(value,dict):
        raise EvaluationError('Resume evidence shape is invalid')
    return value


def load_resume(directory):
    directory = Path(directory).absolute()
    if directory.is_symlink() or not directory.is_dir() or directory == ROOT or ROOT in directory.parents:
        raise EvaluationError('Resume requires an existing private directory outside the checkout')
    info = directory.stat()
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise EvaluationError('Resume directory must be owned private0700')
    plan,receipt = private_json(directory/'plan.json'),private_json(directory/'receipt.json')
    validate_case_bindings(plan,bound=True)
    if (plan.get('schema_version') != 'memoir-subscription-evaluation-plan/2'
            or receipt.get('schema_version') != 'memoir-supabase-evaluation-receipt/2'
            or receipt.get('run_id') != plan.get('run_id') or plan.get('dataset_sha256') != DATASET_SHA256):
        raise EvaluationError('Resume requires matching per-owner current-schema evidence')
    recorded = receipt.get('evaluation',{}).get('cases')
    if not isinstance(recorded,list) or len({item['case_id'] for item in recorded}) != len(recorded):
        raise EvaluationError('Resume case evidence is duplicated or invalid')
    for item in recorded:
        binding = plan['cases'].get(item['case_id'])
        if binding is None or any(item.get(key) != binding[key] for key in ('owner_id','project_id','conversation_id','user_email')):
            raise EvaluationError('Resume evidence crosses a case/account/project boundary')
    return plan,receipt


def budget_contract(plan):
    return {key:plan[key] for key in BUDGET_FIELDS}


def validate_request_counter(plan,receipt,count):
    previous=receipt.get('request_accounting',{}).get('backend_http_requests_reserved',0)
    if (type(previous) is not int or not 0 <= previous <= plan['max_backend_requests']
            or count.get('run_id')!=plan['run_id'] or type(count.get('reserved')) is not int
            or not previous <= count['reserved'] <= plan['max_backend_requests']):
        raise EvaluationError('Resume backend request counter is invalid')


def completed_submission_ledger(case):
    rounds=case.get('rounds') if isinstance(case,dict) else None
    if not isinstance(rounds,list) or len(rounds)!=50:return False
    return all(record.get('round')==ordinal and record.get('status')=='completed'
        and record.get('background_settled') is True and isinstance(record.get('accepted_source_id'),str)
        and record['accepted_source_id'] for ordinal,record in enumerate(rounds,1))


def begin_read_only_revalidation(requests,receipt,case_ids):
    requests.revalidation_deadline=time.monotonic()+READ_ONLY_REVALIDATION_SECONDS
    receipt.setdefault('read_only_revalidation',[]).append({'attempt_id':receipt['attempt_id'],
        'case_ids':list(case_ids),'started_at_unix':time.time(),'max_elapsed_seconds':READ_ONLY_REVALIDATION_SECONDS,
        'reserved_at_start':requests.reserved,'submission_deadlines_reset':False})


def set_case_deadline(requests,plan,origin,*,read_only=False):
    requests.read_only=read_only
    if read_only:
        if requests.revalidation_deadline is None:
            raise EvaluationError('A bounded read-only revalidation phase is required')
        requests.deadline=requests.case_deadline=requests.revalidation_deadline
    else:
        requests.deadline=requests.submission_deadline
        requests.case_deadline=requests.deadline if origin is None else min(requests.deadline,
            time.monotonic()+max(0,plan['max_case_elapsed_seconds']-(time.time()-origin)))


def validate_resume_budget(plan,previous,receipt):
    original=receipt.get('budget_contract')
    if not isinstance(original,dict) or original!=budget_contract(previous) or budget_contract(plan)!=original:
        raise EvaluationError('Resume must retain all original immutable budget values')
    started=receipt.get('started_at_unix')
    origins=receipt.get('case_started_at_unix')
    now=time.time()
    if type(started) not in (int,float) or not math.isfinite(started) or started>now:
        raise EvaluationError('Resume elapsed-time origin is invalid')
    if not isinstance(origins,dict) or any(case not in previous['cases'] or type(origin) not in (int,float)
            or not math.isfinite(origin) or not started<=origin<=now for case,origin in origins.items()):
        raise EvaluationError('Resume case elapsed-time origins are invalid')
    if any(item.get('rounds') and item['case_id'] not in origins for item in receipt['evaluation']['cases']):
        raise EvaluationError('Saved case progress has no original elapsed-time origin')


async def execute(plan,directory,settings,*,start_backend=False,create_confirm=False,resume=None):
    with backend_operation_lock() as descriptor:
        return await _execute(plan,directory,settings,start_backend=start_backend,
            create_confirm=create_confirm,backend_lock_fd=descriptor,resume=resume)


async def _execute(plan,directory,settings,*,start_backend,create_confirm,backend_lock_fd,resume=None):
    previous = None
    if resume is None:
        directory = output_directory(directory)
        receipt = {'schema_version':'memoir-supabase-evaluation-receipt/2','run_id':plan['run_id'],
            'source_revision':plan['source_revision'],'local_checkout_source':plan['local_checkout_source'],'started_at_unix':time.time(),
            'budget_contract':budget_contract(plan),'case_started_at_unix':{},
            'status':'incomplete','storage_backend':'remote_supabase','data_retained':True,
            'browser_started':False,'local_postgres_started':False,'execution_started':False,
            'backend_turn_submissions':0,'semantic_acceptance':'human_review_required',
            'actual_upstream_provider_requests':None,'evaluation':{'status':'running','cases':[]}}
    else:
        directory = Path(directory).absolute()
        previous,receipt = load_resume(directory)
        if any(plan.get(key) != previous.get(key) for key in ('run_id','source_revision','local_checkout_source','dataset_sha256','api_base','web_base')):
            raise EvaluationError('Resume must retain its run/source/service identities')
        if any(case not in previous['cases'] for case in plan['case_ids']):
            raise EvaluationError('Resume cannot add or reassign an original case')
        validate_resume_budget(plan,previous,receipt)
        validate_request_counter(plan,receipt,private_json(directory/'request-counter.json'))
        if receipt.get('stop_reason'):
            receipt.setdefault('previous_failures',[]).append({'reason':receipt.pop('stop_reason'),'summary':receipt['evaluation'].get('failure_summary')})
        receipt['evaluation'].pop('failure_summary',None)
        receipt['evaluation'].pop('failure_stage',None)
        receipt['status'] = receipt['evaluation']['status'] = 'running'
    receipt['attempt_id']=str(uuid4())
    receipt['selected_case_status']='incomplete'
    for case in receipt['evaluation']['cases']:
        if case['case_id'] in plan['case_ids']:
            case.update(status='incomplete',evidence_validated=False)
            if case.get('current_checkpoint'):case['previous_current_checkpoint']=case.pop('current_checkpoint')
    if previous is None:
        save(directory/'plan.json',plan)
    save(directory/'receipt.json',receipt)
    recorded={case['case_id']:case for case in receipt['evaluation']['cases']}
    read_only_cases={case for case in plan['case_ids'] if completed_submission_ledger(recorded.get(case))}
    stage,accounts,current_case = 'authentication',{},None
    async with httpx.AsyncClient(follow_redirects=False,trust_env=False) as client:
        requests = Requests(client,plan['max_backend_requests'],plan['max_elapsed_seconds'])
        counter_path=directory/'request-counter.json'
        count=private_json(counter_path) if previous is not None else {'run_id':plan['run_id'],'reserved':0}
        validate_request_counter(plan,receipt,count)
        requests.reserved=count['reserved']
        started=receipt.get('started_at_unix')
        if type(started) not in (int,float) or not math.isfinite(started) or started>time.time():
            raise EvaluationError('Resume elapsed-time origin is invalid')
        requests.submission_deadline=time.monotonic()+max(0,plan['max_elapsed_seconds']-(time.time()-started))
        requests.deadline=requests.case_deadline=requests.submission_deadline
        def reserved(count):
            receipt['request_accounting']={'backend_http_requests_reserved':count,'actual_upstream_provider_requests':None,'model_request_ceiling_verified':False}
            save(counter_path,{'run_id':plan['run_id'],'reserved':count})
        requests.on_reserve = reserved
        reserved(requests.reserved)
        try:
            verify_execution_source(plan['source_revision'],plan['local_checkout_source'])
            if requests.remaining()<=0 and any(case not in read_only_cases for case in plan['case_ids']):
                raise EvaluationError('Original campaign elapsed-time ceiling reached')
            for case_id in plan['case_ids']:
                origin=receipt['case_started_at_unix'].get(case_id)
                if case_id not in read_only_cases and origin is not None and time.time()-origin>=plan['max_case_elapsed_seconds']:
                    current_case=case_id
                    raise EvaluationError('Original case elapsed-time ceiling reached')
            if read_only_cases:begin_read_only_revalidation(requests,receipt,read_only_cases)
            await bind_accounts(requests,plan,settings,accounts,create_confirm=create_confirm,previous=previous,origins=receipt['case_started_at_unix'],read_only_cases=read_only_cases)
            stored_plan = plan if previous is None else {**previous,'cases':{**previous['cases'],**plan['cases']},'last_resume_selection':plan['case_ids']}
            save(directory/'plan.json',stored_plan)
            receipt.setdefault('preflight',{})
            for case_id in plan['case_ids']:
                current_case=case_id
                account,binding = accounts[case_id],plan['cases'][case_id]
                receipt['case_started_at_unix'].setdefault(case_id,time.time())
                save(directory/'receipt.json',receipt)
                if case_id in read_only_cases:set_case_deadline(requests,plan,None,read_only=True)
                else:set_case_deadline(requests,plan,receipt['case_started_at_unix'][case_id])
                single = {**plan,'case_ids':[case_id],'cases':{case_id:binding}}
                stage = 'canonical_ledger'
                ledger,_,_=await verified_case_ledger(account,single,directory,receipt,case_id)
                needed_rounds=50-len(ledger['rounds'])
                stage = 'backend_startup'
                if start_backend and case_id not in read_only_cases:
                    await start_case_backend(requests,account,single,settings,backend_lock_fd,ledger=ledger,directory=directory,receipt=receipt)
                stage = 'backend_preflight'
                receipt['preflight'][case_id] = await preflight(account,single,needed_rounds=needed_rounds)
                if case_id in read_only_cases:
                    shell=await backend(requests,account,single,'GET','/v1/projects/'+binding['project_id'])
                else:
                    shell = await backend(requests,account,single,'POST','/v1/projects',
                        json={'mode':'self','restore_project_id':binding['project_id'],'language':binding['language']})
                if (shell.get('id') != binding['project_id'] or shell.get('owner_id') != binding['owner_id']
                        or not shell.get('requires_supabase_auth')):
                    raise EvaluationError('Authenticated canonical project adapter binding differs')
                probe = await account.rpc('read_user_memory_events',p_project_id=binding['project_id'])
                readback_shape(probe,binding)
                checkpoint_head_shape(await account.rpc('read_lifetime_private_draft_head',p_project_id=binding['project_id'],p_locale=binding['language']),binding)
                stage = 'conversation'
                receipt['execution_started'] = True
                await run_cases(accounts,single,directory,receipt)
            receipt['selected_case_status'] = 'completed'
            all_cases = (previous or plan)['case_ids']
            recorded={case['case_id']:case for case in receipt['evaluation']['cases']}
            validated={case for case,item in recorded.items() if item.get('evidence_validated') is True
                and item.get('validation_attempt_id')==receipt['attempt_id']}
            missing=[case for case in all_cases if case not in validated]
            if missing and all(completed_submission_ledger(recorded.get(case)) for case in all_cases):
                # Only already completed ledgers enter this phase; it cannot submit or restore data.
                begin_read_only_revalidation(requests,receipt,missing)
                for case_id in missing:
                    current_case=case_id
                    case=recorded[case_id]
                    case.update(status='incomplete',evidence_validated=False)
                    if case.get('current_checkpoint'):
                        case['previous_current_checkpoint']=case.pop('current_checkpoint')
                    save(directory/'receipt.json',receipt)
                    single={**previous,'case_ids':[case_id],'cases':{case_id:previous['cases'][case_id]}}
                    stage='read_only_final_binding'
                    await bind_accounts(requests,single,settings,accounts,create_confirm=False,previous=previous,
                        origins=receipt['case_started_at_unix'],read_only_cases={case_id})
                    read_only_cases.add(case_id)
                    set_case_deadline(requests,plan,None,read_only=True)
                    stage='read_only_final_evidence'
                    await run_cases(accounts,single,directory,receipt)
            completed = {case['case_id'] for case in receipt['evaluation']['cases'] if case['status'] == 'completed'
                and case.get('evidence_validated') is True and case.get('validation_attempt_id')==receipt['attempt_id']}
            receipt['status'] = receipt['evaluation']['status'] = 'completed' if set(all_cases) <= completed else 'incomplete'
        except (Exception,asyncio.CancelledError) as error:
            receipt['status'] = receipt['evaluation']['status'] = 'incomplete'
            receipt['evaluation']['failure_stage'] = stage
            receipt['stop_reason'] = str(error) if isinstance(error,EvaluationError) else 'Backend evaluation failed; inspect retained evidence'
            summary = {'reason':receipt['stop_reason']}
            if isinstance(error,EvaluationError) and error.diagnostic:summary['http_failure']=error.diagnostic
            receipt['evaluation']['failure_summary']=summary
            case=next((item for item in receipt['evaluation']['cases'] if item['case_id']==current_case),None)
            if case:
                case.update(status='incomplete',evidence_validated=False,validation_failure=summary)
                if case['rounds'] and case['rounds'][-1]['status'] != 'completed':
                    case['rounds'][-1].update(status='incomplete',failure_summary=summary)
        finally:
            for case in receipt['evaluation']['cases']:
                account=accounts.get(case['case_id'])
                if case['case_id'] in read_only_cases or not account or not account.access_token or not case['rounds']:continue
                set_case_deadline(requests,plan,receipt['case_started_at_unix'].get(case['case_id']))
                if requests.remaining()<=0 or requests.reserved>=requests.maximum:continue
                try:
                    account.assert_owner(plan['cases'][case['case_id']])
                    login_dir=directory/'private-logins'/case['case_id']/str(uuid4())
                    for folder in (directory/'private-logins',directory/'private-logins'/case['case_id'],login_dir):
                        folder.mkdir(mode=0o700,exist_ok=True)
                    path=await account.login_file(login_dir,case['ui_url'])
                    case['ui_login_file']=str(path.relative_to(directory))
                except Exception:case.setdefault('ui_login_file',None)
            for account in accounts.values():account.close()
            receipt['request_accounting']={'backend_http_requests_reserved':requests.reserved,
                'actual_upstream_provider_requests':None,'model_request_ceiling_verified':False}
            try:
                verify_execution_source(plan['source_revision'],plan['local_checkout_source'])
                receipt['local_checkout_unchanged']=True
            except Exception:
                receipt['local_checkout_unchanged']=False
                receipt['status']=receipt['evaluation']['status']='incomplete'
                receipt['source_validation_error']='source_changed_during_run'
                receipt.setdefault('stop_reason','source_changed_during_run')
            save(directory/'receipt.json',receipt)
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
    parser.add_argument('--user-email')
    parser.add_argument('--case-id', choices=CASE_IDS, action='append')
    parser.add_argument('--resume-dir', type=Path)
    parser.add_argument('--project-id')
    parser.add_argument('--api-base', default='http://127.0.0.1:8010')
    parser.add_argument('--web-base', default='http://127.0.0.1:3010')
    parser.add_argument('--run-id', default=None)
    parser.add_argument('--run-dir', type=Path)
    parser.add_argument('--source-revision')
    parser.add_argument('--max-elapsed-seconds', type=float)
    parser.add_argument('--max-case-elapsed-seconds', type=float)
    parser.add_argument('--max-backend-requests', type=int)
    parser.add_argument('--settle-seconds', type=float)
    parser.add_argument('--poll-seconds', type=float)
    args = parser.parse_args(argv)
    try:
        run_id = args.run_id or str(uuid4())
        directory = args.run_dir or Path.home() / 'memoir-test-results' / run_id
        settings = configuration(args.env_file) if args.execute or args.prepare_user else {}
        email = args.user_email
        if args.prepare_user:
            email=email or os.getenv('MEMOIR_EVAL_USER_EMAIL')
            chosen = selected_cases(args.case_id) if args.case_id else [next((case for case,value in CASE_EMAILS.items() if value==email),CASE_IDS[0])]
            if len(chosen) != 1 or email is not None and email.casefold() != CASE_EMAILS[chosen[0]]:
                raise EvaluationError('UI login must select the mapped account for one case')
            email = CASE_EMAILS[chosen[0]]
        if args.prepare_user:
            if args.project_id and (len(args.project_id) > 128 or not all(c.isalnum() or c in '_-' for c in args.project_id)):
                raise EvaluationError('A valid project ID is required')
            result = asyncio.run(prepare_user(settings, email, directory,
                                             args.web_base, args.project_id))
            print(json.dumps(result))
            return 0
        if args.resume_dir:
            retained,saved_receipt = load_resume(args.resume_dir)
            if args.run_id and args.run_id != retained['run_id']:
                raise EvaluationError('Resume run UUID differs from saved evidence')
            run_id,directory = retained['run_id'],args.resume_dir
        revision = args.source_revision or subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
        selection=args.case_id or (retained['case_ids'] if args.resume_dir else None)
        original=retained if args.resume_dir else {}
        def limit(value,key,default):
            return value if value is not None else original.get(key,default)
        plan = build_plan(run_id=run_id, source_revision=revision, case_id=selection,
            api_base=args.api_base, web_base=args.web_base, user_email=email,
            max_seconds=limit(args.max_elapsed_seconds,'max_elapsed_seconds',7200 if len(selected_cases(selection))==1 else 36000),
            max_case_seconds=limit(args.max_case_elapsed_seconds,'max_case_elapsed_seconds',7200),
            max_backend_requests=limit(args.max_backend_requests,'max_backend_requests',20000 if len(selected_cases(selection))==1 else 100000),
            settle_seconds=limit(args.settle_seconds,'settle_seconds',600),poll_seconds=limit(args.poll_seconds,'poll_seconds',2),
            original_case_ids=original.get('case_ids'))
        if args.resume_dir:
            validate_resume_budget(plan,retained,saved_receipt)
        if not args.execute:
            print(json.dumps(plan, sort_keys=True))
            return 0
        print('Evidence directory: ' + str(directory), file=sys.stderr, flush=True)
        result = asyncio.run(execute(plan, directory, settings,
            start_backend=args.start_backend, create_confirm=args.create_confirmed_test_user,resume=args.resume_dir))
        print(json.dumps({'run_id': run_id, 'status': result['status'], 'receipt_path': str(directory / 'receipt.json'),
                         'stop_reason': result.get('stop_reason'), 'projects': plan['cases']}))
        return 0 if result['status'] == 'completed' else 3
    except (Exception, KeyboardInterrupt) as error:
        print(json.dumps({'status': 'blocked', 'reason': str(error) if isinstance(error, (EvaluationError, BackendInUseError))
                         else 'Remote evaluation configuration or preparation failed'}))
        return 3


if __name__ == '__main__':
    raise SystemExit(main())
