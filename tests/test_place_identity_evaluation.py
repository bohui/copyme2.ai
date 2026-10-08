"""The location golds score extracted model output, not only fixture validity."""
import json
from pathlib import Path

import pytest

from apps.api.codex_runtime import build_workspace_extraction_prompt
from apps.api.place_journey import MARKER_START, MARKER_END
from scripts.evaluate_place_journeys import load_cases, score_response


VERSION, CASES = load_cases()
MODEL_OUTPUTS = json.loads((Path(__file__).parent / 'evaluation' / 'place_identity_model_outputs.json').read_text())


@pytest.mark.parametrize('case', CASES, ids=lambda case: case['id'])
def test_recorded_place_outputs_pass_the_identity_dataset(case):
    assert VERSION == 'memoir-place-identity/1'
    assert score_response(case, case['recorded_response'])['passed']


@pytest.mark.parametrize('case', CASES, ids=lambda case: case['id'])
def test_checked_in_actual_model_outputs_pass_the_same_scorer(case):
    assert MODEL_OUTPUTS['mode'] == 'live_model'
    assert MODEL_OUTPUTS['dataset_version'] == VERSION
    assert score_response(case, MODEL_OUTPUTS['responses'][case['id']])['passed']


def test_evaluator_rejects_missing_city_and_duplicate_aliases():
    case = CASES[0]
    assert not score_response(case, '')['passed']
    full = {**case['expected_places'][0], 'place': '承德市',
            'hierarchy': ['Earth', '中国', '河北省', '承德市']}
    duplicate = case['recorded_response'] + MARKER_START + json.dumps(full) + MARKER_END
    case = {**case, 'text': case['text'] + '我说的就是承德市。'}
    assert not score_response(case, duplicate)['checks']['unique_geographic_identities']


def test_evaluator_rejects_broken_markers_and_saved_place_hallucinations():
    case = next(case for case in CASES if case['id'] == 'saved-photo-is-not-a-new-place-cue')
    assert not score_response(case, MARKER_START + '{broken' + MARKER_END)['passed']
    assert not score_response(case, CASES[0]['recorded_response'])['passed']


def test_evaluator_rejects_city_centre_as_child_pin():
    case = next(case for case in CASES if case['id'] == 'new-child-of-known-city')
    child = {**case['expected_places'][0], 'latitude': case['place_journey']['latitude'],
             'longitude': case['place_journey']['longitude']}
    response = MARKER_START + json.dumps(child) + MARKER_END
    assert not score_response(case, response)['checks']['child_coordinates_independent']


def test_verified_district_parent_is_allowed_but_unrelated_parent_is_rejected():
    case = next(case for case in CASES if case['id'] == 'new-child-of-known-city')
    place = case['expected_places'][0]
    complete = {**place, 'hierarchy': case['hierarchy_alternatives'][place['place']][0]}
    assert score_response(case, MARKER_START + json.dumps(complete) + MARKER_END)['passed']
    wrong = {**place, 'hierarchy': ['Earth', '中国', '河北', '另一城市', place['place']]}
    assert not score_response(case, MARKER_START + json.dumps(wrong) + MARKER_END)['passed']


def test_extraction_has_compact_existing_identity_hints_without_photo_metadata():
    current = CASES[0]['place_journey']
    photo = {'place': '承德', 'hierarchy': ['Earth', '中国', '河北', '承德'],
             'granularity': 'city', 'pictures': [{'secret_caption': 'private-photo-metadata'}]}
    prompt = build_workspace_extraction_prompt('(none)', {'memory_places': [photo]},
        place_journey=current, family_enabled=False, language='zh-CN', canonical_events=True)
    assert 'Known geographic identities' in prompt
    assert 'private-photo-metadata' not in prompt
    assert '40.9517' in prompt
    assert 'Still emit a marker for a repeated place explicitly named now' in prompt
    assert 'backend resolves the final identity' in prompt
