import pytest

from scripts.langfuse_dataset_names import canonical_dataset_name, dataset_name, skill_dataset, dataset_items_digest


def test_rename_verification_preserves_every_item_field_except_the_displayed_dataset_name():
    before = [{'id': 'item', 'datasetName': 'old', 'input': 'question', 'expectedOutput': 'answer'}]
    renamed = [{**before[0], 'datasetName': 'new'}]
    assert dataset_items_digest(before) == dataset_items_digest(renamed)
    changed_gold = [{**renamed[0], 'expectedOutput': 'different answer'}]
    assert dataset_items_digest(before) != dataset_items_digest(changed_gold)


def test_historical_suites_move_without_colliding_with_current_suites():
    old = ['memoir/evaluation/skill-triggers', 'memoir/archive/v2/skill-triggers',
        'memoir/evaluation/event-grounding', 'memoir/issue6/20261008-v1/event-grounding',
        'memoir/evaluation/v4/lane-a/abc123', 'memoir/evaluation/v4/lane-a/def456']
    new = [canonical_dataset_name(name) for name in old]
    assert len(new) == len(set(new))
    assert new[0] == 'memoir/workflows/skill-admission/golden/core'
    assert new[4] == 'memoir/agents/mira/reply/golden/campaign-abc123'
    assert all(canonical_dataset_name(name) == name for name in new)


def test_interviewer_dataset_uses_mira_without_changing_the_skill_selector():
    assert skill_dataset('memoir-interviewer') == 'memoir/agents/mira/reply/golden/core'


@pytest.mark.parametrize('name', ['memoir/unknown/data', 'another-project/evaluation/workflows'])
def test_unknown_datasets_require_classification(name):
    with pytest.raises(ValueError, match='Unclassified dataset'):
        canonical_dataset_name(name)


def test_path_segments_cannot_create_extra_folders():
    with pytest.raises(ValueError):
        dataset_name('golden', 'memoir-mira', 'reply/other')


def test_legacy_publisher_splits_each_phase_by_real_skill_target(monkeypatch):
    from scripts import run_memoir_skill_evaluation as runner
    from scripts.langfuse_dataset_names import SKILL_TASKS, dataset_target
    skills=set(SKILL_TASKS)-{'memoir-interviewer'}
    # Composer uses the checkpoint workflow; external calls are replaced only at
    # the case-catalog boundary so this exercises the real dataset grouping.
    cases=[dict(id=skill,skill=skill,instructions='Synthetic instructions',input={},schema={},validator='fixture')
           for skill in skills-{'memoir-composer'}]
    monkeypatch.setattr(runner,'cases',lambda:cases)
    monkeypatch.setattr(runner,'manifest',lambda:{'skills':sorted(skills)})
    grouped=runner.datasets()
    assert len(grouped)==18
    for phase in ('triggers','deliveries'):
        rows=[(name,items) for name,items in grouped.items() if runner.DATASET_PHASES[name]==phase]
        assert {item['input']['skill'] for _,items in rows for item in items}==skills
        for name,items in rows:
            assert len({item['input']['skill'] for item in items})==1
            target=dataset_target(name)
            assert target.startswith('memoir/') and 'memoir-workflows' not in target
