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
