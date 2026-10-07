"""Canonical evaluation callback around the existing authenticated turn seam.

The disposable native fixture supplies UserStorage, normal CodexRuntime and
the real Temporal client/broker. This module does not replace event extraction
or composition and never loads configured credentials or judge settings.
"""
import asyncio
import math
from uuid import uuid4

from apps.api.agent_storage import UserStorage
from apps.api.recall import private_draft_cadence
from scripts.task_runtime import dispatch_memoir_lanes_once


class CanonicalEvaluationDriver:
    def __init__(self, *, storage, runtime, broker, temporal_client, task_queue):
        if not isinstance(storage, UserStorage):
            raise TypeError('Canonical evaluation requires UserStorage')
        self.storage = storage
        self.runtime = runtime
        self.broker = broker
        self.temporal_client = temporal_client
        self.task_queue = task_queue

    async def run_case(self, *, case_id, project_id, rounds, language,
                       evidence_mode, settle_timeout=60, progress=None,
                       before_round=None, single_attempt=False, live_worker=None):
        """Submit original turns and await durable extraction/draft workflows.

        Receipts contain synthetic story bytes. The caller owns fixture setup,
        provider/worker isolation, tracing and scoring. A mock run cannot become
        live-model evidence by changing a label.
        """
        if evidence_mode != 'mock_only':
            from scripts.canary_worker import CanaryWorker
            if (evidence_mode != 'guarded_live_canary' or not isinstance(live_worker, CanaryWorker)
                    or not single_attempt or len(rounds) != 5 or not self.task_queue.startswith('canary-')):
                raise ValueError('Live evaluation requires a verified provider accounting adapter')
            live_worker.assert_live_ready()
        if (not isinstance(rounds, (list, tuple)) or not 1 <= len(rounds) <= 50
                or any(not isinstance(text, str) or not text.strip() for text in rounds)):
            raise ValueError('A case requires 1 to 50 nonempty original inputs')
        if (type(settle_timeout) not in (int, float)
                or not math.isfinite(settle_timeout) or settle_timeout <= 0):
            raise ValueError('A finite positive settle timeout is required')
        initial = await asyncio.to_thread(self.storage.memory_events, project_id)
        if initial['sources'] or initial['events'] or initial['completed_rounds']:
            raise ValueError('Each evaluation case requires a fresh synthetic project')
        cadence = private_draft_cadence()
        records, checkpoints, workflow_ids = [], [], set()
        for ordinal, text in enumerate(rounds, 1):
            correlation = before_round(case_id, ordinal) if before_round else None
            record = {'round': ordinal, 'status': 'started', 'background_settled': False}
            records.append(record)
            if progress is not None:
                await progress({'status': 'running', 'rounds': records, 'checkpoints': checkpoints})
            try:
                result = await self.runtime.turn(self.storage, text, project_id=project_id,
                    language=language, client_turn_id=str(uuid4()), include_trajectory=True,
                    evaluation=correlation, conversation_text=text, source_kind='narrator_chat')
            except BaseException as error:
                record.update(status='failed', error_class=type(error).__name__,
                              trajectory=getattr(error, 'trajectory', None))
                if progress is not None:
                    await progress({'status': 'incomplete', 'rounds': records, 'checkpoints': checkpoints})
                raise
            record.update(reply=result.get('reply'), trajectory=result.get('trajectory'),
                          accepted_source_id=result.get('accepted_source_id'), status='delivered')
            if not result.get('accepted_source_id') or not result.get('reply'):
                record['status'] = 'failed'
                if progress is not None:
                    await progress({'status': 'incomplete', 'rounds': records, 'checkpoints': checkpoints})
                raise RuntimeError(f'Canonical conversation round {ordinal} was not delivered')
            if progress is not None:
                await progress({'status': 'pending_settlement', 'rounds': records,
                                'checkpoints': checkpoints})
            async with asyncio.timeout(settle_timeout):
                while True:
                    handles = await dispatch_memoir_lanes_once(
                        self.temporal_client, self.broker, self.task_queue, single_attempt=single_attempt)
                    workflow_ids.update(h.id for h in handles)
                    outcomes = await asyncio.gather(*(h.result() for h in handles))
                    if any(r.get('status') == 'retry_required' for r in outcomes):
                        raise RuntimeError('Canonical background lane requires retry')
                    view = await asyncio.to_thread(self.storage.memory_events, project_id)
                    if view['completed_rounds'] != ordinal:
                        raise RuntimeError('Canonical completed-round count differs from the case')
                    if view['processing']['extracted_through'] < ordinal:
                        if single_attempt:
                            raise RuntimeError('Canary extraction did not settle without redelivery')
                        await asyncio.sleep(.05)
                        continue
                    if ordinal % cadence == 0:
                        draft = await asyncio.to_thread(self.storage.saved_memoir_draft, project_id, language)
                        if draft['covered_round'] < ordinal:
                            if single_attempt:
                                raise RuntimeError('Canary draft did not settle without redelivery')
                            await asyncio.sleep(.05)
                            continue
                        checkpoints.append({'milestone': ordinal, 'draft': draft})
                    break
            records[-1]['background_settled'] = True
            records[-1]['status'] = 'completed'
            records[-1]['canonical_state'] = view
            if progress is not None:
                await progress({'status': 'running', 'rounds': records,
                                'checkpoints': checkpoints})
        return {'case_id': case_id, 'project_id': project_id, 'status': 'completed',
                'evidence_mode': evidence_mode, 'rounds': records,
                'checkpoints': checkpoints, 'workflow_ids': sorted(workflow_ids)}
