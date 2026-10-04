"""Trusted outbox-to-lane bridge and private event worker.

No credentials or story bytes enter Temporal. PostgreSQL receipt and token RPCs
resolve authorisation and perform the final atomic/fenced commits.
"""
import asyncio
import json
import os
import logging

import httpx

from .memory_events import validate_extraction
from .recall import private_draft_cadence


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
        for receipt in receipts:
            queued = await self.rpc('queue_memoir_receipt', p_receipt_id=receipt, p_cadence=private_draft_cadence())
            if queued:
                lanes.extend(v for k, v in queued.items() if k.endswith('_lane_id') and v)
        return list(dict.fromkeys(lanes))

    async def run(self):
        interval = min(max(float(os.getenv('MEMORY_SPARK_OUTBOX_POLL_SECONDS', '2')), 1), 60)
        while True:
            try:
                await self.drain_once()
            except (ValueError, RuntimeError, httpx.HTTPError):
                logging.getLogger(__name__).warning('Memoir outbox delivery deferred')
            await asyncio.sleep(interval)


class MemoryEventWorker:
    def __init__(self, broker, *, worker_url=None, worker_secret=None, worker_transport=None):
        self.broker = broker
        self.worker_url = (worker_url or os.environ['MEMORY_SPARK_CODEX_WORKER_URL']).rstrip('/')
        self.worker_secret = worker_secret or os.environ['MEMORY_SPARK_CODEX_WORKER_SECRET']
        self.worker_transport = worker_transport

    async def execute_lane(self, lane_id):
        run_seconds = int(os.getenv('MEMORY_SPARK_MEMOIR_RUN_SECONDS', '300'))
        job = await self.broker.rpc('claim_memoir_lane', p_lane_id=lane_id, p_run_seconds=run_seconds)
        if not job:
            return {'status': 'deferred'}
        async def heartbeat():
            while True:
                await asyncio.sleep(20)
                if not await self.broker.rpc('heartbeat_memoir_lane', p_lane_id=lane_id, p_token=job['token']):
                    return
        renewal = asyncio.create_task(heartbeat())
        try:
            async with asyncio.timeout(run_seconds):
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
                async with httpx.AsyncClient(**options) as client:
                    response = await client.post(self.worker_url + '/internal/codex/turn',
                        headers={'X-Codex-Worker-Secret': self.worker_secret}, json={
                            'user_id': job['user_id'], 'project_id': job['project_id'], 'family_enabled': False,
                            'agent_role': 'author_timeline', 'language': job['locale'],
                            'text': json.dumps({'schema_version': 1, 'sources': job['sources'],
                                'context_sources': job['context_sources'], 'events': job['events']}, ensure_ascii=False),
                        })
                    response.raise_for_status()
                    proposed = json.loads(response.json()['reply'])
                events = validate_extraction(proposed, job['context_sources'], job['events'])
                return await self.broker.rpc('finish_memoir_timeline', p_lane_id=lane_id, p_token=job['token'], p_events=events)
        except (ValueError, TimeoutError, httpx.HTTPError, RuntimeError):
            return await self.broker.rpc('fail_memoir_lane', p_lane_id=lane_id, p_token=job['token'],
                p_error='MEMOIR_UNAVAILABLE', p_retryable=True)
        finally:
            renewal.cancel()
            await asyncio.gather(renewal, return_exceptions=True)
