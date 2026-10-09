"""Truthful, offline seven-skill coverage for saved fifty-round observations.

Collection takes actual application readbacks only and never loads expected
answers. The separate case grader reads a hash-pinned historical expectation
file after collection. Neither function calls a model, browser, search provider,
telemetry publisher, or storage API. These reports do not certify a live run,
semantic quality, historical photo evidence, or browser execution.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from apps.api.place_groups import resolve_place_groups
from apps.api.place_journey import validate_place_journey
from scripts.issue14_progressive_readback import ReadbackError, _references
from scripts.memoir_fifty_readback import CASE_IDS
from scripts.memoir_five_case_evaluator import (
    LIFE_STAGES, SKILLS, case_expectations, expected_round, validate_expected,
)

EXPECTED_PATH = Path(__file__).resolve().parents[1] / 'tests/evaluation/memoir_five_case_expected.json'
EXPECTED_SHA256 = '9391515876dc2f346291e9ecca653e3710a1497d6a03961291cebb8f01d1c242'


def _positive(value):
    return type(value) is int and value > 0


def _skill_calls(result):
    # Only public progress labels are retained. Never copy arbitrary trajectory
    # outputs, model messages, metadata, credentials, or hidden reasoning.
    return sorted({step['skill'] for step in result.get('trace', [])
        if isinstance(step, dict) and step.get('skill') in SKILLS
        and step.get('status') in {'completed', 'succeeded', 'SUCCEEDED'}})


def _timeline(view, round_number, source_id):
    processing = view.get('processing') or {}
    settled = (type(processing) is dict
        and type(processing.get('extracted_through')) is int
        and processing['extracted_through'] == round_number
        and type(processing.get('pending_inputs')) is int
        and processing['pending_inputs'] == 0
        and type(view.get('completed_rounds')) is int
        and view['completed_rounds'] == round_number)
    sources, events = view.get('sources'), view.get('events')
    originals = {source['id']: source for source in sources or []
        if isinstance(source, dict) and isinstance(source.get('id'), str)}
    valid = isinstance(sources, list) and isinstance(events, list) and source_id in originals
    current_count, stages, invalid = 0, set(), 0
    for event in events if isinstance(events, list) else []:
        try:
            if not isinstance(event, dict) or not event.get('source_refs'):
                raise ReadbackError('Event source references are missing')
            refs = _references(event['source_refs'], originals)
            current_count += any(ref['source_id'] == source_id for ref in refs)
            stage = event.get('life_stage')
            if stage in LIFE_STAGES and event.get('stage_evidence'):
                _references(event['stage_evidence'], originals)
                stages.add(stage)
        except (ReadbackError, KeyError, TypeError):
            invalid += 1
    return {'status': 'observed' if settled and valid and not invalid else 'unavailable',
        'scope': 'canonical_memory_event_lane', 'extraction_settled': settled,
        'event_count': len(events) if isinstance(events, list) else None,
        'current_source_events': current_count, 'invalid_source_reference_events': invalid,
        'life_stages': [stage for stage in LIFE_STAGES if stage in stages],
        'empty_extraction_is_valid': True,
        'legacy_marker_contract_comparable': False}


def runtime_family_decision(value):
    """Read the actual authorization result; conflicting/missing evidence is unknown."""
    if type(value) is not dict:
        return None
    decisions = []
    if 'family_features_enabled' in value:
        if type(value['family_features_enabled']) is not bool:
            return None
        decisions.append(value['family_features_enabled'])
    trajectory = value.get('trajectory')
    steps = trajectory.get('steps') if type(trajectory) is dict else None
    for step in steps if type(steps) is list else []:
        if type(step) is dict and step.get('action') == 'authorization.context':
            output = step.get('output')
            if type(output) is not dict or type(output.get('family_enabled')) is not bool:
                return None
            decisions.append(output['family_enabled'])
    return decisions[0] if decisions and all(v is decisions[0] for v in decisions) else None


def round_skill_coverage(*, project_id, round_number, runtime_result, profile,
                         family_context, place_journey, canonical_state,
                         saved_draft=None, family_enabled=None):
    """Project caller-read state; never load hidden expectations during a turn.

    ``canonical_state`` must be the saved MemoryEvent readback after settlement.
    ``family_context`` and ``place_journey`` come from their UserStorage reads,
    not model text. ``family_enabled`` is the actual current server entitlement.
    A saved checkpoint cannot establish the historical formal-composition gate.
    """
    if not isinstance(project_id, str) or not project_id:
        raise ValueError('A project identifier is required')
    if type(round_number) is not int or not 1 <= round_number <= 50:
        raise ValueError('An original round number from 1 through 50 is required')
    if not isinstance(runtime_result, dict) or not isinstance(canonical_state, dict):
        raise ValueError('Application readbacks must be objects')
    if canonical_state.get('project_id') != project_id:
        raise ValueError('Canonical readback project mismatch')
    if isinstance(family_context, dict) and family_context.get('project_id') != project_id:
        raise ValueError('Family readback project mismatch')
    if family_enabled is not None and type(family_enabled) is not bool:
        raise ValueError('Family entitlement must be a boolean or unavailable')

    calls = _skill_calls(runtime_result)
    focus = profile.get('story_focus') if isinstance(profile, dict) else None
    stage = focus.get('life_stage') if isinstance(focus, dict) else None
    update = runtime_result.get('family_context_update')
    update = update if isinstance(update, dict) else {}
    tree_called = ('family_tree' in (update.get('skills') or [])
                   or 'memoir-family-tree' in calls)
    family_valid = (isinstance(family_context, dict)
        and _positive(family_context.get('revision'))
        and isinstance(family_context.get('people'), list)
        and isinstance(family_context.get('relationships'), list))
    tree_saved = (tree_called and family_valid and update.get('persisted') is True
        and type(update.get('revision')) is int
        and update['revision'] == family_context['revision'])

    raw_places = runtime_result.get('place_journeys')
    raw_places = raw_places if isinstance(raw_places, list) else []
    places = [validate_place_journey(place) for place in raw_places]
    places_valid = all(place is not None for place in places)
    places = [place for place in places if place is not None]
    current = validate_place_journey(place_journey)
    saved_current = bool(places_valid and places and current == places[-1]
        and _positive(place_journey.get('revision'))
        and type(place_journey.get('source_sequence')) is int
        and place_journey['source_sequence'] == round_number) if isinstance(place_journey, dict) else False
    grouped = resolve_place_groups(places, allow_provider=False) if places_valid and places else None

    checkpoint = (isinstance(saved_draft, dict) and saved_draft.get('status') == 'ready'
        and saved_draft.get('updating') is False and saved_draft.get('error') is None
        and saved_draft.get('proposal_pending') is False
        and _positive(saved_draft.get('revision'))
        and type(saved_draft.get('covered_round')) is int
        and saved_draft['covered_round'] == round_number
        and isinstance(saved_draft.get('sections'), list) and bool(saved_draft['sections']))
    timeline = _timeline(canonical_state, round_number, runtime_result.get('accepted_source_id'))
    skills = {
        'memoir-memory-context': {
            'status': ('observed' if 'memoir-memory-context' in calls else 'not_observed')
                if isinstance(profile, dict) else 'unavailable',
            'scope': 'persisted_profile_and_public_progress',
            'life_stage': stage if stage in LIFE_STAGES else None,
            'preferred_language': profile.get('preferred_language') if isinstance(profile, dict) else None},
        'memoir-place-journey': {
            'status': 'observed' if saved_current else ('unavailable' if raw_places else 'not_observed'),
            'scope': 'accepted_current_places_and_latest_saved_place',
            'accepted_places': [place['place'] for place in places],
            'persisted_current_turn': saved_current,
            'all_returned_places_valid': places_valid,
            'browser_status': 'not_run'},
        'memoir-family-tree': {
            'status': 'observed' if tree_saved else ('unavailable' if tree_called else 'not_observed'),
            'scope': 'persisted_family_document', 'called': tree_called,
            'enabled': family_enabled, 'persisted_current_update': tree_saved,
            'revision': family_context.get('revision') if isinstance(family_context, dict) else None,
            'people_count': len(family_context['people']) if family_valid else None,
            'relationship_count': len(family_context['relationships']) if family_valid else None},
        'memoir-author-timeline': timeline,
        'memoir-place-groups': {
            'status': 'partial' if grouped is not None else 'not_run',
            'scope': 'deterministic_service_only', 'browser_status': 'not_run',
            'geocoding_allowed': False, 'result': grouped,
            'source_place_count': len(places)},
        'place-photo-research': {
            'status': 'not_run', 'scope': 'no_photo_execution_receipt',
            'reason': 'The owned subscription session has no admitted photo worker or browser route.'},
        'memoir-composer': {
            'status': 'observed' if checkpoint else ('unavailable' if saved_draft is not None else 'not_observed'),
            'scope': 'saved_private_checkpoint', 'saved_checkpoint': checkpoint,
            'revision': saved_draft.get('revision') if isinstance(saved_draft, dict) else None,
            'legacy_action_verified': False},
    }
    return {'schema_version': 'memoir-fifty-skill-readback/1', 'project_id': project_id,
        'round': round_number, 'status': 'partial', 'full_e2e_pass': False,
        'skills': skills, 'family_enabled': family_enabled,
        'readbacks': {'profile': deepcopy(profile), 'family_context': deepcopy(family_context),
                     'place_journey': deepcopy(place_journey),
                     'accepted_place_journeys': deepcopy(raw_places)},
        'semantic_judge': {'status': 'not_run', 'semantic_acceptance': 'human_review_required'}}


def _load_expected():
    try:
        raw = EXPECTED_PATH.read_bytes()
    except OSError:
        raise ValueError('Original expected-file pin is unavailable') from None
    if hashlib.sha256(raw).hexdigest() != EXPECTED_SHA256:
        raise ValueError('Original expected-file pin mismatch')
    expected = json.loads(raw)
    if validate_expected(expected, set(CASE_IDS)):
        raise ValueError('Original expected contract is invalid')
    return expected


def _photo_service_readback(receipt, *, case_id, record, project_id):
    """Validate a saved service receipt; importing its validator does no work."""
    result = {'round': record['round'], 'status': 'not_run', 'called': None,
        'scope': 'isolated_public_reference_metadata', 'browser_status': 'not_run',
        'items': [], 'source_count': 0, 'found_photos': False,
        'rights_permission_verified': False, 'router_decision_observed': False}
    if receipt is None:
        return result
    result['status'] = 'unavailable'
    if not isinstance(receipt, dict) or receipt.get('schema_version') != 'memoir-fifty-photo-receipt/1':
        return result
    if (receipt.get('case_id') != case_id or receipt.get('round') != record['round']
            or receipt.get('project_id') != project_id):
        raise ValueError('Photo receipt case/project/round mismatch')
    correlation = (record.get('trajectory') or {}).get('correlation') or {}
    # The live bridge calls its source pin application_revision. Missing
    # pins and contradictory legacy aliases cannot establish even a no-call
    # negative grade. Never accept an artifact merely because a key is absent.
    revision = correlation.get('application_revision')
    if (type(correlation.get('run_id')) is not str or not correlation['run_id']
            or receipt.get('run_id') != correlation['run_id']
            or type(revision) is not str or len(revision) != 40
            or any(char not in '0123456789abcdef' for char in revision)
            or receipt.get('source_revision') != revision
            or 'source_revision' in correlation and correlation['source_revision'] != revision):
        raise ValueError('Photo receipt run/revision mismatch')
    sources = (record.get('canonical_state') or {}).get('sources') or []
    current = next((source for source in sources if isinstance(source, dict)
                    and source.get('sequence') == record['round']), None)
    if current is not None and isinstance(current.get('text'), str):
        digest = hashlib.sha256(current['text'].encode()).hexdigest()
        if receipt.get('input_sha256') != digest:
            raise ValueError('Photo receipt original-input mismatch')
    called = receipt.get('called')
    if type(called) is not bool:
        return result
    result['called'] = called
    for key in ('reason', 'catalogue_http_requests_counted', 'catalogue_http_hard_cap_verified',
                'searches_started_case', 'searches_started_global', 'logical_search_limit_case',
                'logical_search_limit_global', 'gateway_budget_boundary'):
        if key in receipt:
            result[key] = deepcopy(receipt[key])
    status = receipt.get('status')
    if status == 'not_requested' and called is False and receipt.get('executed') is True:
        result.update(status='not_requested', router_decision_observed=True)
        return result
    request = receipt.get('request')
    if isinstance(request, dict) and isinstance(request.get('place'), str) and isinstance(request.get('period'), str):
        result['request'] = {key: request[key] for key in ('place', 'period')}
    from scripts.memoir_fifty_photo import photo_observation
    body = {'status': receipt.get('result_status'), 'searching': False,
            'items': deepcopy(receipt.get('items')),
            **{key: deepcopy(receipt[key]) for key in ('count', 'target_count', 'shortfall', 'failures')
               if key in receipt}}
    try:
        checked = photo_observation(body)
    except (TypeError, ValueError, KeyError):
        return result
    for key in ('result_status', 'searching', 'count', 'target_count', 'shortfall', 'failures'):
        if key in checked:
            result[key] = checked[key]
    if (status not in {'observed', 'no_match'} or called is not True or receipt.get('executed') is not True
            or receipt.get('terminal') is not True or 'request' not in result):
        return result
    if checked.get('status') != status or checked.get('terminal') is not True:
        return result
    result.update(checked, status='partial', service_status=status, found_photos=bool(checked['items']))
    items = checked['items']
    result.update(source_count=len(items), source_labeled=sum(bool(item.get('source_url')) for item in items),
        rights_labeled=sum(bool(item.get('license')) for item in items),
        date_labeled=sum(bool(item.get('date_expression')) for item in items),
        unknown_rights=sum(str(item.get('license', '')).strip().casefold() in {'', 'unknown', 'unresolved'}
                           for item in items))
    return result


def _grade(skill, requirement, expected, observation):
    if requirement == 'not_applicable':
        return 'not_applicable'
    if observation is None:
        return 'unavailable'
    if skill == 'memoir-author-timeline':
        # The current lane processes every input independently of entitlement;
        # absence of the old Family marker cannot grade its invocation.
        return 'not_comparable'
    if skill == 'memoir-composer':
        return 'not_comparable' if observation.get('saved_checkpoint') else 'unavailable'
    if skill == 'place-photo-research':
        if requirement == 'must_not_call':
            if observation.get('called') is True:
                return 'fail'
            return 'pass' if observation.get('router_decision_observed') is True else 'unavailable'
        if observation.get('router_decision_observed') is True:
            return 'fail'
        if observation.get('status') != 'partial':
            return 'unavailable'
        period = observation['request']['period']
        if ((expected['photo_action'] == 'current_day' and period != '')
                or (expected['photo_action'] == 'historical' and not period.strip())):
            return 'fail'
        return 'partial'
    if skill == 'memoir-place-groups':
        return 'partial' if observation.get('status') == 'partial' else 'unavailable'
    if requirement == 'must_not_call':
        if skill == 'memoir-family-tree':
            return 'fail' if observation.get('called') else 'pass'
        if skill == 'memoir-place-journey':
            return 'fail' if observation.get('accepted_places') else 'pass'
        return 'unavailable'
    if observation.get('status') != 'observed':
        return 'unavailable'
    if skill == 'memoir-memory-context':
        return 'pass' if (expected['life_stage'] is None
            or observation.get('life_stage') == expected['life_stage']) else 'fail'
    if skill == 'memoir-place-journey':
        return 'pass' if set(expected['places']).issubset(observation.get('accepted_places') or []) else 'fail'
    if skill == 'memoir-family-tree':
        return 'pass' if observation.get('enabled') is True else 'fail'
    return 'unavailable'


def case_skill_coverage(*, case_id, rounds):
    """Offline grading of already collected records, with explicit legacy gaps.

    Never call this to construct an execution prompt or select runtime behavior.
    Deterministic passes refer only to the named structural contract subset;
    they are not semantic scores or proof that a provider/browser ran.
    """
    if case_id not in CASE_IDS or not isinstance(rounds, list):
        raise ValueError('Original case and saved round list required')
    expected_payload = _load_expected()
    case_expected = case_expectations(expected_payload)[case_id]
    by_round, project_ids, photos = {}, set(), {}
    for record in rounds:
        ordinal = record.get('round') if isinstance(record, dict) else None
        if type(ordinal) is not int or not 1 <= ordinal <= 50 or ordinal in by_round:
            raise ValueError('Duplicate or invalid saved round')
        observation = record.get('skill_coverage')
        if observation is not None:
            if not isinstance(observation, dict) or observation.get('round') != ordinal:
                raise ValueError('Saved round coverage mismatch')
            project_ids.add(observation.get('project_id'))
        by_round[ordinal] = observation
        if 'photo_research' in record:
            photos[ordinal] = _photo_service_readback(record['photo_research'], case_id=case_id,
                record=record, project_id=observation.get('project_id') if observation else None)
    if len(project_ids) > 1:
        raise ValueError('Saved coverage project mismatch')
    rows, family_failures, family_unavailable, stages = [], [], [], set()
    for ordinal in range(1, 51):
        expected = expected_round(expected_payload, case_expected, ordinal)
        observation = by_round.get(ordinal)
        actual_enabled = observation.get('family_enabled') if observation else None
        if type(actual_enabled) is not bool:
            family_unavailable.append(ordinal)
        elif actual_enabled != expected['family_enabled']:
            family_failures.append(ordinal)
        observations = deepcopy(observation.get('skills', {})) if observation else {}
        if ordinal in photos:
            observations['place-photo-research'] = photos[ordinal]
        memory = observations.get('memoir-memory-context', {})
        if memory.get('status') == 'observed' and memory.get('life_stage') in LIFE_STAGES:
            stages.add(memory['life_stage'])
        timeline = observations.get('memoir-author-timeline', {})
        if timeline.get('status') == 'observed':
            stages.update(timeline.get('life_stages', []))
        rows.append({'round': ordinal, 'expected': expected,
            'grades': {skill: _grade(skill, expected['skill_status'][skill], expected,
                                    observations.get(skill)) for skill in SKILLS}})
    skill_reports = {}
    for skill in SKILLS:
        required = [row['round'] for row in rows if row['expected']['skill_status'][skill] == 'required']
        negative = [row['round'] for row in rows if row['expected']['skill_status'][skill] == 'must_not_call']
        skill_reports[skill] = {'required_rounds': required, 'must_not_call_rounds': negative,
            'status_counts': dict(Counter(row['grades'][skill] for row in rows)),
            **{status + '_rounds': [row['round'] for row in rows if row['grades'][skill] == status]
               for status in ('pass', 'fail', 'partial', 'unavailable', 'not_comparable')}}
    skill_reports['place-photo-research']['observations'] = [photos[n] for n in sorted(photos)]
    photo_called = any(photo.get('called') is True for photo in photos.values())
    photo_status = ('partial' if any(photo['status'] == 'partial' for photo in photos.values())
                    else 'unavailable' if photo_called else 'not_run')
    skill_reports['place-photo-research']['service_status'] = photo_status
    missing = [ordinal for ordinal in range(1, 51) if by_round.get(ordinal) is None]
    return {'schema_version': 'memoir-fifty-case-coverage/1', 'case_id': case_id,
        'expected_sha256': EXPECTED_SHA256, 'status': 'partial',
        'original_contract_status': 'fail' if family_failures or any(
            report['fail_rounds'] for report in skill_reports.values()) else 'partial',
        'full_e2e_pass': False, 'exact_50_rounds': not missing,
        'missing_rounds': missing, 'skills': skill_reports,
        'family_entitlement': {'failed_rounds': family_failures, 'unavailable_rounds': family_unavailable},
        'life_stages_observed': [stage for stage in LIFE_STAGES if stage in stages],
        'all_life_stages_observed': all(stage in stages for stage in LIFE_STAGES),
        'semantic_judge': {'status': 'not_run'},
        'coverage_gaps': ['browser_rendering_not_observed',
            'photo_research_service_only' if photo_status == 'partial' else
                'photo_research_unavailable' if photo_called else 'photo_research_not_run',
            *(['photo_catalogue_http_bound_unverified'] if photo_called else []),
            'legacy_timeline_invocation_contract_changed',
            'private_checkpoint_is_not_formal_composition', 'semantic_judge_not_run'],
        'round_grades': rows}
