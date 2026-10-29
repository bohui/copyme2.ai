"""Draft prompt evaluation uses fictional cases and validates judge output."""
import pytest
from jsonschema import ValidationError, validate

from scripts.evaluate_mira_prompt import cases, judge_schema


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
