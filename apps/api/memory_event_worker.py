"""Trusted outbox-to-lane bridge and private event worker.

No credentials or story bytes enter Temporal. PostgreSQL receipt and token RPCs
resolve authorisation and perform the final atomic/fenced commits.
"""
import asyncio
import json
import os
import logging
import sqlite3
import time

import httpx

from .memory_events import validate_extraction
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
)


def _safe_rpc_failure(failure):
    """Return stable PostgREST diagnostics without copying private messages."""
    if not isinstance(failure, httpx.HTTPStatusError):
        return None, None
    code = None
    kind = None
    try:
        body = failure.response.json()
        if isinstance(body, dict) and isinstance(body.get('code'), str):
            candidate = body['code']
            if len(candidate) <= 32 and candidate.replace('_', '').isalnum():
                code = candidate
        message = body.get('message', '') if isinstance(body, dict) else ''
        if isinstance(message, str):
            kind = next((value for value in _SAFE_MEMORY_ERROR_KINDS if value in message), None)
    except (ValueError, TypeError):
        pass
    return code, kind


class MemoirLaneBroker:
    def __init__(self, *, url=None, key=None, client=None):
        self.url = (url or os.environ['SUPABASE_URL']).rstrip('/')
        self.key = key or os.environ['SUPABASE_SECRET_KEY']
        self.client = client or httpx.AsyncClient(timeout=30)

    async def rpc(self, name, **payload):
        response = await self.client.post(self.url + '/rest/v1/rpc/' + name,
            headers={'apikey': self.key, 'Authorization': 'Bearer ' + self.key}, json=payload)
        response.raise_for_status()
        return response.json()

    async def drain_once(self):
        receipts = await self.rpc('pending_memoir_receipts', p_limit=50)
        lanes = []
        page_budget = 8
        for receipt in receipts:
            scope = await self.rpc('read_memoir_receipt_scope', p_receipt_id=receipt)
            if scope and scope['change_kind'] in {'revocation', 'delete'}:
                from .legacy_memoir import prune_saved_cache
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
        job = await self.broker.rpc('claim_memoir_lane', p_lane_id=lane_id, p_run_seconds=run_seconds)
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
                if job.get('protocol') == 'lifetime_composer_pages':
                    from .lifetime_memory_composer import execute_lifetime_lane
                    return await execute_lifetime_lane(job, self)
                if job['skill'] == 'composer':
                    from .canonical_composer import compose_shared_snapshot
                    bundle = await compose_shared_snapshot(job, self)
                    result = await self.broker.rpc('finish_memoir_composer', p_lane_id=lane_id, p_token=job['token'],
                                                  p_expected_revision=job['base_revision'], p_bundle=bundle)
                    if result['status'] in {'stale', 'rejected'}:
                        await self.broker.rpc('fail_memoir_lane', p_lane_id=lane_id, p_token=job['token'],
                                             p_error='MEMOIR_CONFLICT' if result['status'] == 'stale' else 'MEMOIR_REVIEW_FAILED', p_retryable=True)
                    return result
                options = {'timeout': min(240, run_seconds)}
                if self.worker_transport is not None:
                    options['transport'] = self.worker_transport
                request = {
                    'user_id': job['user_id'], 'project_id': job['project_id'], 'family_enabled': False,
                    'agent_role': 'author_timeline', 'language': job['locale'],
                    'text': json.dumps({'schema_version': 1, 'sources': job['sources'],
                        'context_sources': job['context_sources'], 'events': job['events'],
                        'interview_context': job.get('interview_context', {})}, ensure_ascii=False),
                }
                # A provider 400/5xx or a model proposal rejected by the
                # fenced commit gets a bounded fresh extraction before the
                # durable lane attempt is consumed. The commit can reject a
                # proposal after Python validation when PostgreSQL applies
                # stricter evidence/temporal rules.
                for extraction_attempt in range(3):
                    proposed = None
                    for provider_attempt in range(3):
                        try:
                            async with httpx.AsyncClient(**options) as client:
                                response = await client.post(self.worker_url + '/internal/codex/turn',
                                    headers={'X-Codex-Worker-Secret': self.worker_secret}, json=request)
                                response.raise_for_status()
                                proposed = json.loads(response.json()['reply'])
                            break
                        except httpx.HTTPStatusError as failure:
                            if provider_attempt < 2 and failure.response.status_code in {400, 429, 502, 503, 504}:
                                continue
                            raise
                    events = validate_extraction(proposed, job['context_sources'], job['events'])
                    try:
                        return await self.broker.rpc('finish_memoir_timeline', p_lane_id=lane_id,
                            p_token=job['token'], p_events=events)
                    except httpx.HTTPStatusError as failure:
                        if extraction_attempt < 2 and failure.response.status_code == 400:
                            continue
                        raise
        except (ValueError, TimeoutError, httpx.HTTPError, RuntimeError) as failure:
            # Exception messages and response bodies can contain private story
            # text or credentials. Keep dispatch/provider failures diagnosable.
            rpc_code, rpc_kind = _safe_rpc_failure(failure)
            logging.getLogger(__name__).warning(
                'memoir_lane failure lane_id=%s skill=%s failure_type=%s http_status=%s elapsed_ms=%d rpc_code=%s rpc_kind=%s',
                lane_id, job['skill'], type(failure).__name__,
                failure.response.status_code if isinstance(failure, httpx.HTTPStatusError) else None,
                int((time.monotonic() - started) * 1000), rpc_code, rpc_kind)
            return await self.broker.rpc('fail_memoir_lane', p_lane_id=lane_id, p_token=job['token'],
                p_error='MEMOIR_UNAVAILABLE', p_retryable=True)
        finally:
            renewal.cancel()
            await asyncio.gather(renewal, return_exceptions=True)
