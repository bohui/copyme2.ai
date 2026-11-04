"""Score-table names identify the evaluated target without opening a trace."""
import pytest

from scripts.langfuse_dataset_names import SKILL_TARGETS, score_name
from scripts import run_memoir_agent_evaluation as agents
from scripts import run_memoir_prompt_evaluation as prompts
from scripts import run_memoir_skill_evaluation as skills
from scripts import run_memoir_judge_calibration as calibration


@pytest.mark.parametrize('skill', ['memoir-interviewer', 'memoir-background-agent', 'memoir-composer'])
def test_campaign_scores_identify_the_agent_or_workflow_being_evaluated(skill):
    output = dict(skill=skill, status='pass', checks=dict(production_and_gold_contract=True),
        elapsed_seconds=2, semantic=dict(scores=dict(evidence_use=0.5),
            comments=dict(evidence_use='observed-1.output')))
    values = {score.name: score.value for score in agents.scores(output=output)}
    target = SKILL_TARGETS[skill]
    assert values == {
        target + '/execution_available': 1,
        target + '/contract_pass': 1,
        target + '/production_and_gold_contract': 1,
        target + '/advisory.evidence_use': 0.5,
        target + '/latency_seconds': 2,
    }


def test_prompt_coverage_scores_identify_each_prompt_in_the_shared_dataset():
    for target in ('memoir/agents/mira/reply', 'memoir/shared/bounded-context/policy', 'memoir/shared/bounded-context/en-AU'):
        output = dict(case_id=target, status='unavailable', current_pin_observed=False)
        assert {score.name for score in prompts.scores(output=output)} == {target + '/current_pin_observed'}


def test_every_registered_prompt_can_be_named_in_the_coverage_ledger():
    from scripts.prompt_registry import prompt_registry
    for target in prompt_registry():
        output = dict(case_id=target, status='unavailable', current_pin_observed=False)
        assert {score.name for score in prompts.scores(output=output)} == {target + '/current_pin_observed'}


@pytest.mark.parametrize(('kind', 'target'), [
    ('live_contract', 'memoir/skills/memory-context/profile'),
    ('controlled_application_checks', 'memoir/workflows/memory-context-admission'),
])
def test_skill_scores_distinguish_model_delivery_from_application_admission(kind, target):
    score = skills.evaluate(input=dict(skill='memoir-memory-context', kind=kind),
        output=dict(status='passed', evidence='controlled completion'))
    assert score.name == target + '/contract_pass'


@pytest.mark.parametrize(('judge', 'target'), [
    ('relevance', 'memoir/evaluators/shared/relevance'),
    ('memoir-interviewer', 'memoir/evaluators/agents/mira/reply/interview-quality'),
    ('trajectory', 'memoir/evaluators/shared/trajectory/system'),
    ('five-case', 'memoir/evaluators/workflows/five-case-memoir/trajectory'),
])
def test_calibration_scores_name_the_judge_under_test_instead_of_shared_policy(judge, target):
    output = dict(judgments={judge: dict(available=False, manifest=dict(artifacts=[]))})
    result = calibration.evaluations(input={}, output=output, expected_output={})
    assert [score.name for score in result] == [target + '/available']


@pytest.mark.parametrize(('target', 'metric'), [
    ('other-project/agents/mira/reply', 'contract_pass'),
    ('memoir/agents/mira/../reply', 'contract_pass'),
    ('memoir/agents/mira/reply', '../contract_pass'),
    ('memoir/agents/mira/reply', ''),
])
def test_score_names_reject_ambiguous_target_or_metric_paths(target, metric):
    with pytest.raises(ValueError):
        score_name(target, metric)
