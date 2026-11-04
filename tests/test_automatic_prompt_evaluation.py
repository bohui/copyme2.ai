"""The public command selects frozen scenarios and proves requested prompt use."""
from copy import deepcopy
import json
import subprocess

import pytest

from scripts import evaluate_langfuse_prompt as command
from scripts import run_memoir_agent_evaluation as agents
from scripts.prompt_registry import prompt_registry

MIRA = 'memoir/agents/mira/reply'


@pytest.mark.parametrize('selector, expected_cases', [
    ('PROMPT_EVAL_NAME=' + MIRA, 70),
    ('SKILL_EVAL_NAME=author-timeline', 32),
])
def test_make_plan_selects_datasets_and_graders_without_credentials(selector, expected_cases):
    result = subprocess.run(['make', '--no-print-directory', 'prompt-eval-plan', selector,
        'PROMPT_CREDENTIAL_FILE=/missing/credentials'], cwd=command.ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    plan = json.loads(result.stdout)
    assert plan['count'] == expected_cases and plan['http_dispatches'] == 0
    assert plan['dataset_names'] and plan['evaluator'] == 'scripts/run_memoir_agent_evaluation.py:scores'
    names = {p['name'] for p in plan['requested_prompts']}
    expected = {MIRA} if selector.startswith('PROMPT_') else {
        name for name in prompt_registry() if name.startswith('memoir/skills/author-timeline/')}
    assert names == expected
    assert len(plan['cases']) == len(set(plan['cases']))


def test_prompt_command_executes_and_publishes_grading_by_default(monkeypatch):
    calls = []
    monkeypatch.setattr(agents, 'main', lambda args: calls.append(args) or 0)
    assert command.main(['--name', MIRA]) == 0
    assert calls[0][calls[0].index('--prompt') + 1] == MIRA
    assert '--execute' in calls[0] and '--publish' in calls[0]


def test_judge_prompt_automatically_selects_shared_answer_keys(monkeypatch):
    from scripts import run_memoir_judge_calibration as calibration
    calls = []
    monkeypatch.setattr(calibration, 'main', lambda args: calls.append(args) or 0)
    assert command.main(['--name', 'memoir/evaluators/shared/relevance']) == 0
    assert calls[0][calls[0].index('--judge') + 1] == 'relevance'
    assert '--execute' in calls[0]


@pytest.mark.parametrize('args', [[], ['--name', 'agent.mira.reply'], ['--name', ''],
    ['--skill', 'does-not-exist'], ['--name', MIRA, '--skill', 'author-timeline'],
    ['--name', MIRA, '--plan', '--execute']])
def test_invalid_or_conflicting_selection_cannot_dispatch(args):
    with pytest.raises(SystemExit) as error:
        command.main(args)
    assert error.value.code == 2


def test_unsupported_modality_cannot_fall_back_to_a_raw_ungraded_experiment():
    with pytest.raises(SystemExit) as error:
        command.main(['--plan', '--name', 'memoir/workflows/speech/synthesis/en-AU'])
    assert error.value.code == 2


@pytest.mark.parametrize('mutation', [None, 'version', 'sha256', 'provider_response'])
def test_prompt_score_requires_the_exact_executed_pin_and_real_response(mutation):
    pin = command.prompt_pin(MIRA)
    observed = {k: pin[k] for k in ('name', 'version', 'sha256')}
    call = dict(case_id='one', provider_response_id='observed-response', prompt_manifest=dict(artifacts=[observed]))
    if mutation == 'version': observed['version'] -= 1
    elif mutation == 'sha256': observed['sha256'] = 'stale'
    elif mutation == 'provider_response': call['provider_response_id'] = None
    row = dict(case_id='one', skill='memoir-interviewer', status='pass', checks={}, semantic=None,
        elapsed_seconds=1, evidence_mode='live_reply_proposal')
    row['prompt_coverage'] = agents.prompt_coverage([pin], dict(calls=[call], results=[deepcopy(row)]))
    grades = {score.name: score.value for score in agents.scores(output=row)}
    assert grades[MIRA + '/current_pin_observed'] == int(mutation is None)
    assert (MIRA + '/observed_scenario_checks_pass' in grades) == (mutation is None)


def test_a_component_not_executed_by_a_passing_workflow_keeps_its_gap():
    pins = [command.prompt_pin(MIRA), command.prompt_pin('memoir/agents/mira/repair')]
    row = dict(case_id='one', status='pass', evidence_mode='live_reply_proposal')
    run = dict(calls=[dict(case_id='one', provider_response_id='response', prompt_manifest=dict(artifacts=[pins[0]]))], results=[row])
    result = agents.prompt_coverage(pins, run)
    assert result[0]['status'] == 'pass' and result[1]['status'] == 'unavailable'


def test_obsolete_agent_make_commands_are_removed():
    result = subprocess.run(['make', '-n', 'memoir-agent-eval'], cwd=command.ROOT, capture_output=True, text=True)
    assert result.returncode != 0 and 'No rule to make target' in result.stderr
