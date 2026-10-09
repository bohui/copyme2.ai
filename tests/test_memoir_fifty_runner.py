"""All 250 original inputs and 50 checkpoints through the reused orchestration.

Only orchestration is exercised: no PostgreSQL, Temporal or model evidence.
"""
import asyncio
from copy import deepcopy
from uuid import uuid4

import pytest

from test_issue14_subscription_runner import Session, Storage, REVISION
from scripts import issue14_subscription_runner as module
from scripts.issue14_subscription_transport import SubscriptionLimits, SubscriptionRun
from scripts.memoir_fifty_readback import CASE_IDS, FiftyReadback, case_plans_for_run


class CoverageStorage(Storage):
    def profile(self):
        return {'preferred_language': self.plan['language']}

    def family_context(self, project_id):
        return {'project_id': project_id, 'people': [], 'relationships': []}

    def place_journey(self):
        return {}


class FiftySession(Session):
    def __init__(self, tmp_path, *, case_seconds=10, global_seconds=20):
        super().__init__()
        self.run = SubscriptionRun.create(reservation_root=tmp_path, run_id=str(uuid4()),
            source_revision=REVISION, limits=SubscriptionLimits(3000, global_seconds),
            case_ids=CASE_IDS, case_limits=SubscriptionLimits(600, case_seconds))
        self.evaluation_profile = 'subscription_fifty'
        self.case_ids = CASE_IDS
        self.case_plans = case_plans_for_run(self.run.run_id)
        self.bridges = {case: FiftyReadback(case_id=case, run_id=self.run.run_id,
            project_id=plan['project_id'], source_revision=REVISION) for case, plan in self.case_plans.items()}
        self.storages = {case: CoverageStorage(self, plan) for case, plan in self.case_plans.items()}

    def activate_round(self, case, ordinal):
        if ordinal == 1:
            self.run.start_case(case)
        return super().activate_round(case, ordinal)

    def finish_case(self, case):
        self.events.append(('finish_case', case))
        self.run.finish_case(case)


@pytest.fixture
def campaign(tmp_path, monkeypatch):
    allowed = []
    def verify(session):
        if session not in allowed:
            raise ValueError('session_unverified')
    monkeypatch.setattr(module, 'assert_owned_subscription_session', verify)
    async def lanes(client, broker, queue, *, single_attempt):
        assert client is broker.temporal_client
        assert single_attempt is True and queue == broker.task_queue
        case, ordinal = broker.active
        class Handle:
            id = f'controlled:{case}:{ordinal}'
            async def result(self):
                broker.storages[case].extracted = ordinal
                return deepcopy(broker.lane_outcome)
        return [Handle()]
    monkeypatch.setattr(module, 'dispatch_memoir_lanes_once', lanes)
    def create(**kwargs):
        session = FiftySession(tmp_path, **kwargs)
        allowed.append(session)
        return session
    return create


def execute(session, **kwargs):
    return asyncio.run(module.SubscriptionProgressiveRunner(session,
        evidence_mode='subscription_fifty').run(**kwargs))


def test_campaign_executes_exact_five_case_order_250_originals_50_saved_checkpoints(campaign):
    session = campaign()
    result = execute(session)
    assert result['status'] == 'completed'
    assert len(result['output']) == 5
    assert result['e2e_status'] == 'partial' and result['e2e_passed'] is False
    assert all(len(c['rounds'][0]['skill_coverage']['skills']) == 7 for c in result['cases'])
    assert [c['case_id'] for c in result['cases']] == list(CASE_IDS)
    assert [c for c, _, _ in session.calls] == [c for c in CASE_IDS for _ in range(50)]
    for case in result['cases']:
        originals = session.bridges[case['case_id']].driver_inputs()['rounds']
        assert len(originals) == len(set(originals)) == len(case['rounds']) == 50
        assert [r['canonical_state']['sources'][-1]['text'] for r in case['rounds']] == originals
        assert [r['milestone'] for r in case['checkpoints']] == list(range(5, 51, 5))
        assert len(case['observation']['output']['source_mapping']) == 50
    assert result['cleanup']['session_closed'] is True
    assert all(c['status'] == 'completed' for c in result['request_accounting']['cases'])
    assert result['request_accounting']['upstream_cancellation_verified'] is False


def test_fifty_session_requires_explicit_runner_profile(campaign):
    session = campaign()
    try:
        with pytest.raises(module.SubscriptionRunnerError, match='evidence_mode_invalid'):
            module.SubscriptionProgressiveRunner(session)
    finally:
        session.run.close()


@pytest.mark.parametrize('milestone', list(range(5, 51, 5)))
def test_every_fifty_checkpoint_is_required_and_partial_evidence_survives(campaign, milestone):
    session = campaign()
    def draft(value):
        if value['milestone'] == milestone:
            value['status'] = 'pending'
    session.draft_hook = draft
    result = execute(session)
    assert result['status'] == 'incomplete' and result['output'] is None
    assert len(result['cases'][0]['checkpoints']) == milestone // 5 - 1
    assert len(session.calls) == milestone
    assert all(c['observation']['output'] is None for c in result['cases'])
    assert all(c['status'] == 'not_started' for c in result['cases'][1:])
    assert result['cleanup']['session_closed'] is True


def test_case_deadline_is_nonreset_and_does_not_claim_upstream_cancellation(campaign):
    session = campaign(case_seconds=.025)
    session.turn_delay = .015
    result = execute(session)
    assert result['status'] == 'incomplete' and len(session.calls) <= 2
    assert result['output'] is None and result['request_accounting']['upstream_cancellation_verified'] is False
    assert result['request_accounting']['cases'][0]['status'] == 'incomplete'
    assert result['request_accounting']['stop_reason'] == 'case_elapsed_limit'
    assert result['cleanup']['session_closed'] is True


def test_case_failure_refuses_next_case_and_no_output_after_cleanup_failure(campaign):
    session = campaign()
    async def fail_cleanup():
        raise RuntimeError('not retained')
    session.close_hook = fail_cleanup
    result = execute(session)
    session.run.close()
    assert result['status'] == 'incomplete' and result['output'] is None
    assert all(c['observation']['output'] is None for c in result['cases'])
    assert result['cleanup']['session_closed'] is False


def test_browser_delivery_submits_every_original_once_without_direct_duplicate(campaign):
    session = campaign()
    class Browser:
        turns_enabled = True
        def __init__(self):
            self.submitted = []
            self.observed = []
        async def turn(self, case, ordinal, text):
            assert session.active == (case, ordinal)
            self.submitted.append((case, ordinal, text))
            plan = session.case_plans[case]
            return await session.turn(session.storages[case], text,
                project_id=plan['project_id'], language=plan['language'], client_turn_id=str(uuid4()),
                include_trajectory=True, evaluation=session.bridges[case].before_round(case, ordinal),
                conversation_text=text, source_kind='narrator_chat')
        async def observe_case(self, case):
            # All persisted checkpoints exist before rendering, and the case
            # budget remains active until this actual observer settles.
            assert len(session.storages[case].sources) == 50
            assert len(session.storages[case].drafts) == 10
            assert session.run.snapshot()['active_case_id'] == case
            self.observed.append(case)
            return {'status': 'partial', 'e2e_passed': False}
    session.browser_readback = browser = Browser()
    result = execute(session)
    assert result['status'] == 'completed'
    assert len(browser.submitted) == len(session.calls) == 250
    assert browser.observed == list(CASE_IDS)
    assert all(r['turn_delivery'] == 'browser_form' for c in result['cases'] for r in c['rounds'])
    assert result['e2e_passed'] is False


def test_runner_retains_planned_family_but_grades_actual_runtime_denial(campaign):
    session = campaign()
    def denied(value):
        value['trajectory']['steps'] = [
            {'action': 'authorization.context', 'output': {'family_enabled': False}}]
    session.turn_hook = denied
    result = execute(session)
    case = result['cases'][0]
    assert result['status'] == 'completed'
    assert all(r['planned_family_enabled'] is True for r in case['rounds'])
    assert all(r['skill_coverage']['family_enabled'] is False for r in case['rounds'])
    assert case['skill_coverage']['family_entitlement']['failed_rounds'] == list(range(1, 51))


def test_missing_runtime_family_decision_is_unavailable(campaign):
    result = execute(campaign())
    for case in result['cases']:
        assert all(r['skill_coverage']['family_enabled'] is None for r in case['rounds'])
        assert case['skill_coverage']['family_entitlement']['unavailable_rounds'] == list(range(1, 51))
