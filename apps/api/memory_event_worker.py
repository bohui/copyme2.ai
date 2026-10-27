"""Trusted outbox-to-lane bridge and private event worker.

No credentials or story bytes enter Temporal. PostgreSQL receipt and token RPCs
resolve authorisation and perform the final atomic/fenced commits.
"""
import asyncio
from datetime import datetime, timezone
import json
import os
import logging
import sqlite3
import time

import httpx
from pydantic import ValidationError

from .recall import private_draft_cadence


_SAFE_MEMORY_ERROR_KINDS = (
    'authenticated user required', 'invalid extraction result', 'project unavailable',
    'source unavailable', 'source revision conflict', 'invalid event proposal',
    'ambiguous candidates must remain scoped and unresolved',
    'person identity unavailable in this project', 'chronology target unavailable in this project',
    'event unavailable', 'event revision conflict', 'event kind cannot change',
    'chat correction requires explicit current original testimony', 'invalid life stage',
    'extraction cannot grant visibility or print rights', 'invalid temporal placement',
    'life stage requires evidence', 'removed source link requires an explicit author decision',
    'event source unavailable', 'evidence revision conflict',
    'evidence quote must match original testimony', 'evidence span must match original testimony',
    'memoir run expired before commit',
    'bounded semantic summary required', 'fact-free summary step must preserve prior context',
    'typed derived summary item required', 'exact summary evidence required',
    'summary evidence outside accepted inputs', 'summary replay conflict', 'stale summary page',
    'bounded place journeys required', 'grounded coarse place journey required', 'valid public place centre required',
    'bounded derived hints required', 'prepared questions must be distinct', 'grounded question hints required',
    'reply only work cannot create derived facts', 'invalid bounded strategy proposal',
    'stale derived page', 'strategy revision changed', 'older strategy source',
    'stale strategy plan input', 'strategy replay conflict', 'strategy CAS failed',
    'complete canonical source inventory required', 'checkpoint predecessor or coverage changed',
    'stale semantic checkpoint', 'incomplete accepted summary receipts', 'semantic checkpoint CAS failed',
    'summary admission differs from canonical page', 'semantic page requires its canonical writer',
    'background continuity replay conflict', 'bounded current background continuity required',
    'reply only work cannot create continuity', 'current background original required',
    'descriptive background continuity required', 'exact admitted background continuity evidence required',
    'background continuity requires a saved reply v2 handoff', 'atomic background continuity commit required',
    'background original changed during canonical commit', 'background continuity identity conflict',
    'background continuity commit receipt required',
    'attribution replay conflict', 'bounded attribution result required', 'bounded attribution proposals required',
    'rule handling cannot add model attribution', 'exact current attribution evidence required',
    'invalid passage disposition', 'non-story disposition conflicts with direct testimony',
    'bounded event proposal index required', 'invalid selective event place', 'public coarse geography required',
    'place requires one exact event passage',
    'profile rollout disabled', 'timeline owner required', 'profile commit deferred during interactive turn',
    'bounded profile patch required', 'profile retry body changed', 'stale profile page',
    'profile disposition differs from admitted work', 'auto eligible profile field and original evidence required',
    'invalid profile birth year', 'invalid profile value', 'exact current profile evidence required',
    'newer chosen name authority', 'chosen name authority changed',
    'guidance context changed', 'attribution context changed', 'canonical profile owner required',
    'profile admission deferred or stopped', 'stale canonical profile admission',
    'profile cannot reuse timeline outputs', 'revision instruction changed', 'bounded lane fence required',
    'canonical lane owner mismatch', 'current privacy requires maintenance', 'stale canonical lane admission',
    'bounded prior output proofs required', 'derived lane output belongs to another page',
    'stale progressive authority', 'canonical lane unavailable', 'stale canonical lane page',
    'bounded skill phase required', 'profile model not admitted', 'skill phase mismatch',
    'timeline model not admitted', 'skill page changed',
    'ambiguous question evidence requires exact offsets', 'typed question evidence offsets required',
    'question evidence span must match the referenced passage',
)

# Match only fixed validator messages. Exception bodies may include private
# testimony; unknown messages must never be copied into diagnostics.
_SAFE_VALIDATION_KINDS = {
    'Unsupported life stage': 'unsupported_life_stage',
    'Canonical event revision conflict': 'event_revision_conflict',
    'Ambiguous identity must remain unresolved': 'ambiguous_identity',
    'A new event has no expected revision': 'invalid_new_event_revision',
    'Unresolved candidates must be canonical scoped identities': 'candidate_scope',
    'Chronology requires a canonical scoped target': 'chronology_scope',
    'Explicit correction must cite the current original statement': 'correction_evidence',
    'Correction requires explicit correction wording': 'correction_wording',
    'Evidence must match an authorised original source version': 'evidence_mismatch',
    'Evidence span must match the original words': 'evidence_span',
    'Stage placement requires evidence': 'stage_evidence',
    'A supported year requires a date evidence basis': 'date_evidence',
    'Date ranges must retain their original direction': 'date_range',
    'Numeric date requires supported original evidence': 'numeric_date_evidence',
    'The original date expression must be retained in its evidence': 'date_expression',
    'Evidence outside the claimed source page': 'source_page_scope',
    'Evidence requires both exact offsets or neither': 'incomplete_evidence_span',
    'An ambiguous occurrence requires exact offsets': 'ambiguous_evidence_span',
    'Evidence span exceeds claimed source page': 'source_page_span',
    'Evidence quote outside claimed source page': 'source_page_quote',
    'Whole-source policy authority changed': 'source_authority_changed',
    'Unsupported canonical lane page': 'unsupported_lane_page',
    'Invalid canonical lane fence': 'invalid_lane_fence',
    'Invalid canonical lane scope': 'invalid_lane_scope',
    'Typed current lane preferences required': 'invalid_lane_preferences',
    'Invalid bounded original source window': 'invalid_source_window',
    'Unbounded canonical event candidates': 'unbounded_event_candidates',
    'Invalid bounded canonical lane page': 'invalid_lane_page',
}


def _safe_validation_failure(failure):
    if isinstance(failure, ValidationError):
        return 'invalid_schema'
    if isinstance(failure, json.JSONDecodeError):
        return 'invalid_json'
    if isinstance(failure, ValueError):
        return _SAFE_VALIDATION_KINDS.get(str(failure))
    return None


def _safe_rpc_failure(failure):
    """Classify PostgREST and wrapped database errors without copying private messages."""
    code = None
    kind = None
    try:
        if isinstance(failure, httpx.HTTPStatusError):
            body = failure.response.json()
        else:
            from psycopg import Error
            cause = failure if isinstance(failure, Error) else failure.__cause__
            if not isinstance(cause, Error):
                return None, None
            body = {'code': cause.sqlstate, 'message': cause.diag.message_primary or str(cause)}
        if isinstance(body, dict) and isinstance(body.get('code'), str):
            candidate = body['code']
            if len(candidate) <= 32 and candidate.isascii() and candidate.replace('_', '').isalnum():
                code = candidate
        message = body.get('message', '') if isinstance(body, dict) else ''
        if isinstance(message, str):
            kind = next((value for value in sorted(_SAFE_MEMORY_ERROR_KINDS, key=len, reverse=True) if value in message), None)
    except (ImportError, ValueError, TypeError):
        pass
    return code, kind


class MemoirLaneBroker:
    def __init__(self, *, url=None, key=None, client=None):
        self.url = (url or os.environ['SUPABASE_URL']).rstrip('/')
        self.key = key or os.environ['SUPABASE_SECRET_KEY']
        self.client = client or httpx.AsyncClient(timeout=30)

    async def rpc(self, name, **payload):
        started = time.monotonic()
        try:
            response = await self.client.post(self.url + '/rest/v1/rpc/' + name,
                headers={'apikey': self.key, 'Authorization': 'Bearer ' + self.key}, json=payload)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as failure:
            code, kind = _safe_rpc_failure(failure)
            logging.getLogger(__name__).warning(
                'memoir_lane rpc_failure rpc_name=%s lane_id=%s page_number=%s page_digest=%s failure_type=%s http_status=%s elapsed_ms=%d rpc_code=%s rpc_kind=%s at=%s',
                name, payload.get('p_lane_id'), payload.get('p_page_number'), payload.get('p_page_digest'),
                type(failure).__name__, failure.response.status_code if isinstance(failure, httpx.HTTPStatusError) else None,
                int((time.monotonic() - started) * 1000), code, kind, datetime.now(timezone.utc).isoformat())
            raise

    async def drain_once(self):
        receipts = await self.rpc('pending_memoir_receipts', p_limit=50)
        lanes = []
        page_budget = 8
        for receipt in receipts:
            scope = await self.rpc('read_memoir_receipt_scope', p_receipt_id=receipt)
            if scope and scope['change_kind'] in {'revocation', 'delete'}:
                from .draft_cache import prune_saved_cache
                await asyncio.to_thread(prune_saved_cache, scope['user_id'], scope['project_id'],
                    preserve_lifetime_pages=bool(scope.get('conversation_id')))
            if scope and scope.get('conversation_id'):
                if page_budget <= 0:
                    break
                complete,used = await self._checkpoint_lifetime_receipt(receipt,page_budget)
                page_budget -= used
                if not complete:
                    break
            try:
                queued = await self.rpc('queue_memoir_receipt', p_receipt_id=receipt, p_cadence=private_draft_cadence())
            except httpx.HTTPStatusError as error:
                from .private_draft_broker import receipt_scope_conflict
                if not (scope and scope.get('conversation_id') and receipt_scope_conflict(error)):
                    raise
                from .private_draft_jobs import PrivateDraftJobs
                await asyncio.to_thread(PrivateDraftJobs(os.environ['MEMORY_SPARK_TASK_DB']).restart_page,receipt)
                break

            if queued:
                lanes.extend(v for k, v in queued.items() if k.endswith('_lane_id') and v)
        return list(dict.fromkeys(lanes))

    async def _checkpoint_lifetime_receipt(self,receipt,budget):
        from .private_draft_broker import PrivateDraftBroker,receipt_scope_conflict
        from .private_draft_jobs import PrivateDraftJobs
        path=os.getenv('MEMORY_SPARK_TASK_DB')
        if not path:
            # Leave the required PostgreSQL receipt undelivered. No local
            # fallback may acknowledge work it cannot checkpoint durably.
            raise RuntimeError('Governed draft receipt store unavailable')
        queue=PrivateDraftJobs(path)
        resume=await asyncio.to_thread(queue.page_resume,receipt)
        if resume and resume['complete']:
            return True,0
        cursor=resume['next_cursor'] if resume else None
        used=0
        while used<budget:
            used+=1
            try:
                page=await self.rpc('private_draft_event_page',p_event_id=receipt,p_cursor=cursor)
            except httpx.HTTPStatusError as error:
                if cursor is None or not (error.response.status_code in {400,409} or receipt_scope_conflict(error,snapshot=True)):
                    raise
                # Retry a changed policy from its newly authorised first page
                # on the next bounded iteration, never continue stale bytes.
                cursor=None
                continue
            if not page:
                raise RuntimeError('Governed draft receipt unavailable')
            result=await asyncio.to_thread(PrivateDraftBroker.reconcile,page)
            if result['retrieval_complete']:
                return True,used
            cursor=result['next_cursor']
        return False,used

    async def run(self):
        interval = min(max(float(os.getenv('MEMORY_SPARK_OUTBOX_POLL_SECONDS', '2')), 1), 60)
        while True:
            try:
                await self.drain_once()
            except (ValueError, RuntimeError, sqlite3.Error, httpx.HTTPError):
                logging.getLogger(__name__).warning('Memoir outbox delivery deferred')
            await asyncio.sleep(interval)


class MemoryEventWorker:
    def __init__(self, broker, *, worker_url=None, worker_secret=None, worker_transport=None):
        self.broker = broker
        self.worker_url = (worker_url or os.environ['MEMORY_SPARK_CODEX_WORKER_URL']).rstrip('/')
        self.worker_secret = worker_secret or os.environ['MEMORY_SPARK_CODEX_WORKER_SECRET']
        self.worker_transport = worker_transport

    async def execute_lane(self, lane_id):
        started = time.monotonic()
        run_seconds = int(os.getenv('MEMORY_SPARK_MEMOIR_RUN_SECONDS', '900'))
        try:
            job = await self.broker.rpc('claim_memoir_lane', p_lane_id=lane_id, p_run_seconds=run_seconds)
        except Exception as error:
            from .lifetime_memory_policy import PolicyUnavailable, is_policy_pending
            if not is_policy_pending(error):
                raise
            # A rejected claim is rolled back atomically: there is no lease or
            # body authority to release and no generation failure to count.
            return {'status':'pending','error':PolicyUnavailable.code,'retrieval_complete':False}
        if not job:
            state = await self.broker.rpc('read_memoir_lane_state', p_lane_id=lane_id)
            return {'status': 'retry_required' if state and state['state']=='retry_required'
                    else 'finished' if not state or state['state']=='finished' else 'deferred'}
        async def heartbeat():
            while True:
                await asyncio.sleep(20)
                if not await self.broker.rpc('heartbeat_memoir_lane', p_lane_id=lane_id, p_token=job['token']):
                    return
        renewal = asyncio.create_task(heartbeat())
        try:
            async with asyncio.timeout(run_seconds):
                if job.get('protocol') != 'lifetime_composer_pages':
                    raise ValueError('Unsupported canonical lane page')
                from .lifetime_memory_composer import execute_lifetime_lane
                return await execute_lifetime_lane(job, self)
        except asyncio.CancelledError:
            if job.get('protocol') == 'lifetime_composer_pages':
                from .lifetime_memory_lane_engine import _settle
                try:
                    await _settle(asyncio.create_task(self.broker.rpc('yield_lifetime_memoir_lane',
                        p_lane_id=lane_id,p_token=job['token'])))
                except (ValueError,RuntimeError,httpx.HTTPError):
                    logging.getLogger(__name__).warning('memoir_lane cancellation_release_deferred lane_id=%s',lane_id)
            raise
        except (ValueError, TimeoutError, httpx.HTTPError, RuntimeError) as failure:
            # Exception messages and response bodies can contain private story
            # text or credentials. Keep dispatch/provider failures diagnosable.
            rpc_code, rpc_kind = _safe_rpc_failure(failure)
            rpc_name = None
            if isinstance(failure,httpx.HTTPStatusError):
                path=failure.request.url.path
                candidate=path.rsplit('/',1)[-1]
                if (path.startswith('/rest/v1/rpc/') and candidate.isascii()
                        and len(candidate)<=80 and candidate.replace('_','').isalnum()):
                    rpc_name=candidate
            logging.getLogger(__name__).warning(
                'memoir_lane failure lane_id=%s skill=%s failure_type=%s http_status=%s elapsed_ms=%d rpc_name=%s rpc_code=%s rpc_kind=%s validation_kind=%s',
                lane_id, job['skill'], type(failure).__name__,
                failure.response.status_code if isinstance(failure, httpx.HTTPStatusError) else None,
                int((time.monotonic() - started) * 1000), rpc_name, rpc_code, rpc_kind, _safe_validation_failure(failure))
            recovery = await self.broker.rpc('fail_memoir_lane', p_lane_id=lane_id, p_token=job['token'],
                p_error='MEMOIR_UNAVAILABLE', p_retryable=True)
            logging.getLogger(__name__).warning('memoir_lane recovery lane_id=%s skill=%s status=%s',
                lane_id, job['skill'], recovery.get('status'))
            return recovery
        finally:
            renewal.cancel()
            await asyncio.gather(renewal, return_exceptions=True)
