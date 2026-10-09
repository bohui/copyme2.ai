"""Offline readbacks and grading never dispatch a model or external search."""
from copy import deepcopy
import json

import pytest

from scripts import memoir_fifty_coverage as coverage

PROJECT = 'synthetic-project'


def observed(round_number=1):
    source = {'id': 'source-one', 'version': 1, 'text': 'I was born in Hobart.',
              'project_id': PROJECT, 'sequence': round_number}
    place = {'schema_version': 1, 'place': 'Hobart',
             'hierarchy': ['Earth', 'Australia', 'Tasmania', 'Hobart'],
             'granularity': 'city', 'revision': 1, 'source_sequence': round_number,
             'latitude': -42.8821, 'longitude': 147.3272}
    return dict(project_id=PROJECT, round_number=round_number,
        runtime_result={'accepted_source_id': source['id'], 'reply': 'Tell me more.',
            'trace': [{'skill': 'memoir-memory-context', 'status': 'completed'}],
            'place_journeys': [place]},
        profile={'story_focus': {'life_stage': 'baby'}},
        family_context=None, place_journey=place, family_enabled=True,
        canonical_state={'project_id': PROJECT, 'completed_rounds': round_number,
            'sources': [source], 'processing': {'extracted_through': round_number, 'pending_inputs': 0},
            'events': [{'id': 'event-one', 'revision': 1, 'life_stage': 'baby',
                'source_refs': [{'source_id': source['id'], 'version': 1, 'quote': source['text']}],
                'stage_evidence': [{'source_id': source['id'], 'version': 1, 'quote': source['text']}]}]})


def test_records_seven_skills_without_claiming_browser_photo_or_semantic_pass(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('No external geocoder may be called')
    monkeypatch.setattr('apps.api.place_groups.search_place_details', forbidden)
    data = observed()
    before = deepcopy(data)
    result = coverage.round_skill_coverage(**data)
    assert data == before
    assert set(result['skills']) == set(coverage.SKILLS)
    assert result['skills']['memoir-author-timeline']['status'] == 'observed'
    assert result['skills']['memoir-author-timeline']['current_source_events'] == 1
    assert result['skills']['memoir-place-groups']['scope'] == 'deterministic_service_only'
    assert result['skills']['memoir-place-groups']['browser_status'] == 'not_run'
    assert result['skills']['place-photo-research']['status'] == 'not_run'
    assert result['semantic_judge']['status'] == 'not_run'
    assert result['status'] == 'partial' and result['full_e2e_pass'] is False
    json.dumps(result)


def test_round_collection_does_not_load_hidden_expected(monkeypatch):
    monkeypatch.setattr(coverage, '_load_expected', lambda: pytest.fail('expected leaked into collection'))
    assert coverage.round_skill_coverage(**observed())['round'] == 1


def test_absent_and_unresolved_readbacks_are_not_passes():
    data = observed()
    data.update(profile=None, place_journey=None)
    data['runtime_result']['place_journeys'] = []
    data['canonical_state']['processing']['pending_inputs'] = 1
    result = coverage.round_skill_coverage(**data)
    assert result['skills']['memoir-memory-context']['status'] == 'unavailable'
    assert result['skills']['memoir-author-timeline']['status'] == 'unavailable'
    assert result['skills']['memoir-place-journey']['status'] == 'not_observed'
    assert result['skills']['memoir-place-groups']['status'] == 'not_run'


@pytest.mark.parametrize('field', ['family_context', 'canonical_state'])
def test_cross_project_readbacks_fail_closed(field):
    data = observed()
    data[field] = {'project_id': 'another-project'}
    with pytest.raises(ValueError, match='project'):
        coverage.round_skill_coverage(**data)


def test_family_update_claim_requires_matching_saved_revision():
    data = observed(3)
    data['runtime_result']['family_context_update'] = {
        'persisted': True, 'revision': 3, 'skills': ['family_tree']}
    data['family_context'] = {'project_id': PROJECT, 'revision': 2,
        'people': [{'id': 'sister', 'name': 'Nora'}], 'relationships': [], 'timeline': []}
    result = coverage.round_skill_coverage(**data)
    assert result['skills']['memoir-family-tree']['status'] == 'unavailable'
    data['family_context']['revision'] = 3
    result = coverage.round_skill_coverage(**data)
    assert result['skills']['memoir-family-tree']['status'] == 'observed'


def test_source_references_must_resolve_exactly_and_stage_needs_own_evidence():
    data = observed()
    data['canonical_state']['events'][0]['source_refs'][0]['quote'] = 'Invented quote'
    result = coverage.round_skill_coverage(**data)
    assert result['skills']['memoir-author-timeline']['status'] == 'unavailable'
    data = observed()
    data['canonical_state']['events'][0]['stage_evidence'] = []
    result = coverage.round_skill_coverage(**data)
    assert result['skills']['memoir-author-timeline']['life_stages'] == []


def test_old_place_cannot_establish_current_turn_persistence():
    data = observed()
    data['place_journey']['source_sequence'] = 0
    result = coverage.round_skill_coverage(**data)
    assert result['skills']['memoir-place-journey']['persisted_current_turn'] is False


def test_case_grades_original_entitlement_boundary_and_keeps_missing_rounds():
    record = coverage.round_skill_coverage(**observed())
    result = coverage.case_skill_coverage(case_id='chengdu-tea-ledger',
        rounds=[{'round': 1, 'skill_coverage': record}])
    assert result['expected_sha256'] == coverage.EXPECTED_SHA256
    assert result['exact_50_rounds'] is False
    assert result['missing_rounds'] == list(range(2, 51))
    assert result['family_entitlement']['failed_rounds'] == [1]
    assert set(result['skills']) == set(coverage.SKILLS)
    assert result['skills']['place-photo-research']['required_rounds'] == [12, 22]
    assert {12, 22}.issubset(result['skills']['place-photo-research']['unavailable_rounds'])
    assert result['full_e2e_pass'] is False


def test_legacy_timeline_and_composer_actions_cannot_be_certified_by_new_lane():
    record = coverage.round_skill_coverage(**observed())
    result = coverage.case_skill_coverage(case_id='harbour-copper-notebook',
        rounds=[{'round': 1, 'skill_coverage': record}])
    assert 1 in result['skills']['memoir-author-timeline']['not_comparable_rounds']
    assert result['original_contract_status'] != 'pass'
    assert 'private_checkpoint_is_not_formal_composition' in result['coverage_gaps']


def test_expected_file_pin_is_checked_only_by_offline_grader(tmp_path, monkeypatch):
    bad = tmp_path / 'expected.json'
    bad.write_text('{}')
    monkeypatch.setattr(coverage, 'EXPECTED_PATH', bad)
    with pytest.raises(ValueError, match='pin'):
        coverage.case_skill_coverage(case_id='harbour-copper-notebook', rounds=[])


def test_duplicate_rounds_are_rejected():
    record = {'round': 1, 'skill_coverage': coverage.round_skill_coverage(**observed())}
    with pytest.raises(ValueError, match='round'):
        coverage.case_skill_coverage(case_id='harbour-copper-notebook', rounds=[record, record])


def test_saved_private_checkpoint_never_proves_formal_composition():
    data = observed(50)
    data['saved_draft'] = {'status': 'ready', 'revision': 10, 'covered_round': 50,
        'updating': False, 'error': None, 'proposal_pending': False,
        'sections': [{'id': 'saved-section', 'content': 'Saved prose'}]}
    result = coverage.round_skill_coverage(**data)
    composer = result['skills']['memoir-composer']
    assert composer['status'] == 'observed'
    assert composer['scope'] == 'saved_private_checkpoint'
    assert composer['legacy_action_verified'] is False
    data['saved_draft']['covered_round'] = 45
    assert coverage.round_skill_coverage(**data)['skills']['memoir-composer']['status'] == 'unavailable'


def test_life_stage_coverage_is_observed_and_not_inferred_from_expected_bands():
    rounds = []
    for ordinal, stage in enumerate(coverage.LIFE_STAGES, 1):
        data = observed(ordinal)
        data['profile']['story_focus']['life_stage'] = stage
        data['canonical_state']['events'] = []
        rounds.append({'round': ordinal, 'skill_coverage': coverage.round_skill_coverage(**data)})
    case = coverage.case_skill_coverage(case_id='harbour-copper-notebook', rounds=rounds)
    assert case['all_life_stages_observed'] is True
    assert case['life_stages_observed'] == list(coverage.LIFE_STAGES)
    assert case['exact_50_rounds'] is False
    empty = coverage.case_skill_coverage(case_id='harbour-copper-notebook', rounds=[])
    assert empty['life_stages_observed'] == [] and empty['all_life_stages_observed'] is False


def test_entitlement_absence_is_unavailable_not_disabled_or_enabled():
    data = observed()
    data['family_enabled'] = None
    result = coverage.case_skill_coverage(case_id='harbour-copper-notebook', rounds=[{
        'round': 1, 'skill_coverage': coverage.round_skill_coverage(**data)}])
    assert result['family_entitlement']['failed_rounds'] == []
    assert result['family_entitlement']['unavailable_rounds'] == list(range(1, 51))


def photo_record(ordinal=12, *, status='observed', called=True, period='', items=None):
    data = observed(ordinal)
    receipt = {'schema_version': 'memoir-fifty-photo-receipt/1',
        'run_id': 'synthetic-run', 'source_revision': 'a' * 40,
        'case_id': 'harbour-copper-notebook', 'project_id': PROJECT, 'round': ordinal,
        'input_sha256': 'b' * 64, 'called': called, 'status': status, 'executed': True,
        'browser_status': 'not_run', 'model_requests_started': 0, 'real_storage_writes': 0,
        'catalogue_http_requests_counted': False, 'catalogue_http_hard_cap_verified': False}
    if called:
        receipt.update(request={'place': 'Hobart', 'period': period}, terminal=True,
            result_status='NO_MATCH' if status == 'no_match' else 'READY',
            items=items if items is not None else [{'source_url': 'https://archive.example/item',
                'image_url': 'https://archive.example/photo.jpg', 'license': 'Unknown',
                'date_expression': '', 'attribution': 'An archive',
                'allowed_actions': {'embed': True, 'download': False, 'print': False, 'publish': False}}])
    return {'round': ordinal, 'skill_coverage': coverage.round_skill_coverage(**data),
            'trajectory': {'correlation': {'run_id': 'synthetic-run', 'application_revision': 'a' * 40}},
            'photo_research': receipt}


def test_actual_photo_metadata_is_partial_and_keeps_unknown_rights():
    record = photo_record()
    original = deepcopy(record)
    result = coverage.case_skill_coverage(case_id='harbour-copper-notebook', rounds=[record])
    assert record == original
    photo = result['skills']['place-photo-research']
    assert photo['partial_rounds'] == [12]
    observation = photo['observations'][0]
    assert observation['source_count'] == 1 and observation['unknown_rights'] == 1
    assert observation['date_labeled'] == 0 and observation['rights_labeled'] == 1
    assert observation['browser_status'] == 'not_run'
    assert observation['catalogue_http_hard_cap_verified'] is False
    assert observation['items'][0]['allowed_actions']['publish'] is False
    assert 'photo_research_not_run' not in result['coverage_gaps']
    assert 'photo_research_service_only' in result['coverage_gaps']
    assert result['full_e2e_pass'] is False


def test_terminal_zero_photo_matches_are_not_reported_as_photos_found():
    result = coverage.case_skill_coverage(case_id='harbour-copper-notebook',
        rounds=[photo_record(status='no_match', items=[])])
    photo = result['skills']['place-photo-research']['observations'][0]
    assert photo['status'] == 'partial' and photo['source_count'] == 0
    assert photo['result_status'] == 'NO_MATCH' and photo['found_photos'] is False


def test_explicit_photo_refusal_receipts_preserve_negative_grades():
    record = photo_record(28, status='not_requested', called=False)
    result = coverage.case_skill_coverage(case_id='harbour-copper-notebook', rounds=[record])
    assert 28 in result['skills']['place-photo-research']['pass_rounds']
    record = photo_record(28, status='unavailable')
    result = coverage.case_skill_coverage(case_id='harbour-copper-notebook', rounds=[record])
    assert 28 in result['skills']['place-photo-research']['fail_rounds']


def test_missing_positive_photo_request_is_a_routing_failure_not_a_pass():
    result = coverage.case_skill_coverage(case_id='harbour-copper-notebook',
        rounds=[photo_record(status='not_requested', called=False)])
    assert 12 in result['skills']['place-photo-research']['fail_rounds']


def test_incomplete_or_malformed_photo_claims_cannot_pass():
    for update in ({'terminal': False}, {'called': False}, {'items': []}, {'status': 'pass'}):
        record = photo_record()
        record['photo_research'].update(update)
        result = coverage.case_skill_coverage(case_id='harbour-copper-notebook', rounds=[record])
        assert 12 in result['skills']['place-photo-research']['unavailable_rounds']


def test_historical_and_current_photo_requests_are_checked_offline():
    result = coverage.case_skill_coverage(case_id='harbour-copper-notebook',
        rounds=[photo_record(period='1978'), photo_record(22, period='')])
    assert result['skills']['place-photo-research']['fail_rounds'] == [12, 22]


@pytest.mark.parametrize('field,value', [('case_id', 'other-case'), ('project_id', 'other-project'), ('round', 22)])
def test_misbound_photo_receipt_rejected(field, value):
    record = photo_record()
    record['photo_research'][field] = value
    with pytest.raises(ValueError, match='Photo receipt'):
        coverage.case_skill_coverage(case_id='harbour-copper-notebook', rounds=[record])


def test_unavailable_photo_receipts_retain_bounded_failure_provenance():
    record = photo_record(status='unavailable')
    record['photo_research'].update(result_status='UNAVAILABLE', items=[], target_count=10,
        shortfall=10, failures=[{'provider': 'commons', 'reason': 'timeout'}])
    case = coverage.case_skill_coverage(case_id='harbour-copper-notebook', rounds=[record])
    receipt = case['skills']['place-photo-research']['observations'][0]
    assert receipt['failures'] == [{'provider': 'commons', 'reason': 'timeout'}]
    assert receipt['shortfall'] == receipt['target_count'] == 10
    assert case['skills']['place-photo-research']['service_status'] == 'unavailable'


def test_photo_refusal_without_completed_decision_does_not_establish_negative_pass():
    record = photo_record(28, status='not_requested', called=False)
    record['photo_research']['executed'] = False
    case = coverage.case_skill_coverage(case_id='harbour-copper-notebook', rounds=[record])
    assert 28 in case['skills']['place-photo-research']['unavailable_rounds']


def test_photo_receipt_matches_original_saved_input_and_run_correlation():
    import hashlib
    record = photo_record()
    record['canonical_state'] = observed(12)['canonical_state']
    record['trajectory'] = {'correlation': {'run_id': 'synthetic-run', 'application_revision': 'a' * 40}}
    with pytest.raises(ValueError, match='Photo receipt original-input'):
        coverage.case_skill_coverage(case_id='harbour-copper-notebook', rounds=[record])
    text = record['canonical_state']['sources'][0]['text']
    record['photo_research']['input_sha256'] = hashlib.sha256(text.encode()).hexdigest()
    case = coverage.case_skill_coverage(case_id='harbour-copper-notebook', rounds=[record])
    assert case['skills']['place-photo-research']['partial_rounds'] == [12]
    record['photo_research']['run_id'] = 'another-run'
    with pytest.raises(ValueError, match='Photo receipt run/revision'):
        coverage.case_skill_coverage(case_id='harbour-copper-notebook', rounds=[record])


@pytest.mark.parametrize('change', ['wrong_receipt', 'missing_receipt', 'missing_correlation', 'conflicting_alias'])
def test_photo_receipt_binds_real_application_revision_and_rejects_missing_or_conflicting_pin(change):
    import hashlib
    record = photo_record(28, status='not_requested', called=False)
    record['canonical_state'] = observed(28)['canonical_state']
    record['trajectory'] = {'correlation': {'run_id': 'synthetic-run', 'application_revision': 'a' * 40}}
    record['photo_research']['input_sha256'] = hashlib.sha256(
        record['canonical_state']['sources'][0]['text'].encode()).hexdigest()
    if change == 'wrong_receipt': record['photo_research']['source_revision'] = 'b' * 40
    elif change == 'missing_receipt': record['photo_research'].pop('source_revision')
    elif change == 'missing_correlation': record['trajectory']['correlation'].pop('application_revision')
    else: record['trajectory']['correlation']['source_revision'] = 'b' * 40
    with pytest.raises(ValueError, match='Photo receipt run/revision'):
        coverage.case_skill_coverage(case_id='harbour-copper-notebook', rounds=[record])


@pytest.mark.parametrize('value,expected', [
    ({}, None), ({'family_features_enabled': False}, False),
    ({'family_features_enabled': True}, True), ({'family_features_enabled': 'true'}, None),
    ({'trajectory': {'steps': [{'action': 'authorization.context', 'output': {'family_enabled': False}}]}}, False),
    ({'trajectory': {'steps': [{'action': 'authorization.context', 'output': {'family_enabled': True}}]}}, True),
    ({'trajectory': {'steps': [{'action': 'authorization.context', 'output': {'family_enabled': 1}}]}}, None),
    ({'family_features_enabled': True, 'trajectory': {'steps': [
        {'action': 'authorization.context', 'output': {'family_enabled': False}}]}}, None),
])
def test_family_coverage_uses_actual_runtime_decision_never_plan(value, expected):
    assert coverage.runtime_family_decision(value) is expected
