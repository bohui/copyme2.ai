"""Pure, unapproved budget proposal for one fifty-input backend campaign.

This module reads no environment/files, creates no reservations, imports no app
or provider code, and has no dispatch/admission path. Numerical proposals and
caller-supplied observations are never execution authorization or native proof.
"""
from collections.abc import Mapping
from copy import deepcopy


SCHEMA_VERSION = 'memoir-fifty-budget-proposal/1'
DERIVATION_SOURCE_REVISION = '3a9a339813ed06fb06ba18815bf32b880072314e'
DERIVATION_SOURCE_TREE = '640f47d4ea8d1e8cb52f3198dfb93719cec1457e'
PRESERVED_CANARY = {'maximum_actual_requests': 80, 'wall_seconds': 900, 'request_seconds': 60}
STAGES = ('collector', 'broad_workspace', 'canonical_extraction', 'initial_locale',
          'focused_place', 'focused_family', 'event_preparation', 'composer_draft', 'composer_review')
ACCOUNT_BINDING = 'b45a626039b65a68ace979d43215b7c4ea36048e5ee32744034e4134905961fa'

# A fresh latest-main plan must revalidate these source bytes. These are an
# audit snapshot, not a claim about the user's current native configuration.
DERIVATION_FILE_SHA256 = {
    'apps/api/codex_runtime.py': 'c55c8be799808b61ff71e433e6e6baf9267d56ef802cd5337f825c9621fdc8a9',
    'apps/api/codex_worker_service.py': 'f4ed2e955b1bce1796ca91f8142454245e34da3cfefa5b4f660e501c25495d9a',
    'apps/api/memory_event_worker.py': '9eaa6d5687ae16bacfae98cd610b213f08a7f271183a96318dcae011979e5aa8',
    'apps/api/memory_events.py': 'cc626253dfecb2fa8f75d846334167f0ebd4e1321f2e092de6fb352918dcc403',
    'apps/api/canonical_composer.py': '569b08c45a7aeb9c84b9bd7f32627a174f577a39256d9158d7d239b1a44ca17f',
    'apps/api/memoir_preview.py': '523c0ce0725faa48290e9df8000071e3ef3e8d8ceaa697f4e0fb54b9df1b1d96',
    'apps/api/temporal_workflows.py': 'c6a47bbbe4b9d14ef3f744f57d1d75c39e667ef736ceed2504ae873f2962daa8',
    'apps/api/codex_agent.py': '1eb0c965c77a1d8882f34ea7131a863e35244b9bbbd30650010545c270ea1188',
    'scripts/canary_worker.py': 'fcd88be57ef025b7e6e0a6c74b5a08bb16de6d2b72c0b66423ac29c0e517cf70',
    'scripts/canary_send_guard.py': '42594b4a928560dfc667ec952c68fe7df25deffc04d180b441c2f6a15227761e',
    'scripts/canary_gateway_actor.py': '641b3cbd4fb568eda1335469f4fd989262c85d08df48a8d161589ca47aca5831',
    'compose.yml': 'd7ecd8668c8604078103f90771487b37c1626b9634add81186f25d37a307a53d',
    '.env.example': '812a42bcd08b691a05bc5747ce79929ac36be40088386367afddafe9d2859bbc',
}


def _integer(name, value, *, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(f'{name} must be an integer of at least {minimum}')
    return value


def _routing():
    stages = {}
    for stage in STAGES:
        background = stage in {'canonical_extraction', 'event_preparation', 'composer_draft', 'composer_review'}
        effort_setting = ('MEMORY_SPARK_AUTHOR_TIMELINE_REASONING_EFFORT' if stage == 'canonical_extraction'
            else 'MEMORY_SPARK_MEMOIR_COMPOSER_REASONING_EFFORT' if background
            else 'MEMORY_SPARK_LLM_REASONING_EFFORT')
        stages[stage] = {
            'model_setting': 'MEMORY_SPARK_MEMOIR_COMPOSER_MODEL' if background else 'MEMORY_SPARK_LLM_MODEL',
            'configuration_alias': 'memoir-luna-low' if background else 'gpt-5.6-luna-pooled',
            'reasoning_setting': effort_setting,
            'configuration_reasoning': 'low' if background else 'max',
            'verified_native_alias': None, 'verified_wire_model': None, 'verified_native_reasoning': None,
        }
    return {'intent': 'preserve_latest_main_role_policy', 'stages': stages,
        'runtime_verified': False, 'aliases_describe': 'Compose and example configuration, not verified native settings',
        'payload_model_has_precedence': True, 'global_worker_reasoning_override_has_precedence': True,
        'code_fallback_caveats': [
            'CodexRuntime composer fallback is legal2ai-luna-low when the composer model setting is absent',
            'CodexWorker background model falls back to its ordinary model when the composer setting is absent'],
        'account': {'name': 'erduoy', 'proposed_binding_sha256': ACCOUNT_BINDING,
            'consumer_and_account_binding_verified': False,
            'scope': 'one proposed existing subscription account; both role aliases must be verified'},
        'old_uniform_low_override_is_latest_main_e2e': False,
        'uniform_model_or_effort_override': 'separate experiment requiring explicit approval, not an automatic substitution'}


def build_budget_proposal(*, family_enabled, max_actual_requests=600,
        wall_seconds=7200, request_seconds=60, max_preparation_requests=100):
    """Describe proposed stops; never change or authorize the old canary runtime."""
    if type(family_enabled) is not bool:
        raise ValueError('family_enabled must be an explicit boolean')
    for name, value in (('max_actual_requests', max_actual_requests),
            ('wall_seconds', wall_seconds), ('request_seconds', request_seconds)):
        _integer(name, value, minimum=1)
    _integer('max_preparation_requests', max_preparation_requests)
    if request_seconds > wall_seconds:
        raise ValueError('Request deadline cannot exceed the run deadline')
    limits = dict(zip(STAGES, (50, 50, 50, 1, 50, 150 if family_enabled else 0,
        max_preparation_requests, 30, 30)))
    maximum_workers = sum(limits.values())
    return {
        'schema_version': SCHEMA_VERSION, 'approval_status': 'unapproved',
        'live_execution_authorized': False, 'completion_guaranteed': False,
        'runtime_enforcement': 'not_implemented_by_this_contract',
        'input_count': 50, 'owner_project_count': 1, 'family_enabled': family_enabled,
        'checkpoint_rounds': list(range(5, 51, 5)),
        'coverage_scope': 'synthetic-entitlement backend campaign; not the ordinary 20-round free/browser gate',
        'proposed_limits': {'maximum_actual_requests': max_actual_requests,
            'maximum_preparation_requests': max_preparation_requests,
            'wall_seconds': wall_seconds, 'request_seconds': request_seconds,
            'concurrency': 1, 'transport_retries': 0, 'activity_redeliveries': 0, 'account_failover': False},
        'worker_stage_limits': limits, 'maximum_worker_requests': maximum_workers,
        'semantic_repair_allowance': {'family': 100 if family_enabled else 0,
            'composer_draft': 20, 'composer_review': 20},
        'actual_send_headroom_after_maximum_worker_requests': max_actual_requests - maximum_workers,
        'call_graph': {'formula': 'L = I + 150 + Qp + Qf + P + C',
            'locale_I': [0, 1], 'place_Qp': [0, 50], 'family_Qf': [0, 150 if family_enabled else 0],
            'preparation_P': 'sum of actual uncached dirty-active-event preparation dispatches',
            'composer_C_successful_changed_checkpoint_scenario': [20, 60],
            'cached_or_incomplete_checkpoint_calls': 'may be lower; never infer completeness from counts',
            'model_index_calls': 0,
            'actual_vs_logical': 'Codex tool continuations can produce multiple actual sends per worker turn'},
        'preparation_warning': {'automatic_50_call_bound': False,
            'maximum_event_proposals_per_extraction': 100,
            'conditional_5000_bound': 'requires exactly 50 extraction commits, stable policy/config, no outside edits, successful sequential checkpoints and no uncached replay',
            'full_history_reprepare_scenario_per_event_per_round': 275,
            'proposed_stop': max_preparation_requests},
        'required_runtime_controls': [
            'one shared immutable actual-send reservation across every role and continuation',
            'reserve before each actual upstream send; never reset by restarting or splitting runs',
            'independent per-stage worker caps including all preparations and semantic repairs',
            'unknown, failed or unsettled usage holds reservations and stops future sends',
            'stop on quota/provider/protocol failure, cancellation, deadline or cap exhaustion',
            'one activity attempt, one concurrent model operation and preparation concurrency one',
            'a shared worker-boundary counter covering timeline direct POST and composer calls'],
        'excluded_calls': ['judge', 'photo', 'geocoding', 'hosted_remote_tools', 'paid_provider_routes', 'voice'],
        'routing': _routing(),
        'hard_token_or_monetary_limit_enforced': False,
        'token_and_cost_status': {'input_token_bound': None, 'output_token_bound': None,
            'reasoning_token_bound': None, 'per_request_output_limit': None,
            'verified_rates': None, 'maximum_cost': None, 'currency': None,
            'request_deadlines_are_spending_caps': False},
        'old_canary_runtime_compatible': False, 'prior_canary_approval_reusable': False,
        'preserved_canary': dict(PRESERVED_CANARY),
        'derivation_source_revision': DERIVATION_SOURCE_REVISION,
        'derivation_source_tree': DERIVATION_SOURCE_TREE,
        'derivation_file_sha256': dict(DERIVATION_FILE_SHA256),
        'revalidate_source_before_latest_main_run': True,
        'blockers': ['specific_fifty_round_envelope_not_approved',
            'fifty_round_runtime_admission_not_implemented_or_reviewed',
            'native_role_alias_reasoning_and_provider_mapping_unverified',
            'existing_consumer_and_single_account_binding_unverified',
            'hard_token_and_cost_bounds_unavailable',
            'native_accounting_and_process_exit_validation_pending'],
    }


def _same_json_literal(value, expected):
    """Compare generated JSON structure without bool/int/float coercion."""
    if type(value) is not type(expected):
        return False
    if type(expected) is dict:
        return (all(type(key) is str for key in value)
            and value.keys() == expected.keys()
            and all(_same_json_literal(value[key], item) for key, item in expected.items()))
    if type(expected) is list:
        return (len(value) == len(expected)
            and all(_same_json_literal(item, template) for item, template in zip(value, expected)))
    return type(expected) in (str, int, bool, type(None)) and value == expected


def _validate_proposal(proposal):
    if type(proposal) is not dict:
        raise ValueError('A generated unapproved proposal is required')
    try:
        limits = proposal['proposed_limits']
        if type(limits) is not dict:
            raise ValueError('Proposal limits must be a JSON object')
        expected = build_budget_proposal(family_enabled=proposal['family_enabled'],
            max_actual_requests=limits['maximum_actual_requests'], wall_seconds=limits['wall_seconds'],
            request_seconds=limits['request_seconds'], max_preparation_requests=limits['maximum_preparation_requests'])
    except (KeyError, TypeError):
        raise ValueError('Incomplete budget proposal') from None
    if not _same_json_literal(proposal, expected):
        raise ValueError('Budget proposal was changed or made authorizing')


def assess_budget_observations(proposal, *, worker_requests_by_stage,
        actual_requests, unsettled_requests=0):
    """Check supplied totals without treating them as verified provider evidence.

    Unknown actual usage stays unknown. Worker/guard-entry counts are never
    converted to actual requests, tokens or spend. This function cannot dispatch.
    """
    _validate_proposal(proposal)
    if not isinstance(worker_requests_by_stage, Mapping) or set(worker_requests_by_stage) != set(STAGES):
        raise ValueError('All known stages must be reported explicitly; unsupported stages are forbidden')
    counts = {stage: _integer(stage, worker_requests_by_stage[stage]) for stage in STAGES}
    _integer('unsettled_requests', unsettled_requests)
    if actual_requests is not None:
        _integer('actual_requests', actual_requests)
    findings = []
    stage_overruns = [stage for stage in STAGES if counts[stage] > proposal['worker_stage_limits'][stage]]
    findings.extend('stage_limit_exceeded:' + stage for stage in stage_overruns)
    worker_count = sum(counts.values())
    if worker_count > proposal['maximum_worker_requests']:
        findings.append('worker_request_limit_exceeded')
    actual_limit = proposal['proposed_limits']['maximum_actual_requests']
    if actual_requests is None:
        findings.append('actual_usage_unknown')
    elif actual_requests > actual_limit:
        findings.append('actual_request_limit_exceeded')
    elif actual_requests == actual_limit:
        findings.append('actual_request_limit_reached')
    if unsettled_requests:
        findings.append('unsettled_requests')
    exceeded = bool(stage_overruns or worker_count > proposal['maximum_worker_requests']
        or (actual_requests is not None and actual_requests > actual_limit))
    return {'evidence_scope': 'caller_supplied_offline_totals_not_native_proof',
        'live_execution_authorized': False, 'approval_status': 'unapproved',
        'worker_requests_by_stage': deepcopy(counts), 'worker_requests': worker_count,
        'actual_requests': actual_requests, 'unsettled_requests': unsettled_requests,
        'remaining_actual_requests': None if actual_requests is None else max(0, actual_limit - actual_requests),
        'counts_within_proposed_limits': False if exceeded else None if actual_requests is None else True,
        'findings': findings, 'hard_token_or_monetary_limit_enforced': False}
