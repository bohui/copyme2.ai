"""Issue 90: exercise the CLI with controlled services, never real providers."""
import asyncio
from copy import deepcopy
import json

import pytest

from scripts import memoir_skill_eval_suite as suite
from scripts.memoir_live_skill_cases import scenario_cases


def selected(skill='memoir-place-groups', **kwargs):
    return suite.plan(skill=[skill], **kwargs)


def test_inventory_and_bilingual_scenarios_are_complete_and_stable():
    plan = suite.plan()
    assert len(plan['inventory']) == 10
    assert len(plan['items']) == 160
    assert len({(c['skill'], c['case']) for c in plan['items']}) == 80
    assert len({c['id'] for c in plan['items']}) == 160
    assert all({c['locale'] for c in plan['items'] if c['skill'] == skill} == {'en-AU', 'zh-CN'}
               for skill in plan['inventory'])
    assert len(plan['evaluators']) == 20
    assert len(plan['datasets']) == 12
    assert plan['http_dispatches'] == 0
    case = deepcopy(plan['items'][0])
    before = case['id']
    case['task']['instruction'] += ' Reviewed correction.'
    assert suite.identity(case) == before
    assert suite.digest(case) != suite.digest(plan['items'][0])


def test_unmapped_prompt_owner_and_runtime_skill_fail_preflight(monkeypatch):
    from apps.api.background_skills import SKILLS, Skill
    from apps.api.prompt_catalog import PROMPT_PATHS
    monkeypatch.setitem(PROMPT_PATHS, 'memoir/skills/new-skill/task', 'unused.md')
    with pytest.raises(ValueError, match='unmapped'):
        suite.plan()
    monkeypatch.delitem(PROMPT_PATHS, 'memoir/skills/new-skill/task')
    monkeypatch.setitem(SKILLS, 'new-runtime', Skill('new-runtime', 'x', 'model', 'x'))
    with pytest.raises(ValueError, match='unmapped'):
        suite.plan()


def test_cli_planning_never_allocates_services_or_reads_env(monkeypatch, capsys, tmp_path):
    from scripts import run_memoir_skill_evaluation as cli
    monkeypatch.setattr(suite, 'run', lambda *a, **k: pytest.fail('execution during plan'))
    assert cli.main(['--skill', 'memoir-interviewer', '--locale', 'zh-CN']) == 0
    result = json.loads(capsys.readouterr().out)
    assert len(result['items']) == 8 and result['http_dispatches'] == 0
    with pytest.raises(SystemExit) as error:
        cli.main(['--phase', 'publish', '--case', result['items'][0]['id']])
    assert error.value.code == 2
    assert list(tmp_path.iterdir()) == []


def test_real_grouping_dispatches_no_skill_model_and_keeps_denominators(tmp_path):
    receipt = asyncio.run(suite.run(selected(), tmp_path))
    assert len(receipt['results']) == 16
    assert receipt['budgets']['skill']['dispatched'] == 0
    assert all(r['contract']['status'] == 'pass' for r in receipt['results'])
    assert all(r['execution'] == 'completed' for r in receipt['results'])
    assert all(r['quality']['status'] == 'unavailable' for r in receipt['results'])
    assert receipt['status'] == 'incomplete'
    assert receipt['coverage']['memoir-place-groups']['planned'] == 16
    assert json.loads((tmp_path / 'receipt.json').read_text()) == receipt


def test_missing_runners_keep_every_item_and_cannot_pass(tmp_path):
    receipt = asyncio.run(suite.run(suite.plan(), tmp_path))
    assert len(receipt['results']) == 160
    assert len(receipt['coverage']) == 10
    family = receipt['coverage']['memoir-family-tree']
    assert family['planned'] == family['unavailable'] == 16
    assert family['positive_delivery'] == 0
    assert 'unwired' in (tmp_path / 'report.md').read_text()


def profile_output(item):
    source = item['task']['page']['source']
    return {'profile_patch': [dict(field=k, value=v, source_refs=[dict(source_id=source['id'],
        version=source['version'], quote=source['text'], char_start=0, char_end=len(source['text']))])
        for k, v in item['gold']['facts'].items()]}


class ControlledSkill:
    """Fixture owns only the external model; app still builds/validates packets."""
    def __init__(self):
        self.packets = []

    async def call(self, request):
        self.packets.append(deepcopy(request))
        assert 'gold' not in request and 'rubric' not in request
        item = next(c for c in scenario_cases() if c['id'] == request['item_id'])
        return dict(output=profile_output(item), response_id='fixture-response',
                    model='controlled-model', usage=None)


class ControlledJudge:
    async def call(self, packet):
        return dict(status='pass', citations=['output'], rationale='Supported by supplied evidence.',
                    critical_violations=[], response_id='judge-fixture', model='independent-fixture', usage=None)


def test_cli_complete_flow_gold_exclusion_evidence_and_negative_delivery(tmp_path, capsys):
    from scripts import run_memoir_skill_evaluation as cli
    skill = ControlledSkill()
    status = cli.main(['--execute', '--skill', 'memoir-memory-context', '--output-root', str(tmp_path)],
                      services=dict(skill=skill, sdk_judge=ControlledJudge()))
    assert status == 0
    receipt = json.loads((tmp_path / 'receipt.json').read_text())
    assert len(receipt['results']) == 16
    assert len(skill.packets) == 16
    assert all(r['contract']['status'] == 'pass' for r in receipt['results'])
    negative = [r for r in receipt['results'] if not r['positive_case']]
    assert negative and all(r['positive_delivery'] is False for r in negative)
    assert all(r['quality']['calibration'] == 'advisory' for r in receipt['results'])
    assert all(r['binding']['output_sha256'] == suite.digest(r['output']) for r in receipt['results'])
    assert receipt['budgets']['skill']['calls'][0]['usage'] is None
    assert receipt['scope'] == 'controlled_offline'


def test_failed_dispatch_counts_and_retains_budget_exhausted_items(tmp_path):
    class Failure:
        async def call(self, request):
            raise TimeoutError('private provider text')
    result = asyncio.run(suite.run(selected('memoir-memory-context'), tmp_path,
        skill=Failure(), max_skill_calls=1, max_judge_calls=2))
    assert result['budgets']['skill']['dispatched'] == 1
    assert result['budgets']['judge']['dispatched'] == 0
    assert len(result['results']) == 16
    assert result['results'][1]['reason'] == 'skill_budget_exhausted'
    assert 'private provider text' not in (tmp_path / 'receipt.json').read_text()


@pytest.mark.parametrize('change', [dict(status='pass', citations=[]),
    dict(status='pass', citations=['invented']), dict(status='nonsense'),
    dict(status='pass', critical_violations=['invented_fact']), dict(status='pass', rationale='')])
def test_invalid_or_critical_judgments_never_pass(tmp_path, change):
    class Judge(ControlledJudge):
        async def call(self, packet):
            return {**await super().call(packet), **change}
    result = asyncio.run(suite.run(selected(), tmp_path, sdk_judge=Judge(), max_judge_calls=1))
    assert result['results'][0]['quality']['status'] != 'pass'
    assert result['results'][1]['quality']['reason'] == 'judge_budget_exhausted'


def test_mutually_exclusive_executors_fail_before_work(tmp_path):
    with pytest.raises(ValueError, match='exclusive'):
        asyncio.run(suite.run(selected(), tmp_path, sdk_judge=ControlledJudge(), managed_judge=ControlledJudge()))
    assert not list(tmp_path.iterdir())


def test_model_cannot_forge_host_witnesses_and_receipts_cannot_be_rebound(tmp_path):
    planned = selected()
    result = asyncio.run(suite.run(planned, tmp_path))
    item = planned['items'][0]
    row = result['results'][0]
    assert suite.hosted_contract(item, row['output'], row['binding'], result)['status'] == 'pass'
    assert suite.hosted_contract(item, row['output'], row['binding'], None)['status'] == 'unavailable'
    changed = deepcopy(row['binding'])
    changed['input_sha256'] = '0' * 64
    assert suite.hosted_contract(item, row['output'], changed, result)['status'] == 'unavailable'


def test_evidence_size_and_deadline_prevent_dispatch(tmp_path):
    skill = ControlledSkill()
    result = asyncio.run(suite.run(selected('memoir-memory-context'), tmp_path, skill=skill,
                                   max_evidence_bytes=10))
    assert not skill.packets and len(result['results']) == 16
    assert all(r['execution'] == 'unavailable' for r in result['results'])


def test_separate_calibration_splits_have_no_claimed_human_labels():
    assets = suite.plan()['calibration']
    assert set(assets) == {'development', 'holdout'}
    assert not set(assets['development']) & set(assets['holdout'])
    assert suite.plan()['human_calibration'] == 'pending_human_labels'


def test_cancelled_dispatch_is_counted_and_every_planned_item_is_saved(tmp_path):
    class Cancelled:
        async def call(self, request): raise asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(suite.run(selected('memoir-memory-context'), tmp_path, skill=Cancelled()))
    receipt = json.loads((tmp_path / 'receipt.json').read_text())
    assert receipt['status'] == 'incomplete'
    assert receipt['budgets']['skill']['dispatched'] == 1
    assert len(receipt['results']) == receipt['coverage']['memoir-memory-context']['planned'] == 16
    assert (tmp_path / 'report.md').exists()


def test_judge_cannot_be_the_evaluated_model(tmp_path):
    class Same(ControlledJudge):
        async def call(self, packet): return {**await super().call(packet), 'model': 'controlled-model'}
    receipt = asyncio.run(suite.run(selected('memoir-memory-context'), tmp_path,
        skill=ControlledSkill(), sdk_judge=Same(), max_judge_calls=1))
    assert receipt['results'][0]['quality']['status'] == 'unavailable'


def test_elapsed_budget_prevents_all_skill_dispatches(tmp_path):
    provider = ControlledSkill()
    class Clock:
        now = 0
        def __call__(self):
            self.now += 10
            return self.now
    receipt = asyncio.run(suite.run(selected('memoir-memory-context'), tmp_path,
        skill=provider, seconds=1, clock=Clock()))
    assert not provider.packets
    assert receipt['budgets']['skill']['dispatched'] == 0
    assert len(receipt['results']) == 16


def test_profile_omission_and_wrong_unicode_offsets_fail_host_contract(tmp_path):
    planned = suite.plan(case=['memoir-memory-context/explicit-profile/zh-CN'])
    class Omit(ControlledSkill):
        async def call(self, request):
            result = await super().call(request)
            result['output']['profile_patch'].pop()
            return result
    receipt = asyncio.run(suite.run(planned, tmp_path, skill=Omit()))
    assert receipt['results'][0]['contract']['status'] == 'fail'
    output = profile_output(planned['items'][0])
    output['profile_patch'][0]['source_refs'][0]['char_end'] = len(planned['items'][0]['task']['source']['text'].encode())
    with pytest.raises(ValueError): suite.validate(planned['items'][0], output)


def test_family_direction_is_checked_independently_and_integration_stays_unwired():
    case = suite.plan(case=['memoir-family-tree/relationship-direction/en-AU'])['items'][0]
    tree = dict(people=[dict(id='mei', name='Mei'), dict(id='alex', name='Alex')],
        relationships=[dict(from_person_id='mei', to_person_id='alex', relationship_type='parent')])
    def marker(value):
        return '[[MEMORY_SPARK_FAMILY_TREE]]' + json.dumps(value) + '[[/MEMORY_SPARK_FAMILY_TREE]]'
    suite.validate(case, marker(tree))
    tree['relationships'][0].update(from_person_id='alex', to_person_id='mei')
    with pytest.raises(ValueError, match='direction'): suite.validate(case, marker(tree))
    integration = suite.plan(case=['memoir-family-tree/unwired-integration/en-AU'])['items'][0]
    with pytest.raises(LookupError, match='unwired'): suite.validate(integration, marker(tree))


def test_game_schema_and_exact_chapter_quotes_do_not_create_authority():
    item = suite.plan(case=['memoir-story-game/proposal/en-AU'])['items'][0]
    chapter = item['task']['chapters'][0]
    proposal = dict(scenes=[dict(chapter_id=chapter['id'], block_index=i, person=person,
        title=person, quote=chapter['blocks'][i]['text'], art='generic-garden')
        for i, person in enumerate(('father', 'mother'))])
    with pytest.raises(LookupError, match='authority'): suite.validate(item, proposal)
    proposal['scenes'][0]['quote'] = 'An invented childhood story.'
    with pytest.raises(ValueError, match='quote'): suite.validate(item, proposal)


def test_response_size_is_bounded_before_retaining_application_evidence(tmp_path):
    class Huge(ControlledSkill):
        async def call(self, request):
            result = await super().call(request)
            result['output'] = 'x' * 300000
            return result
    result = asyncio.run(suite.run(selected('memoir-memory-context'), tmp_path, skill=Huge(), max_skill_calls=1))
    assert result['budgets']['skill']['dispatched'] == 1
    assert result['results'][0]['execution'] == 'unavailable'
    assert 'x' * 300000 not in (tmp_path / 'receipt.json').read_text()
