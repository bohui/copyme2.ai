import copy
import json
from pathlib import Path

import pytest


def proposal(family=True, **kwargs):
    from scripts.fifty_round_budget_contract import build_budget_proposal
    return build_budget_proposal(family_enabled=family, **kwargs)


def zero_counts():
    from scripts.fifty_round_budget_contract import STAGES
    return {stage: 0 for stage in STAGES}


def test_explicit_unapproved_proposal_counts_all_roles_and_repairs():
    value = proposal()
    assert value['approval_status'] == 'unapproved'
    assert value['live_execution_authorized'] is False
    assert value['completion_guaranteed'] is False
    assert value['input_count'] == 50
    assert value['checkpoint_rounds'] == list(range(5, 51, 5))
    assert value['maximum_worker_requests'] == 511
    assert value['worker_stage_limits'] == {
        'collector': 50, 'broad_workspace': 50, 'canonical_extraction': 50,
        'initial_locale': 1, 'focused_place': 50, 'focused_family': 150,
        'event_preparation': 100, 'composer_draft': 30, 'composer_review': 30}
    assert value['proposed_limits'] == {'maximum_actual_requests': 600,
        'maximum_preparation_requests': 100, 'wall_seconds': 7200,
        'request_seconds': 60, 'concurrency': 1, 'transport_retries': 0,
        'activity_redeliveries': 0, 'account_failover': False}
    assert value['semantic_repair_allowance'] == {'family': 100, 'composer_draft': 20, 'composer_review': 20}
    assert value['actual_send_headroom_after_maximum_worker_requests'] == 89
    assert value['hard_token_or_monetary_limit_enforced'] is False
    assert value['runtime_enforcement'] == 'not_implemented_by_this_contract'
    assert value['prior_canary_approval_reusable'] is False
    json.dumps(value, allow_nan=False)


def test_family_off_and_prepare_allowance_are_explicit_without_changing_old_canary():
    assert proposal(False)['maximum_worker_requests'] == 361
    assert proposal(False)['worker_stage_limits']['focused_family'] == 0
    value = proposal(max_preparation_requests=50)
    assert value['maximum_worker_requests'] == 461
    assert value['actual_send_headroom_after_maximum_worker_requests'] == 139
    from scripts.fifty_round_budget_contract import PRESERVED_CANARY
    assert PRESERVED_CANARY == {'maximum_actual_requests': 80, 'wall_seconds': 900, 'request_seconds': 60}
    assert value['old_canary_runtime_compatible'] is False


@pytest.mark.parametrize('kwargs', [
    {'family_enabled': 1}, {'family_enabled': None},
    {'max_actual_requests': True}, {'max_actual_requests': -1},
    {'wall_seconds': float('nan')}, {'wall_seconds': 0},
    {'request_seconds': 0}, {'request_seconds': 7201},
    {'max_preparation_requests': -1}, {'max_preparation_requests': 2.5},
])
def test_invalid_or_ambiguous_caps_are_rejected(kwargs):
    from scripts.fifty_round_budget_contract import build_budget_proposal
    params = {'family_enabled': True, **kwargs}
    with pytest.raises(ValueError): build_budget_proposal(**params)


def test_routing_preserves_latest_main_policy_and_records_unknown_wire_identity():
    routing = proposal()['routing']
    assert routing['intent'] == 'preserve_latest_main_role_policy'
    for role in ('collector', 'broad_workspace', 'focused_place', 'focused_family', 'initial_locale'):
        assert routing['stages'][role]['configuration_alias'] == 'gpt-5.6-luna-pooled'
        assert routing['stages'][role]['configuration_reasoning'] == 'max'
        assert routing['stages'][role]['verified_wire_model'] is None
    for role in ('canonical_extraction', 'event_preparation', 'composer_draft', 'composer_review'):
        assert routing['stages'][role]['configuration_alias'] == 'memoir-luna-low'
        assert routing['stages'][role]['configuration_reasoning'] == 'low'
    assert routing['runtime_verified'] is False
    assert routing['old_uniform_low_override_is_latest_main_e2e'] is False
    assert routing['account']['name'] == 'erduoy'
    assert routing['account']['consumer_and_account_binding_verified'] is False


def test_unknown_actual_usage_is_never_substituted_with_worker_or_guard_counts():
    from scripts.fifty_round_budget_contract import assess_budget_observations
    counts = zero_counts()
    counts['collector'] = 20
    report = assess_budget_observations(proposal(), worker_requests_by_stage=counts, actual_requests=None)
    assert report['actual_requests'] is None
    assert report['remaining_actual_requests'] is None
    assert report['counts_within_proposed_limits'] is None
    assert 'actual_usage_unknown' in report['findings']
    assert report['live_execution_authorized'] is False
    assert report['worker_requests'] == 20


def test_exhausted_and_unsettled_requests_never_grant_admission():
    from scripts.fifty_round_budget_contract import assess_budget_observations
    report = assess_budget_observations(proposal(), worker_requests_by_stage=zero_counts(),
        actual_requests=600, unsettled_requests=1)
    assert report['remaining_actual_requests'] == 0
    assert report['counts_within_proposed_limits'] is True
    assert set(report['findings']) == {'actual_request_limit_reached', 'unsettled_requests'}
    assert report['live_execution_authorized'] is False


def test_preparation_and_actual_limits_are_independent():
    from scripts.fifty_round_budget_contract import assess_budget_observations
    counts = zero_counts()
    counts['event_preparation'] = 101
    report = assess_budget_observations(proposal(), worker_requests_by_stage=counts, actual_requests=102)
    assert report['counts_within_proposed_limits'] is False
    assert 'stage_limit_exceeded:event_preparation' in report['findings']
    report = assess_budget_observations(proposal(), worker_requests_by_stage=zero_counts(), actual_requests=601)
    assert report['counts_within_proposed_limits'] is False
    assert 'actual_request_limit_exceeded' in report['findings']


def test_missing_stages_tampering_and_non_integer_usage_are_rejected():
    from scripts.fifty_round_budget_contract import assess_budget_observations
    bad = proposal()
    bad['live_execution_authorized'] = True
    with pytest.raises(ValueError):
        assess_budget_observations(bad, worker_requests_by_stage=zero_counts(), actual_requests=0)
    for counts in ({'collector': 1}, {**zero_counts(), 'judge': 1}, {**zero_counts(), 'collector': True}):
        with pytest.raises(ValueError):
            assess_budget_observations(proposal(), worker_requests_by_stage=counts, actual_requests=0)
    for count in (True, -1, float('inf')):
        with pytest.raises(ValueError):
            assess_budget_observations(proposal(), worker_requests_by_stage=zero_counts(), actual_requests=count)


def test_outputs_are_independent_and_assessment_does_not_mutate_inputs():
    from scripts.fifty_round_budget_contract import assess_budget_observations
    value = proposal()
    saved = copy.deepcopy(value)
    counts = zero_counts()
    assess_budget_observations(value, worker_requests_by_stage=counts, actual_requests=0)
    assert value == saved and counts == zero_counts()
    value['routing']['stages']['collector']['configuration_reasoning'] = 'low'
    assert proposal()['routing']['stages']['collector']['configuration_reasoning'] == 'max'


def test_audit_source_pins_match_this_reviewed_derivation():
    # V1 is an immutable historical derivation, not a hash lock on all future
    # checkouts. Keep this existing gate strict: validate its original Git
    # objects AND the separately reviewed versioned current source contract.
    from scripts.issue14_subscription_source_contract_v6 import audit_subscription_source_v6
    root = Path(__file__).resolve().parents[1]
    report = audit_subscription_source_v6(root)
    assert report['historical_derivation_integrity_verified'] is True
    assert report['current_source_matches_reviewed_snapshot'] is True
    assert report['source_gate_passed'] is True
    assert report['live_execution_authorized'] is False
    assert report['provider_capability_verified'] is False


def test_contract_module_is_standard_library_only_without_runtime_or_dispatch_imports():
    import ast
    path = Path(__file__).resolve().parents[1] / 'scripts/fifty_round_budget_contract.py'
    tree = ast.parse(path.read_text())
    imported = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert imported == {'collections.abc', 'copy'}
    assert not any(isinstance(node, ast.Import) for node in ast.walk(tree))
    assert not any(isinstance(node, (ast.AsyncFunctionDef, ast.Await)) for node in ast.walk(tree))
    assert not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        and node.func.id in {'open', 'eval', 'exec', '__import__'} for node in ast.walk(tree))


def test_lower_proposed_cap_reports_negative_headroom_without_granting_execution():
    value = proposal(max_actual_requests=80, wall_seconds=900)
    assert value['actual_send_headroom_after_maximum_worker_requests'] == -431
    assert value['approval_status'] == 'unapproved'
    assert value['live_execution_authorized'] is False
    assert value['old_canary_runtime_compatible'] is False


@pytest.mark.parametrize(('path', 'replacement'), [
    (('worker_stage_limits', 'collector'), 50.0),
    (('live_execution_authorized',), 0),
    (('live_execution_authorized',), 0.0),
    (('input_count',), 50.0),
    (('owner_project_count',), True),
    (('checkpoint_rounds', 0), 5.0),
    (('proposed_limits', 'concurrency'), True),
    (('proposed_limits', 'transport_retries'), False),
    (('proposed_limits', 'account_failover'), 0),
    (('call_graph', 'locale_I', 0), False),
    (('routing', 'runtime_verified'), 0),
    (('routing', 'payload_model_has_precedence'), 1),
    (('token_and_cost_status', 'request_deadlines_are_spending_caps'), 0),
    (('preserved_canary', 'maximum_actual_requests'), 80.0),
])
def test_equal_but_type_tampered_proposal_literals_are_rejected(path, replacement):
    from scripts.fifty_round_budget_contract import assess_budget_observations
    value = proposal()
    parent = value
    for key in path[:-1]:
        parent = parent[key]
    assert parent[path[-1]] == replacement
    assert type(parent[path[-1]]) is not type(replacement)
    parent[path[-1]] = replacement
    with pytest.raises(ValueError):
        assess_budget_observations(value, worker_requests_by_stage=zero_counts(), actual_requests=0)


@pytest.mark.parametrize('location', ['root', 'dict', 'list', 'string', 'key'])
def test_proposal_rejects_subclasses_of_json_literal_types(location):
    from scripts.fifty_round_budget_contract import assess_budget_observations
    class DictSubclass(dict): pass
    class ListSubclass(list): pass
    class StringSubclass(str): pass
    value = proposal()
    if location == 'root':
        value = DictSubclass(value)
    elif location == 'dict':
        value['worker_stage_limits'] = DictSubclass(value['worker_stage_limits'])
    elif location == 'list':
        value['checkpoint_rounds'] = ListSubclass(value['checkpoint_rounds'])
    elif location == 'string':
        value['approval_status'] = StringSubclass('unapproved')
    else:
        value[StringSubclass('approval_status')] = value.pop('approval_status')
    with pytest.raises(ValueError):
        assess_budget_observations(value, worker_requests_by_stage=zero_counts(), actual_requests=0)


def test_json_roundtrip_and_reordered_keys_preserve_valid_proposal():
    from scripts.fifty_round_budget_contract import assess_budget_observations
    value = json.loads(json.dumps(proposal(), sort_keys=True, allow_nan=False))
    value['worker_stage_limits'] = dict(reversed(list(value['worker_stage_limits'].items())))
    result = assess_budget_observations(value, worker_requests_by_stage=zero_counts(), actual_requests=0)
    assert result['live_execution_authorized'] is False
    assert result['counts_within_proposed_limits'] is True
