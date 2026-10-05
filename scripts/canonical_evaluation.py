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
                       evidence_mode, settle_timeout=60):
        """Submit original turns and await durable extraction/draft workflows.

        Receipts contain synthetic story bytes. The caller owns fixture setup,
        provider/worker isolation, tracing and scoring. A mock run cannot become
        live-model evidence by changing a label.
        """
        if evidence_mode != 'mock_only':
            raise ValueError('Live evaluation requires a verified provider accounting adapter')
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
            result = await self.runtime.turn(self.storage, text, project_id=project_id,
                language=language, client_turn_id=str(uuid4()), include_trajectory=True,
                conversation_text=text, source_kind='narrator_chat')
            if not result.get('accepted_source_id') or not result.get('reply'):
                raise RuntimeError(f'Canonical conversation round {ordinal} was not delivered')
            records.append({'round': ordinal, 'reply': result['reply'],
                            'trajectory': result.get('trajectory')})
            async with asyncio.timeout(settle_timeout):
                while True:
                    handles = await dispatch_memoir_lanes_once(
                        self.temporal_client, self.broker, self.task_queue)
                    workflow_ids.update(h.id for h in handles)
                    outcomes = await asyncio.gather(*(h.result() for h in handles))
                    if any(r.get('status') == 'retry_required' for r in outcomes):
                        raise RuntimeError('Canonical background lane requires retry')
                    view = await asyncio.to_thread(self.storage.memory_events, project_id)
                    if view['completed_rounds'] != ordinal:
                        raise RuntimeError('Canonical completed-round count differs from the case')
                    if view['processing']['extracted_through'] < ordinal:
                        await asyncio.sleep(.05)
                        continue
                    if ordinal % cadence == 0:
                        draft = await asyncio.to_thread(self.storage.saved_memoir_draft, project_id, language)
                        if draft['covered_round'] < ordinal:
                            await asyncio.sleep(.05)
                            continue
                        checkpoints.append({'milestone': ordinal, 'draft': draft})
                    break
        return {'case_id': case_id, 'project_id': project_id, 'status': 'completed',
                'evidence_mode': evidence_mode, 'rounds': records,
                'checkpoints': checkpoints, 'workflow_ids': sorted(workflow_ids)}
