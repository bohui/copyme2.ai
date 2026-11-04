from copy import deepcopy
import json
from pathlib import Path

import pytest

from scripts.check_langfuse_evaluation_bindings import validate
from scripts.prompt_registry import prompt_registry

ROOT=Path(__file__).resolve().parents[1]


def bindings():
    return json.loads((ROOT/'config/langfuse-evaluation-bindings.json').read_text())


def test_real_bindings_preserve_split_lineage_and_resolve_every_prompt():
    result=validate(bindings(),prompt_registry(include_unpublished=True))
    assert result['datasets'] >= 36


def test_summary_target_binds_the_instructions_actually_sent_to_the_model():
    from apps.api.lifetime_memory_summary import summary_contract
    from apps.api.model_request import instruction_manifest
    instructions, schema = summary_contract()
    actual = {p['name'] for p in instruction_manifest(instructions, schema)['artifacts']}
    target = bindings()['targets']['memoir/skills/author-timeline/summarize']
    assert actual <= set(target['evaluated_prompts'])


def test_production_target_binds_the_executed_stage_and_its_adapters():
    target = bindings()['targets']['memoir/skills/story-game/production']
    prefix = 'memoir/skills/story-game/novel-to-game/'
    assert target['primary_prompt'] == prefix+'production'
    assert {prefix+p for p in ('production','adapter','journey','assets')} <= set(target['evaluated_prompts'])


def test_missing_shared_component_is_rejected_even_if_the_primary_is_registered():
    cfg=bindings()
    target=cfg['targets']['memoir/skills/composer/review']
    target['evaluated_prompts'].remove('memoir/skills/composer/shared/editorial-review')
    with pytest.raises(ValueError,match='Missing composed prompt dependency'):
        validate(cfg,prompt_registry(include_unpublished=True))


@pytest.mark.parametrize('mutation',['foreign_target','unknown_prompt','missing_item','duplicate_item','double_sampling','self_judging'])
def test_invalid_bindings_fail_before_publication(mutation):
    cfg=bindings()
    if mutation=='foreign_target':cfg['datasets'][0]['target']='memoir/agents/other/reply'
    elif mutation=='unknown_prompt':next(iter(cfg['targets'].values()))['evaluated_prompts'].append('memoir/missing')
    elif mutation=='missing_item':
        next(d for d in cfg['datasets'] if d['source_dataset_id'])['source_item_ids'].pop()
    elif mutation=='duplicate_item':
        child=next(d for d in cfg['datasets'] if d['source_dataset_id'])
        child['source_item_ids'].append(child['source_item_ids'][0])
    elif mutation=='double_sampling':cfg['online'].append(deepcopy(cfg['online'][0]))
    else:
        rule=cfg['online'][0];rule['target']='memoir/evaluators/shared/relevance';rule['name']=rule['target']+'/online/quality'
    with pytest.raises(ValueError):validate(cfg,prompt_registry(include_unpublished=True))
