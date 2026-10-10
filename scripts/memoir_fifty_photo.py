"""Opt-in, isolated public-photo research for an issued fifty-round session.

Import is offline. Native admission uses an exact existing Python, no installs,
accounts, credentials, production storage, model calls or shared photo service.
Each admitted search owns a killable process group and an ephemeral PhotoPages.
Catalogue HTTPS reads have a separate durable cap; browser research is denied.
These public-read reservations are not model-gateway requests.
Browser receipt validation checks artifacts, never fabricates rendered evidence.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from contextlib import contextmanager
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
from urllib.parse import urlsplit, urlencode

ROOT = Path(__file__).resolve().parents[1]
MAX_SEARCH_SECONDS = 180
MAX_RESULT_BYTES = 2 * 1024 * 1024
MAX_PUBLIC_HTTP_REQUESTS = 128
_PUBLIC_HOSTS = frozenset({'commons.wikimedia.org', 'upload.wikimedia.org',
    'loc.gov', 'www.loc.gov', 'tile.loc.gov', 'cdn.loc.gov'})


class PhotoCleanupError(RuntimeError):
    """Owned public-research processes did not settle; stop the campaign."""

_ALLOWED_SETTINGS = {'GOOGLE_CSE_ID', 'GOOGLE_CSE_URL'}
_SCOPE_FIELDS = ('run_id', 'source_revision', 'case_id', 'project_id', 'round', 'input_sha256')


def _assert_session(session):
    from scripts.issue14_subscription_session import assert_owned_subscription_session
    assert_owned_subscription_session(session)
    if session.evaluation_profile != 'subscription_fifty':
        raise ValueError('Only an issued fifty-round session may own photo research')


def photo_intent(text, accepted_places):
    """Conservative public intent from current narration and accepted places only.

    Reuse the production current-message grounding/ambiguity rules. This is an
    evaluation action adapter, not a replacement for the application's UI policy.
    Unknown intent never inherits an older place, period or private photograph.
    """
    from apps.api.place_journey import grounded_place_journeys, validate_place_journey
    if type(text) is not str or type(accepted_places) is not list:
        return None
    hold = (r"\b(?:do not|don't|never)\s+(?:search|find|show|fetch)\b|"
        r"\b(?:private|personal photo|rights.unknown|no permission|not obtained|"
        r"not cleared|third.party|my friend (?:asks|said)|someone (?:asks|said))\b|"
        r"(?:[\"“”]|\b(?:he|she|they|my \w+|someone)\s+(?:asked|asks|says|said|told)\b)|"
        r"(?:不需要公共照片|不要.{0,16}(?:照片搜索|搜索照片|找照片)|私人|私密|未授权|没有公开使用授权)")
    if re.search(hold, text, re.I):
        return None
    public = bool(re.search(r'\bpublic\b|公共', text, re.I))
    visual = bool(re.search(r'\b(?:photo(?:graph)?s?|pictures?|images?|looks? like)\b|照片', text, re.I))
    request = bool(re.search(r'\b(?:show|find|search|could|may help|historical|reference)\b|请|如果', text, re.I))
    if not (public and visual and request):
        return None
    candidates = [value for raw in accepted_places if (value := validate_place_journey(raw))]
    places = grounded_place_journeys(candidates, text)
    if len(places) != 1:
        return None
    current = re.search(r'\b(?:now|today|current|present.day)\b|现在|当前|今天', text, re.I)
    year = re.search(r'(?<!\d)((?:18|19|20)\d{2})(?!\d)', text)
    chinese = re.search(r'[一二][〇零一二三四五六七八九]{3}(?=年)', text)
    period = ''
    if not current:
        if year:
            period = year.group(1)
        elif chinese:
            digits = {'〇': '0', '零': '0', **dict(zip('一二三四五六七八九', '123456789'))}
            period = ''.join(digits[char] for char in chinese.group())
        elif re.search(r'\bhistorical\b|老照片|历史', text, re.I):
            period = 'historical'
        else:
            return None
    place = places[0]
    return {'place': place['place'], 'period': period,
            **{key: place[key] for key in ('latitude', 'longitude') if key in place}}


def photo_process_environment(directory, existing_public_settings, playwright_browsers_path):
    """No inherited keys, proxy settings, shared service URLs or real home."""
    if type(existing_public_settings) is not dict or set(existing_public_settings) - _ALLOWED_SETTINGS:
        raise ValueError('Only existing keyless public source settings are supported')
    settings = {}
    for key, value in existing_public_settings.items():
        if type(value) is not str or len(value) > 2048 or any(ord(c) < 32 for c in value):
            raise ValueError('Invalid existing public source setting')
        if not value:
            continue
        if key == 'GOOGLE_CSE_ID' and not re.fullmatch(r'[A-Za-z0-9:_-]{1,120}', value):
            raise ValueError('Invalid existing public engine identifier')
        if key == 'GOOGLE_CSE_URL':
            parsed = urlsplit(value)
            if (parsed.scheme != 'https' or parsed.hostname != 'cse.google.com'
                    or parsed.username or parsed.password or parsed.port not in (None, 443)
                    or parsed.path != '/cse' or parsed.fragment
                    or not re.fullmatch(r'cx=[A-Za-z0-9%:_-]+', parsed.query)):
                raise ValueError('Invalid existing public search page')
        settings[key] = value
    env = {key: os.environ[key] for key in ('PATH', 'LANG', 'LC_ALL') if key in os.environ}
    env.update(HOME=str(directory), TMPDIR=str(directory), PYTHONPATH=str(ROOT),
        PYTHONDONTWRITEBYTECODE='1', PYTHONUNBUFFERED='1',
        MEMORY_SPARK_PHOTO_WEB_SEARCH='0', GOOGLE_CSE_ID='', GOOGLE_CSE_URL='')
    env.update(settings)
    # Kept as a compatibility input for the native owner. Catalogue-only mode
    # neither uses nor validates a browser installation; its absence is not a
    # reason to block approved Commons/LOC reads.
    return env


def _public_https(value):
    if type(value) is not str or len(value) > 8192:
        return False
    try:
        parsed = urlsplit(value)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
                or parsed.port not in (None, 443) or parsed.hostname == 'localhost'
                or parsed.hostname.endswith(('.localhost', '.local', '.internal'))):
            return False
        try:
            return ipaddress.ip_address(parsed.hostname).is_global
        except ValueError:
            return '.' in parsed.hostname
    except ValueError:
        return False


def photo_observation(body):
    result = {'status': 'unavailable', 'browser_status': 'not_run', 'items': [],
        'model_requests_started': 0, 'real_storage_writes': 0,
        'scope': 'isolated_public_reference_metadata'}
    if (type(body) is not dict or body.get('searching') is not False
            or body.get('status') not in {'READY', 'PARTIAL', 'NO_MATCH', 'UNAVAILABLE'}
            or type(body.get('items')) is not list or len(body['items']) > 150):
        return result
    result['result_status'] = body['status']
    result['searching'] = False
    for key in ('count', 'target_count', 'shortfall'):
        if type(body.get(key)) is int and body[key] >= 0:
            result[key] = body[key]
    result['failures'] = [dict(row) for row in body.get('failures', [])
        if type(row) is dict and set(row) == {'provider', 'reason'}
        and all(type(value) is str and re.fullmatch(r'[a-z0-9_]{1,64}', value) for value in row.values())][:20]
    if body['status'] == 'UNAVAILABLE' or body['status'] == 'NO_MATCH' and result['failures']:
        result['reason'] = 'public_sources_unavailable'
        return result
    items = []
    for item in body['items']:
        if (type(item) is not dict or not _public_https(item.get('source_url'))
                or not _public_https(item.get('image_url')) or type(item.get('license')) is not str
                or not item['license'] or type(item.get('allowed_actions')) is not dict
                or item['allowed_actions'].get('embed') is not True):
            return result
        allowed = ('asset_id', 'title', 'source_url', 'image_url', 'license', 'license_url',
            'date_expression', 'date_basis', 'attribution', 'scene_date_range', 'search_fallback',
            'requested_period', 'period_match', 'latitude', 'longitude')
        public = {key: deepcopy(item[key]) for key in allowed if key in item}
        # A reference receipt never confers print/publication/download permission.
        public['allowed_actions'] = {'embed': True, 'memory_reference': True,
                                    'download': False, 'print': False, 'publish': False}
        items.append(public)
    if body['status'] == 'NO_MATCH' and items:
        return result
    if body['status'] in {'READY', 'PARTIAL'} and not items:
        return result
    result.update(status='observed' if items else 'no_match', items=items,
                  source_count=len(items), terminal=True)
    return result


class FiftyPhotoResearch:
    """Owned subprocess adapter. A native owner must explicitly admit it."""
    def __init__(self):
        raise TypeError('Use explicit native-owner admission')

    @classmethod
    async def admit(cls, *, session, directory, python_binary, python_sha256,
                    existing_public_settings, playwright_browsers_path=None):
        _assert_session(session)
        binary, directory = Path(python_binary), Path(directory)
        if (not binary.is_absolute() or not binary.is_file() or not os.access(binary, os.X_OK)
                or hashlib.sha256(binary.read_bytes()).hexdigest() != python_sha256
                or directory.exists() or directory.is_symlink()
                or ROOT == directory.resolve() or ROOT in directory.resolve().parents):
            raise ValueError('Exact existing Python and fresh external photo directory required')
        env = photo_process_environment(directory, existing_public_settings, playwright_browsers_path)
        session.run.remaining_seconds()
        directory.mkdir(mode=0o700, parents=True)
        self = object.__new__(cls)
        self.session, self.directory, self.binary, self.env = session, directory, str(binary), env
        self.binary_sha256 = python_sha256
        self._waiter, self._cleanup_complete = None, True
        self.closed, self.process = False, None
        self._lock = asyncio.Lock()
        self._seen, self._counts, self._receipts = set(), {}, []
        self._http_reserved, self._http_cases = {}, {}
        self._http_uncertain = set()
        try:
            self.admission = await self._preflight()
        except BaseException:
            await self.close()
            raise
        return self

    async def _preflight(self):
        code = r"""
import importlib.metadata, json
result = {'status': 'unavailable', 'reason': 'photo_catalogue_dependencies_missing',
    'all_runtime_components_pinned': False, 'package_versions': {},
    'photo_browser_providers': 'not_admitted_uncounted_browser_network'}
try:
    result['package_versions'] = {name: importlib.metadata.version(name) for name in ('httpx', 'Pillow')}
    import apps.api.place_photo_pages, apps.api.place_photo_fingerprints
    result.update(status='ready', network_mode='counted_catalogues_only')
    result.pop('reason', None)
except Exception:
    pass
print(json.dumps(result))
"""
        try:
            result = await self._process([self.binary, '-c', code],
                timeout=min(10, self.session.run.remaining_seconds()), cwd=self.directory, env=self.env,
                capture=True)
            value = json.loads(result) if len(result) < 2048 else {}
            if value.get('status') == 'ready' and value.get('network_mode') == 'counted_catalogues_only':
                return value
            return {**value, 'status': 'unavailable', 'reason': value.get('reason', 'photo_browser_preflight_failed')}
        except PhotoCleanupError:
            raise
        except Exception:
            return {'status': 'unavailable', 'reason': 'photo_browser_preflight_failed'}

    async def observe_round(self, case_id, ordinal, runtime_result):
        _assert_session(self.session)
        if (self.closed or self.session._active != (case_id, ordinal)
                or (case_id, ordinal) in self._seen or type(ordinal) is not int
                or not 1 <= ordinal <= 50 or type(runtime_result) is not dict):
            raise ValueError('An unseen active original round is required')
        text = self.session.bridge_for_case(case_id).driver_inputs()['rounds'][ordinal - 1]
        scope = {'run_id': self.session.run.run_id, 'source_revision': self.session.run.source_revision,
            'case_id': case_id, 'project_id': self.session.case_plans[case_id]['project_id'],
            'round': ordinal, 'input_sha256': hashlib.sha256(text.encode()).hexdigest()}
        receipt = {**scope, 'schema_version': 'memoir-fifty-photo-receipt/1',
            'status': 'not_requested', 'executed': True, 'called': False, 'browser_status': 'not_run',
            'reason': 'no_safe_explicit_public_photo_intent',
            'model_requests_started': 0, 'real_storage_writes': 0,
            'searches_started_case': self._counts.get(case_id, 0),
            'searches_started_global': sum(self._counts.values()),
            'logical_search_limit_case': 2, 'logical_search_limit_global': 10,
            'catalogue_http_requests_counted': True, 'catalogue_http_hard_cap_verified': True,
            'public_http_limit_search': 128, 'public_http_limit_case': 256, 'public_http_limit_global': 1280,
            'public_http_requests_reserved': 0,
            'photo_browser_providers': 'not_admitted_uncounted_browser_network',
            'gateway_budget_boundary': 'client_to_existing_gateway_http_requests'}
        self._seen.add((case_id, ordinal))
        intent = photo_intent(text, runtime_result.get('place_journeys', []))
        if intent is None:
            self._receipts.append(receipt)
            return deepcopy(receipt)
        receipt['request'] = intent
        receipt.pop('reason', None)
        if self.admission.get('status') != 'ready':
            receipt.update(status='unavailable', reason=self.admission.get('reason', 'photo_not_admitted'))
        elif self._counts.get(case_id, 0) >= 2 or sum(self._counts.values()) >= 10:
            receipt.update(status='unavailable', reason='photo_search_limit')
        else:
            async with self._lock:
                _assert_session(self.session)
                if self.closed or self.session._active != (case_id, ordinal):
                    raise ValueError('Photo scope changed before dispatch')
                timeout = min(MAX_SEARCH_SECONDS, self.session.run.remaining_seconds())
                self._counts[case_id] = self._counts.get(case_id, 0) + 1
                receipt.update(called=True, searches_started_case=self._counts[case_id],
                               searches_started_global=sum(self._counts.values()))
                self._http_cases[sum(self._counts.values())] = case_id
                task = asyncio.current_task()
                active = self.session.run._begin_dispatch()
                self.session._pending.add(task)
                try:
                    body = await self._execute({'owner': scope['project_id'], **intent}, timeout)
                    self.session.run.remaining_seconds()
                    receipt.update(photo_observation(body))
                except PhotoCleanupError:
                    receipt.update(status='unavailable', reason='photo_cleanup_failed')
                    self._receipts.append(receipt)
                    raise
                except asyncio.CancelledError:
                    receipt.update(status='unavailable', reason='photo_cancelled')
                    self._receipts.append(receipt)
                    raise
                except Exception:
                    receipt.update(status='unavailable', reason='photo_process_failed')
                finally:
                    index = sum(self._counts.values())
                    receipt['public_http_requests_reserved'] = self._http_reserved.get(index, 0)
                    receipt['public_http_accounting'] = 'unavailable' if index in self._http_uncertain else 'available'
                    receipt['public_http_requests_completed'] = None
                    receipt['public_http_upstream_cancellation_verified'] = False
                    self.session._pending.discard(task)
                    if active:
                        self.session.run._end_dispatch()
        self._receipts.append(receipt)
        return deepcopy(receipt)

    async def _settle_process(self, process, waiter):
        from scripts.run_isolated_check import stop_owned
        # Shield cleanup and join it even if cancellation arrives again.
        cleanup = asyncio.create_task(asyncio.to_thread(stop_owned, process))
        cancelled = False
        for task in (cleanup, waiter):
            while not task.done():
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    cancelled = True
                    continue
                except Exception:
                    break
        try:
            waiter.result()
        except BaseException:
            pass
        self._cleanup_complete = cleanup.result()['group_gone']
        if not self._cleanup_complete:
            raise PhotoCleanupError('Owned photo process cleanup incomplete')
        if cancelled:
            raise asyncio.CancelledError()

    async def _process(self, command, *, timeout, cwd, env, capture=False):
        if hashlib.sha256(Path(self.binary).read_bytes()).hexdigest() != self.binary_sha256:
            raise ValueError('Pinned photo Python changed')
        process = subprocess.Popen(command, cwd=cwd, env=env,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, start_new_session=True)
        self.process, self._cleanup_complete = process, False
        waiter = asyncio.create_task(asyncio.to_thread(process.communicate, timeout=timeout))
        self._waiter = waiter
        try:
            stdout, _ = await asyncio.shield(waiter)
            if process.returncode != 0:
                raise ValueError('Photo process did not complete')
            return stdout or b''
        finally:
            try:
                await self._settle_process(process, waiter)
            finally:
                if self.process is process and self._cleanup_complete:
                    self.process, self._waiter = None, None

    async def _execute(self, request, timeout):
        index = sum(self._counts.values())
        work = self.directory / f'search-{index:02d}'
        work.mkdir(mode=0o700)
        source, target = work / 'request.json', work / 'result.json'
        source.write_text(json.dumps(request), encoding='utf-8'); source.chmod(0o600)
        env = {**self.env, 'HOME': str(work), 'TMPDIR': str(work)}
        try:
            await self._process([self.binary, str(Path(__file__).resolve()),
                '--owned-worker', str(source), str(target)], timeout=timeout, cwd=work, env=env)
        finally:
            try:
                self._http_reserved[index] = _read_http_reservations(work / 'http-reservations.jsonl')
            except PhotoCleanupError:
                self._http_reserved[index] = None
                self._http_uncertain.add(index)
                raise
        if not target.is_file() or target.is_symlink() or target.stat().st_size > MAX_RESULT_BYTES:
            raise ValueError('Photo worker result unavailable')
        result = json.loads(target.read_text())
        if (result.get('public_http_requests_reserved') != self._http_reserved[index]
                or result.get('public_http_journal_durable') is not True):
            self._http_uncertain.add(index)
            raise PhotoCleanupError('Public HTTP receipt cannot be reconciled')
        return result

    def receipts(self):
        return deepcopy(self._receipts)

    def snapshot(self):
        return {'schema_version': 'memoir-fifty-photo-lifecycle/1',
            'admission': deepcopy(getattr(self, 'admission', {'status': 'unavailable'})),
            'closed': self.closed, 'cleanup_complete': self._cleanup_complete,
            'owned_process_active': self.process is not None,
            'logical_searches_started': sum(self._counts.values()),
            'case_searches_started': deepcopy(self._counts),
            'model_requests_started': 0, 'real_storage_writes': 0,
            'catalogue_http_requests_counted': True, 'catalogue_http_hard_cap_verified': True,
            'public_http_limit_search': 128, 'public_http_limit_case': 256, 'public_http_limit_global': 1280,
            'public_http_requests_reserved': (None if self._http_uncertain else sum(self._http_reserved.values())),
            'public_http_requests_reserved_known': sum(count for count in self._http_reserved.values() if type(count) is int),
            'public_http_accounting': 'unavailable' if self._http_uncertain else 'available',
            'public_http_requests_completed': None, 'public_http_upstream_cancellation_verified': False,
            'case_public_http_requests_reserved': {case: (None if any(self._http_cases.get(index) == case
                for index in self._http_uncertain) else sum(count for index, count in self._http_reserved.items()
                if self._http_cases.get(index) == case and type(count) is int)) for case in self._counts},
            'photo_browser_providers': 'not_admitted_uncounted_browser_network',
            'browser_rendering': 'not_run',
            'receipts': self.receipts()}

    async def close(self):
        self.closed = True
        if self.process is not None:
            process, waiter = self.process, self._waiter
            try:
                await self._settle_process(process, waiter)
            finally:
                if self.process is process and self._cleanup_complete:
                    self.process, self._waiter = None, None


def validate_browser_receipt(value, *, expected_scope, artifact_root):
    """Validate a separate browser producer's scope and retained PNG artifacts.

    This is only a receipt contract check. It does not itself establish that the
    browser ran or that its assertions are true; retain the producer's execution
    and network receipts alongside the screenshots before claiming acceptance.
    """
    if (type(value) is not dict or value.get('schema_version') != 'memoir-fifty-browser-receipt/1'
            or value.get('evidence_mode') != 'rendered_browser' or value.get('status') != 'passed'
            or any(value.get(key) != expected_scope.get(key) or key not in expected_scope for key in _SCOPE_FIELDS)):
        raise ValueError('A scoped rendered-browser receipt is required')
    observations = value.get('observations')
    checks = ('current_input_rendered', 'reply_rendered', 'place_scope_matches',
              'photo_source_labels_visible', 'photo_rights_labels_visible', 'photo_date_labels_visible')
    if (type(observations) is not dict or any(observations.get(key) is not True for key in checks)
            or observations.get('page_errors') != [] or observations.get('unexpected_network_requests') != []):
        raise ValueError('Rendered browser observations are incomplete')
    shots, root = value.get('screenshots'), Path(artifact_root).resolve()
    if type(shots) is not list or not 1 <= len(shots) <= 10:
        raise ValueError('Retained browser screenshots are required')
    for shot in shots:
        if type(shot) is not dict or type(shot.get('path')) is not str:
            raise ValueError('Invalid browser screenshot')
        path = root / shot['path']
        if (Path(shot['path']).is_absolute() or path.is_symlink() or root not in path.resolve().parents
                or not path.is_file() or path.stat().st_size > 16 * 1024 * 1024):
            raise ValueError('Screenshot is outside the owned artifact directory')
        raw = path.read_bytes()
        if not raw.startswith(b'\x89PNG\r\n\x1a\n') or hashlib.sha256(raw).hexdigest() != shot.get('sha256'):
            raise ValueError('Screenshot identity is invalid')
    return deepcopy(value)


class PublicHttpBudget:
    """Durable pre-send attempts for this one child; no reservation refund."""
    def __init__(self, path):
        self.fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        self.lock = threading.Lock()
        self.reserved = 0
        self.exhausted = False
        self.failed = False

    def reserve(self, method, host, body=None, headers=None):
        if (method not in {'GET', 'HEAD'} or host not in _PUBLIC_HOSTS or body is not None
                or any(str(key).lower() in {'authorization', 'cookie', 'proxy-authorization'}
                       for key in (headers or {}))):
            raise ValueError('Public read-only HTTP destination required')
        with self.lock:
            if self.failed or self.reserved >= MAX_PUBLIC_HTTP_REQUESTS:
                self.exhausted = True
                raise ValueError('Public HTTP attempt limit reached')
            ordinal = self.reserved + 1
            # Reserve in memory even if persistence fails. A failed journal
            # closes this boundary permanently before any HTTP contact.
            self.reserved = ordinal
            raw = (json.dumps({'ordinal': ordinal, 'method': method}, separators=(',', ':')) + '\n').encode()
            try:
                offset = 0
                while offset < len(raw):
                    count = os.write(self.fd, raw[offset:])
                    if count <= 0:
                        raise OSError('Journal unavailable')
                    offset += count
                os.fsync(self.fd)
            except BaseException:
                self.failed = True
                raise

    def close(self):
        os.close(self.fd)


def _read_http_reservations(path):
    if not path.exists():
        raise PhotoCleanupError('Public HTTP journal missing; accounting unavailable')
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 16384:
        raise PhotoCleanupError('Public HTTP journal unavailable')
    rows = path.read_bytes().splitlines()
    if len(rows) > MAX_PUBLIC_HTTP_REQUESTS:
        raise PhotoCleanupError('Public HTTP journal exceeds its bound')
    try:
        for ordinal, raw in enumerate(rows, 1):
            value = json.loads(raw)
            if value not in ({'ordinal': ordinal, 'method': 'GET'}, {'ordinal': ordinal, 'method': 'HEAD'}):
                raise ValueError()
    except (ValueError, TypeError):
        raise PhotoCleanupError('Public HTTP journal incomplete') from None
    return len(rows)


@contextmanager
def counted_public_catalogues(journal):
    """Task-child-only replacements: every selected external path is counted.

    Browser/LLM/keyed providers have no admitted transport here. Catalogue JSON,
    robots checks, image fingerprints and each redirect use the existing public
    IP-pinned, TLS-verifying Fetcher. It has no automatic transport retries.
    A caller requiring a proxy must report that blocker, never bypass it.
    """
    from apps.api import place_photos as providers
    from apps.api.place_photo_browser import _research
    helper = _research()
    budget = PublicHttpBudget(journal)
    original_https, original_http = helper.PinnedHTTPS, helper.PinnedHTTP
    original_addresses = helper.public_addresses
    original_get = providers._get
    replacements = {key: getattr(providers, key) for key in
                    ('_google_browser', '_flickr_browser', '_google_cse', '_flickr', '_llm_web_search')}
    class CountedHTTPS(original_https):
        def request(self, method, url, body=None, headers=None, *, encode_chunked=False):
            budget.reserve(method, self.host, body, headers)
            return super().request(method, url, body=body, headers=headers or {}, encode_chunked=encode_chunked)
    def addresses(host, port):
        # Refuse unknown hosts and exhausted reads before even resolving DNS.
        if host not in _PUBLIC_HOSTS or port != 443:
            raise ValueError('Public catalogue host required')
        with budget.lock:
            if budget.failed or budget.reserved >= MAX_PUBLIC_HTTP_REQUESTS:
                budget.exhausted = True
                raise ValueError('Public HTTP attempt limit reached')
        return original_addresses(host, port)
    def forbidden_http(*args, **kwargs):
        raise ValueError('Only counted TLS-verified public HTTPS is admitted')
    def disabled(*args, **kwargs):
        raise providers.PhotoResearchUnavailable('browser', 'uncounted_network_not_admitted')
    def get(url, params):
        target = url + ('&' if '?' in url else '?') + urlencode(params)
        status, _, _, raw = helper.Fetcher().fetch(target, MAX_RESULT_BYTES,
            {'commons.wikimedia.org', 'loc.gov', 'www.loc.gov'}, deadline_seconds=15)
        if status != 200:
            raise providers.PhotoResearchUnavailable('catalogue', f'http_{status}')
        value = json.loads(raw)
        if type(value) is not dict:
            raise ValueError('Catalogue response must be an object')
        return value
    helper.PinnedHTTPS, helper.PinnedHTTP = CountedHTTPS, forbidden_http
    helper.public_addresses = addresses
    providers._get = get
    for key in replacements:
        setattr(providers, key, disabled)
    try:
        yield budget
    finally:
        providers._get = original_get
        helper.PinnedHTTPS, helper.PinnedHTTP = original_https, original_http
        helper.public_addresses = original_addresses
        for key, value in replacements.items():
            setattr(providers, key, value)
        budget.close()


async def _worker(source, target):
    if (os.getenv('MEMORY_SPARK_PHOTO_WEB_SEARCH') != '0'
            or any(os.getenv(key) for key in ('SUPABASE_URL', 'SUPABASE_SECRET_KEY',
                'MEMORY_SPARK_LLM_API_KEY', 'MEMORY_SPARK_LLM_BASE_URL',
                'MEMORY_SPARK_PHOTO_WORKER_URL', 'GOOGLE_CSE_API_KEY', 'FLICKR_API_KEY'))):
        raise ValueError('Sanitized public-only worker environment required')
    from apps.api.place_photo_pages import PhotoPages
    request = json.loads(Path(source).read_text())
    if set(request) - {'owner', 'place', 'period', 'latitude', 'longitude'}:
        raise ValueError('Public photo request required')
    # No Chromium launch occurs. Uncounted browser providers fail closed.
    with counted_public_catalogues(Path(target).parent / 'http-reservations.jsonl') as budget:
        pages = PhotoPages(repository=None)
        try:
            result = await asyncio.to_thread(pages.page, request['owner'], request['place'], request['period'], None,
                **{key: request[key] for key in ('latitude', 'longitude') if key in request})
            result['public_http_requests_reserved'] = budget.reserved
            result['public_http_journal_durable'] = not budget.failed
            result['public_http_limit'] = MAX_PUBLIC_HTTP_REQUESTS
            result['public_http_limit_reached'] = budget.exhausted
            raw = json.dumps(result, ensure_ascii=False).encode()
            if len(raw) > MAX_RESULT_BYTES:
                raise ValueError('Photo receipt is too large')
            with open(target, 'xb') as stream:
                os.chmod(target, 0o600)
                stream.write(raw)
        finally:
            # page() already waits for terminal completion. Join all owned
            # catalogue threads before restoring the counted transport seam.
            await asyncio.to_thread(pages.pool.shutdown, wait=True, cancel_futures=True)


if __name__ == '__main__':
    if len(sys.argv) != 4 or sys.argv[1] != '--owned-worker':
        raise SystemExit('Native-owner admission is required; there is no live default')
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    asyncio.run(_worker(sys.argv[2], sys.argv[3]))
