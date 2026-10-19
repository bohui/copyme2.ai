"""Run the evaluation CLI, replacing only provider and Langfuse boundaries."""
import asyncio
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import httpx
import pytest

from scripts import run_memoir_skill_evaluation as evaluation
from scripts.memoir_live_skill_cases import interviewer_cases, validate_case
from scripts.memoir_skill_judge import SkillJudge, judge_prompt, evaluator_plan
from apps.api.prompt_catalog import PENDING_EVALUATION_PROMPTS
from scripts.prompt_registry import publication_prompt_registry, prompt_registry

ROOT = Path(__file__).resolve().parents[1]


def selection(case):
    reason = case['expected']['selection_reason']
    pause = reason == 'pause'
    return dict(acknowledgement='We can pause.' if pause else 'We can follow that memory.',
        question=None if pause else 'What do you remember about that?',
        selected_candidate_id=None, selection_reason=reason or 'no_plan', used_strategy='comfort',
        work=dict(mode='reply_only' if pause else 'extract', name=None),
        associations=[], response_photo_ids=[], stopped=pause, continuity_updates=[])


@pytest.mark.parametrize('case', interviewer_cases(), ids=lambda case: case['id'])
def test_interviewer_outputs_use_the_production_validator_and_expected_current_intent(case):
    value = selection(case)
    validate_case(case, value)
    invalid = deepcopy(value)
    invalid['selected_candidate_id'] = 'stale-or-foreign-candidate'
    invalid['selection_reason'] = 'prepared_candidate'
    with pytest.raises(ValueError):
        validate_case(case, invalid)


def test_item_identity_survives_input_gold_and_metadata_updates():
    name, rows = next(iter(evaluation.datasets().items()))
    changed = deepcopy(rows[0])
    changed['input']['selectors'] = ['changed-reviewed-test']
    changed['expected_output']['status'] = 'changed'
    changed['metadata']['revision'] = 2
    assert evaluation.item_id(name, rows[0]) == evaluation.item_id(name, changed)


def test_all_ten_skills_have_evaluator_plans_and_unpublished_judges_cannot_run(tmp_path, monkeypatch):
    plan = evaluator_plan()
    assert len(plan) == 20
    assert len({entry['name'] for entry in plan}) == 20
    assert 'memoir-interviewer' in evaluation.manifest()['skills']
    pending = set(publication_prompt_registry()) - set(prompt_registry())
    assert pending <= set(PENDING_EVALUATION_PROMPTS)
    pin_judge_fixtures(tmp_path, monkeypatch, published=False)
    for skill in evaluation.manifest()['skills']:
        preview, provenance = judge_prompt(skill, preview=True)
        assert '{{skill_rubric}}' not in preview
        assert provenance['compiled_sha256']
        with pytest.raises(ValueError, match='Missing Langfuse prompt receipt'):
            judge_prompt(skill, root=tmp_path)


class HostedDataset:
    def __init__(self, client, name):
        self.client, self.name, self.id = client, name, evaluation.digest(name)[:24]
        self.items = [SimpleNamespace(**deepcopy(item)) for item in client.items.get(name, {}).values()]

    def run_experiment(self, **options):
        rows = []
        for item in self.items:
            output = asyncio.run(options['task'](item=item))
            scores = [evaluate(output=output) for evaluate in options['evaluators']]
            rows.append(SimpleNamespace(input=item.input, output=output, expected_output=item.expected_output,
                experiment_item_id=item.id, experiment_dataset_id=self.id, scores=scores))
        identity = evaluation.digest(self.name)[:16]
        self.client.experiments[identity] = rows
        return SimpleNamespace(experiment_id=identity, item_results=rows)


class LangfuseBoundary:
    def __init__(self):
        self.definitions, self.items, self.experiments, self.writes = {}, {}, {}, []
        self.api = SimpleNamespace(
            projects=SimpleNamespace(get=lambda: SimpleNamespace(data=[SimpleNamespace(id='cmut9t75w00071z02n8bdv7it')])),
            datasets=SimpleNamespace(list=lambda **kwargs: SimpleNamespace(
                data=list(self.definitions.values()), meta=SimpleNamespace(total_pages=1))),
            experiments=SimpleNamespace(list_items=lambda **kwargs: SimpleNamespace(
                data=self.experiments[kwargs['experiment_id']], meta=SimpleNamespace(cursor=None))))

    def create_dataset(self, **values):
        self.definitions[values['name']] = SimpleNamespace(**values)

    def create_dataset_item(self, **values):
        name, identity = values.pop('dataset_name'), values.pop('id')
        self.writes.append((name, identity, deepcopy(values)))
        previous = self.items.setdefault(name, {}).get(identity, {})
        self.items[name][identity] = {**previous, **values, 'id': identity}

    def get_dataset(self, name, **kwargs):
        return HostedDataset(self, name)

    @contextmanager
    def start_as_current_observation(self, **kwargs):
        yield SimpleNamespace(update=lambda **kwargs: None)

    def flush(self):
        pass


@pytest.fixture
def boundary(tmp_path, monkeypatch):
    client = LangfuseBoundary()
    monkeypatch.setattr(evaluation, 'prompt_client', lambda *args: client)
    monkeypatch.setattr('scripts.export_langfuse_prompts.export_prompts', lambda *args, **kwargs: [])
    env = tmp_path / 'test.env'
    env.write_text('MEMORY_SPARK_LLM_BASE_URL=https://gateway.test/v1\n'
        'MEMORY_SPARK_LLM_API_KEY=private-fixture-key\nMEMORY_SPARK_LLM_MODEL=skill-model\n')
    for key in ('MEMORY_SPARK_LLM_BASE_URL', 'MEMORY_SPARK_LLM_API_KEY', 'MEMORY_SPARK_LLM_MODEL'):
        monkeypatch.delenv(key, raising=False)
    return client, env


def pin_judge_fixtures(tmp_path, monkeypatch, *, published=True):
    """Temporary fake pins test the boundary; no repository receipt is invented."""
    for name, relative in PENDING_EVALUATION_PROMPTS.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((ROOT / relative).read_bytes())
        if published:
            path.with_name(path.name + '.langfuse.json').write_text(json.dumps(dict(
                schema_version=1, name=name, version=1, type='text',
                sha256=hashlib.sha256(path.read_bytes()).hexdigest())))
    monkeypatch.setattr(evaluation, 'judge_prompt', lambda skill: judge_prompt(skill, root=tmp_path))
    monkeypatch.setattr(evaluation, 'SkillJudge', lambda provider: SkillJudge(provider, root=tmp_path))


def invoke(monkeypatch, tmp_path, env, *args):
    monkeypatch.setattr(sys, 'argv', ['run_memoir_skill_evaluation.py', '--execute',
        '--env-file', str(env), '--output-root', str(tmp_path / 'results'), *args])
    code = evaluation.main()
    receipt, = (tmp_path / 'results').glob('*/receipt.json')
    return code, json.loads(receipt.read_text()), receipt.parent


def transport(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: original(
        transport=httpx.MockTransport(handler), **kwargs))


def completed(value):
    return httpx.Response(200, json=dict(id='resp-fixture', status='completed', model='served-fixture-model',
        usage=dict(input_tokens=3, output_tokens=2), output=[dict(type='message',
            content=[dict(type='output_text', text=json.dumps(value))])]))


def test_cli_runs_skill_contract_independent_judge_and_report(boundary, tmp_path, monkeypatch):
    client, env = boundary
    pin_judge_fixtures(tmp_path / 'pins', monkeypatch)
    case = next(case for case in interviewer_cases() if case['id'] == 'interviewer-pause-en-AU')
    calls = []
    def handle(request):
        body = json.loads(request.content)
        calls.append(body)
        if body['model'] == 'judge-model':
            assert 'actual_output_and_bound_witnesses' in body['instructions']
            return completed(dict(score='pass', reasoning='The reply respects the explicit pause [input] [artifact].'))
        assert 'expected_output' not in body['input'] and 'skill_rubric' not in body['instructions']
        return completed(selection(case))
    transport(monkeypatch, handle)
    code, receipt, directory = invoke(monkeypatch, tmp_path, env, '--phase', 'deliveries',
        '--skill', 'memoir-interviewer', '--case', case['id'], '--judge', 'sdk', '--judge-model', 'judge-model')
    assert code == 0
    assert [call['model'] for call in calls] == ['skill-model', 'judge-model']
    result, = receipt['results']
    assert result['status'] == 'passed' and result['delivery'] == 'correct_skip'
    assert result['quality']['score'] == 'pass' and result['quality']['calibration'] == 'pending'
    assert len(receipt['calls']) == len(receipt['judge_calls']) == 1
    assert 'Quality (advisory)' in (directory / 'report.md').read_text()
    assert set(client.definitions) == {'memoir/evaluation/skills/memoir-interviewer'}


def test_cli_budget_exhaustion_keeps_every_planned_item(boundary, tmp_path, monkeypatch):
    _, env = boundary
    case = next(case for case in interviewer_cases() if case['id'] == 'interviewer-pause-en-AU')
    calls = []
    def handle(request):
        calls.append(request)
        return completed(selection(case))
    transport(monkeypatch, handle)
    code, receipt, _ = invoke(monkeypatch, tmp_path, env, '--phase', 'deliveries', '--max-calls', '1',
        '--skill', 'memoir-interviewer', '--case', 'interviewer-pause-en-AU', '--case', 'interviewer-redirect-en-AU')
    assert code == 1 and len(calls) == 1
    assert len(receipt['results']) == 2
    assert [row['status'] for row in receipt['results']] == ['passed', 'unavailable']
    assert receipt['status'] == 'incomplete'


def test_a_positive_judge_cannot_upgrade_a_failed_contract(boundary, tmp_path, monkeypatch):
    _, env = boundary
    pin_judge_fixtures(tmp_path / 'pins', monkeypatch)
    case = next(case for case in interviewer_cases() if case['id'] == 'interviewer-explore-memory-en-AU')
    wrong = selection(case)
    wrong.update(question=None, stopped=True, selection_reason='pause')
    def handle(request):
        if json.loads(request.content)['model'] == 'judge-model':
            return completed(dict(score='pass', reasoning='The prose sounds pleasant [artifact].'))
        return completed(wrong)
    transport(monkeypatch, handle)
    code, receipt, _ = invoke(monkeypatch, tmp_path, env, '--phase', 'deliveries',
        '--skill', 'memoir-interviewer', '--case', case['id'], '--judge', 'sdk', '--judge-model', 'judge-model')
    assert code == 1 and receipt['status'] == 'failed'
    assert receipt['results'][0]['quality']['score'] == 'pass'
    assert receipt['results'][0]['status'] == 'failed'


@pytest.mark.parametrize('bad', ['missing_citation', 'duplicate_json', 'timeout'])
def test_bad_or_unavailable_judges_keep_contract_and_quality_separate(boundary, tmp_path, monkeypatch, bad):
    _, env = boundary
    pin_judge_fixtures(tmp_path / 'pins', monkeypatch)
    case = next(case for case in interviewer_cases() if case['id'] == 'interviewer-pause-en-AU')
    def handle(request):
        if json.loads(request.content)['model'] != 'judge-model':
            return completed(selection(case))
        if bad == 'timeout':
            raise httpx.ReadTimeout('private transport detail')
        if bad == 'duplicate_json':
            raw = json.dumps(dict(score='pass', reasoning='Looks good [artifact].')) * 2
            return httpx.Response(200, json=dict(id='judge-invalid', status='completed', output=[dict(
                type='message', content=[dict(type='output_text', text=raw)])]))
        return completed(dict(score='pass', reasoning='Looks good without any citation.'))
    transport(monkeypatch, handle)
    code, receipt, _ = invoke(monkeypatch, tmp_path, env, '--phase', 'deliveries',
        '--skill', 'memoir-interviewer', '--case', case['id'], '--judge', 'sdk', '--judge-model', 'judge-model')
    assert code == 1 and receipt['status'] == 'incomplete'
    assert receipt['results'][0]['status'] == 'passed'
    assert receipt['results'][0]['quality']['score'] == 'unavailable'
    assert 'private transport detail' not in json.dumps(receipt)


def test_grouping_dispatches_no_skill_model_request(boundary, tmp_path, monkeypatch):
    _, env = boundary
    transport(monkeypatch, lambda request: pytest.fail('Deterministic grouping must not call a model'))
    code, receipt, _ = invoke(monkeypatch, tmp_path, env, '--phase', 'deliveries',
        '--skill', 'memoir-place-groups', '--case', 'groups-independent-child-pin')
    assert code == 0 and receipt['calls'] == []
    assert receipt['results'][0]['artifact']['places']


def test_dataset_update_preserves_identity_and_archives_only_retired_items():
    client = LangfuseBoundary()
    name, rows = next(iter(evaluation.datasets().items()))
    initial = {name: deepcopy(rows)}
    evaluation.publish_datasets(client, initial)
    changed = deepcopy(rows[:1])
    changed[0]['expected_output']['revision'] = 2
    with pytest.raises(ValueError, match='conflict|unexpected'):
        evaluation.publish_datasets(client, {name: changed})
    loaded, _ = evaluation.publish_datasets(client, {name: changed}, update=True)
    identity = evaluation.item_id(name, changed[0])
    assert [item.id for item in loaded[name].items] == [identity]
    assert client.items[name][identity]['expected_output']['revision'] == 2
    assert all(item['status'] == 'ARCHIVED' for key, item in client.items[name].items() if key != identity)


def test_zero_call_plan_needs_no_credentials(boundary, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(evaluation, 'prompt_client', lambda *args: pytest.fail('Plan must be local'))
    monkeypatch.setattr(sys, 'argv', ['run_memoir_skill_evaluation.py', '--skill', 'memoir-interviewer', '--locale', 'zh-CN'])
    assert evaluation.main() == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan['http_dispatches'] == 0 and len(plan['skills']) == 10
    localized = [case for case in plan['selected_cases'] if not case.endswith('-triggers')]
    assert len(localized) == 8 and all(case.endswith('-zh-CN') for case in localized)


def test_unpublished_judge_stops_before_services_or_model_calls(boundary, tmp_path, monkeypatch):
    _, env = boundary
    pin_judge_fixtures(tmp_path / 'unpublished', monkeypatch, published=False)
    monkeypatch.setattr(evaluation, 'prompt_client', lambda *args: pytest.fail('Missing pins must stop before Langfuse'))
    transport(monkeypatch, lambda request: pytest.fail('Missing pins must stop before model dispatch'))
    monkeypatch.setattr(sys, 'argv', ['run_memoir_skill_evaluation.py', '--execute', '--phase', 'deliveries',
        '--skill', 'memoir-interviewer', '--judge', 'sdk', '--env-file', str(env)])
    with pytest.raises(SystemExit) as stopped:
        evaluation.main()
    assert stopped.value.code == 2


@pytest.mark.parametrize('mutation', ['identity', 'input', 'gold', 'artifact', 'score', 'duplicate_score', 'missing_quality'])
def test_experiment_verification_requires_matching_artifacts_gold_identity_and_scores(mutation):
    client = LangfuseBoundary()
    output = dict(status='passed', quality=dict(score='pass'))
    item = SimpleNamespace(experiment_item_id='stable-item', experiment_dataset_id='dataset',
        input={'case_id': 'case'}, expected_output={'action': 'pause'}, output=deepcopy(output),
        scores=[SimpleNamespace(name='contract_pass', value=1), SimpleNamespace(name='skill_quality', value='pass')])
    wanted = {'stable-item': dict(dataset_id='dataset', input=deepcopy(item.input),
        expected_output=deepcopy(item.expected_output), output=deepcopy(output))}
    client.experiments['experiment'] = [item]
    if mutation == 'identity': item.experiment_item_id = 'foreign-item'
    if mutation == 'input': item.input['case_id'] = 'another-case'
    if mutation == 'gold': item.expected_output['action'] = 'deliver'
    if mutation == 'artifact': item.output['status'] = 'failed'
    if mutation == 'score': item.scores[0].value = 0
    if mutation == 'duplicate_score': item.scores.append(item.scores[0])
    if mutation == 'missing_quality': item.scores.pop()
    result = evaluation.readback(client, 'experiment', 1, datetime.now(timezone.utc), expected=wanted)
    assert result['status'] == ('pending' if mutation == 'missing_quality' else 'conflict')
