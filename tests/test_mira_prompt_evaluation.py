"""Draft prompt evaluation uses fictional cases and validates judge output."""
import pytest
from jsonschema import ValidationError, validate

from scripts.evaluate_mira_prompt import cases, lane_b_cases, emotional_cases, judge_schema


def test_comparison_uses_existing_bilingual_cases_and_real_reply_projections():
    inputs = cases()
    assert len(inputs) == len({case['id'] for case in inputs}) == 36
    assert {case['view']['reply_language'] for case in inputs} == {'en-AU', 'zh-CN'}
    for case in inputs:
        assert case['view']['current']['narrator']['original'] == case['context']['source']['text']
        assert 'gold' not in case['view'] and 'criteria' not in case['view']


def test_judge_schema_rejects_unbounded_scores_and_unrecognized_winners():
    rating = dict(score=4, critical=[], reason='Follows the current memory.')
    row = dict(id='fictional-case', A=rating, B=rating, winner='tie')
    validate(dict(results=[row]), judge_schema())
    with pytest.raises(ValidationError):
        validate(dict(results=[{**row, 'A': {**rating, 'score': 5}}]), judge_schema())
    with pytest.raises(ValidationError):
        validate(dict(results=[{**row, 'winner': 'candidate'}]), judge_schema())


def test_lane_b_probes_keep_prepared_hints_and_current_narration_in_the_real_packet():
    cases()  # Load the existing shared fixture modules.
    inputs = lane_b_cases()
    assert len(inputs) == 6
    for case in inputs:
        assert len(case['view']['brief']['hints']) == 2
        assert case['view']['current']['narrator']['original'] == case['context']['source']['text']


def test_emotional_probes_cover_both_languages_without_putting_judge_criteria_in_requests():
    cases()
    inputs = emotional_cases()
    assert len(inputs) == len({case['id'] for case in inputs}) == 16
    assert {case['view']['reply_language'] for case in inputs} == {'en-AU', 'zh-CN'}
    for case in inputs:
        assert case['view']['current']['narrator']['original'] == case['context']['source']['text']
        assert case['criteria']['required']
        assert 'criteria' not in case['view'] and 'gold' not in case['view']
