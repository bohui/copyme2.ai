"""Bounded selected-source jobs with canonical authority at every boundary.

Jobs store source versions, window offsets and derived outline ancestry, never
copies of the lifetime transcript. One run consumes at most eight bounded pages;
PostgreSQL leases, page commits and the frontier make crashes resumable.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import os
from uuid import UUID

from .lifetime_memory_contracts import ContextBudget
from .lifetime_memory_publication import PublicationUnavailable
from .lifetime_memory_read_api import mapped_identity
from .lifetime_memory_reads import ReadPublication, ReadFence, _settle, snapshot_lifetime_read


PAGE_LIMIT = 8
SELECTED_SOURCE_LIMIT = 1000


def _owner_rpc(storage, name, **parameters):
    import httpx
    from fastapi import HTTPException
    try:
        return storage.lifetime_rpc(name, **parameters)
    except httpx.HTTPStatusError as error:
        from .lifetime_memory_policy import PolicyUnavailable, is_policy_pending
        if is_policy_pending(error):
            raise HTTPException(503, str(PolicyUnavailable()),
                                headers={'X-Error-Code': PolicyUnavailable.code}) from None
        try:
            failure = error.response.json()
        except ValueError:
            failure = {}
        code = failure.get('code') if isinstance(failure, dict) else None
        if code == '40001':
            raise HTTPException(409, 'The collection or selected sources changed; review and retry') from None
        if code in {'22023', '22P02', 'P0001', '23514'}:
            raise HTTPException(422, 'The selected collection request is invalid') from None
        if code == '42501':
            raise HTTPException(403, 'The selected collection is unavailable or its permission changed') from None
        if code == '55000':
            raise HTTPException(503, 'Lifetime generation is paused; existing results remain available',
                                headers={'X-Error-Code': 'LIFETIME_GENERATION_PAUSED'}) from None
        raise HTTPException(503, 'Selected collection storage is temporarily unavailable') from None


def update_selection(storage, project_id, payload):
    return _owner_rpc(storage, 'set_lifetime_collection', p_project_id=project_id,
        p_expected_revision=payload.expected_revision,
        p_periods={key: period.model_dump() for key, period in payload.periods.items()},
        p_ready=payload.confirm_ready)


def submit_selected_job(storage, project_id, payload, *, organise=False):
    from .lifetime_memory_runtime import lifetime_generation_paused
    return _owner_rpc(storage, 'create_lifetime_collection_job', p_project_id=project_id,
        p_kind='BuildOutline' if organise else payload.kind,
        p_title='A life remembered' if organise else payload.title,
        p_source_ids=[] if organise else payload.memory_ids,
        p_expected_revision=payload.expected_revision if organise else None,
        p_locale=payload.language if organise else 'en-AU', p_paused=organise and lifetime_generation_paused())


class CollectionResultPublication(ReadPublication):
    """One transaction verifies ordinary read and selected-job authority.

    Two nested database transactions could deadlock when upgrading the job lock.
    The single SQL entry point follows account/project/profile/identity/
    collection/entitlement/job order and retains those locks through the bounded
    actual ASGI send.
    """
    def __init__(self, dsn, *, authenticated_owner, job_id, **kwargs):
        super().__init__(dsn, authenticated_owner=authenticated_owner, **kwargs)
        self.job_id = UUID(str(job_id))
        self.root_digest = None

    @asynccontextmanager
    async def guard(self, fence):
        from psycopg import AsyncConnection, Error
        from psycopg.types.json import Jsonb
        snapshot = ReadFence.model_validate(fence).model_dump(mode='json')
        root = self.root_digest
        if snapshot['identity']['owner_id'] != str(self.owner) or not isinstance(root, str) or len(root) != 64:
            raise PublicationUnavailable('Collection result publication scope is unavailable')
        connection = None
        try:
            try:
                async with asyncio.timeout(self.lock_timeout):
                    connection = await AsyncConnection.connect(self._dsn, connect_timeout=2)
                    await connection.execute('set local role authenticated')
                    await connection.execute("select set_config('request.jwt.claim.sub',%s,true)", (str(self.owner),))
                    await connection.execute("select set_config('lock_timeout',%s,true)", (f'{int(self.lock_timeout*1000)}ms',))
                    result = await connection.execute('select public.lock_lifetime_collection_result_publication(%s,%s,%s)',
                        (Jsonb(snapshot), str(self.job_id), root))
                    remaining = float((await result.fetchone())[0])
            except Error as error:
                raise PublicationUnavailable('Selected collection result is unavailable or stale') from error
            allowance = min(self.send_timeout, remaining - .1)
            if allowance <= 0:
                raise PublicationUnavailable('Selected collection result snapshot expired')
            async with asyncio.timeout(allowance):
                yield
        finally:
            if connection is not None:
                await _settle(asyncio.create_task(connection.close()))


def selected_job_result(storage, task_id, *, cursor=None, limit=PAGE_LIMIT, publisher=None):
    """A mapped owner never falls back to unfenced legacy SQLite result bytes."""
    identity = mapped_identity(storage, None)
    if identity is None:
        return None
    from fastapi import HTTPException
    try:
        task_id = str(UUID(str(task_id)))
    except ValueError:
        raise HTTPException(404, 'Task not found') from None
    scope = _owner_rpc(storage, 'read_lifetime_collection_job_scope', p_job_id=task_id)
    if not scope:
        raise HTTPException(404, 'Task not found')
    publisher = publisher or CollectionResultPublication(os.getenv('MEMOIR_PUBLICATION_DATABASE_URL'),
        authenticated_owner=storage.user_id, job_id=task_id)
    def reader(fence):
        value = _owner_rpc(storage, 'read_lifetime_collection_job', p_job_id=str(UUID(str(task_id))),
            p_cursor=str(UUID(str(cursor))) if cursor else None, p_limit=limit)
        publisher.root_digest = value['root_digest']
        return value
    return snapshot_lifetime_read(storage, scope['project_id'], reader, publisher=publisher)


class CollectionJobWorker:
    def __init__(self, broker, *, worker_url=None, worker_secret=None, worker_transport=None, publisher=None, budget=None):
        self.broker = broker
        self.worker_url = worker_url if worker_url is not None else os.getenv('MEMORY_SPARK_CODEX_WORKER_URL')
        self.worker_secret = worker_secret if worker_secret is not None else os.getenv('MEMORY_SPARK_CODEX_WORKER_SECRET')
        self.worker_transport = worker_transport
        self.publisher = publisher
        self.budget = budget or ContextBudget(model=os.getenv('MEMORY_SPARK_LLM_MODEL', 'gpt-5.6-luna-pooled'),
            context_window=131072, input_budget=65536, output_headroom=32768, framing_headroom=4096)

    async def _defer_policy(self, claim, processed):
        # The content guard is deliberately closed. Release only this persisted
        # owner's live lease through the separate metadata-only authority.
        await self.broker.rpc('defer_lifetime_collection_job_policy',
            p_job_id=claim['id'], p_token=claim['token'], p_user_id=claim['user_id'])
        return {'status': 'deferred', 'processed': processed}

    async def execute(self, job_id, *, page_limit=PAGE_LIMIT):
        if type(page_limit) is not int or not 1 <= page_limit <= PAGE_LIMIT:
            raise ValueError('A collection run accepts one to eight pages')
        from .lifetime_memory_activation import CanonicalActivationUnavailable
        from .lifetime_memory_lane_engine import check_lane_generation, LaneGenerationPaused
        from .lifetime_memory_policy import is_policy_pending
        try:
            claim = await self.broker.rpc('claim_lifetime_collection_job', p_job_id=str(UUID(str(job_id))), p_run_seconds=600)
        except Exception as error:
            if is_policy_pending(error):
                # A rejected claim is atomic: no token or attempt was acquired.
                return {'status': 'deferred', 'processed': 0}
            raise
        if not claim:
            return {'status': 'deferred', 'processed': 0}
        processed = 0
        try:
            for _ in range(page_limit):
                page = await self.broker.rpc('read_lifetime_collection_job_page', p_job_id=claim['id'], p_token=claim['token'])
                if page.get('complete'):
                    return {'status': 'succeeded', 'processed': processed}
                result = None
                if page['kind'] == 'BuildOutline':
                    check_lane_generation()
                    from .lifetime_memory_job_engine import build_bounded_job_input, send_bounded_job_request, validate_job_result
                    if not self.worker_url or not self.worker_secret:
                        raise PublicationUnavailable('Organising worker unavailable')
                    bounded = build_bounded_job_input(page, budget=self.budget)
                    response = await send_bounded_job_request(worker_url=self.worker_url, worker_secret=self.worker_secret, bounded_job=bounded,
                        worker_transport=self.worker_transport, publisher=self.publisher)
                    result = validate_job_result(bounded.fence, response['reply'])
                committed = await self.broker.rpc('commit_lifetime_collection_job_page',
                    p_fence={key: value for key, value in page.items() if key != 'complete'}, p_result=result)
                processed += 1
                if committed['complete']:
                    return {'status': 'succeeded', 'processed': processed}
            await self.broker.rpc('release_lifetime_collection_job', p_job_id=claim['id'], p_token=claim['token'], p_error=None)
            return {'status': 'pending', 'processed': processed}
        except (LaneGenerationPaused, CanonicalActivationUnavailable):
            # Provider authority and generation pause are scheduling deferrals,
            # not failed model attempts. Keep the frozen manifest/checkpoint.
            try:
                await self.broker.rpc('release_lifetime_collection_job', p_job_id=claim['id'], p_token=claim['token'], p_error=None)
            except Exception as error:
                if is_policy_pending(error):
                    return await self._defer_policy(claim, processed)
                raise
            return {'status': 'deferred', 'processed': processed}
        except Exception as error:
            if is_policy_pending(error):
                return await self._defer_policy(claim, processed)
            # Never persist exception strings containing source or generated bytes.
            # A failed release leaves the durable token to expire and be reclaimed.
            try:
                await self.broker.rpc('release_lifetime_collection_job', p_job_id=claim['id'], p_token=claim['token'],
                    p_error='BOUNDED_JOB_RETRY')
            except Exception:
                pass
            raise


async def drain_collection_jobs_once(broker, *, limit=4, worker=None):
    if type(limit) is not int or not 1 <= limit <= 8:
        raise ValueError('A collection drain accepts one to eight jobs')
    from .lifetime_memory_runtime import lifetime_generation_paused
    jobs = await broker.rpc('pending_lifetime_collection_jobs', p_limit=limit, p_include_outline=not lifetime_generation_paused())
    executor = worker or CollectionJobWorker(broker)
    results = []
    for job_id in jobs:
        try:
            results.append(await executor.execute(job_id))
        except Exception:
            results.append({'status': 'retry', 'processed': 0})
    return results
