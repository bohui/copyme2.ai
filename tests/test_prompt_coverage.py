"""Prompt changes must retain source, dataset and evaluator accountability."""
import json

import pytest

from scripts.audit_prompt_coverage import ROOT, rows, validate, validate_source_inventory, validate_snapshot
from scripts.prompt_registry import prompt_registry


def inputs():
    return (json.loads((ROOT/'config/prompt-coverage.json').read_text()),
            json.loads((ROOT/'config/langfuse-evaluation-bindings.json').read_text()))


def test_every_retained_prompt_has_a_current_source_and_evaluation_review():
    coverage, bindings = inputs()
    assert validate(coverage, bindings)['prompts'] == len(prompt_registry(include_unpublished=True))
    assert len(coverage['retired']) == 1


def test_a_new_prompt_file_cannot_escape_review_by_omitting_the_catalog(tmp_path):
    path=tmp_path/'apps/api/prompts/unregistered.md'
    path.parent.mkdir(parents=True)
    path.write_text('New model instructions')
    with pytest.raises(ValueError,match='Unregistered prompt source'):
        validate_source_inventory({},tmp_path)


@pytest.mark.parametrize('mutation', ['missing_prompt', 'stale_prompt', 'stale_dataset',
    'stale_evaluator', 'missing_reason', 'missing_consumer'])
def test_incomplete_or_stale_prompt_reviews_fail_before_publication(mutation):
    coverage, bindings = inputs()
    name='memoir/agents/mira/reply'
    entry=coverage['prompts'][name]
    if mutation=='missing_prompt': del coverage['prompts'][name]
    elif mutation=='stale_prompt': entry['review']['prompt_sha256']='0'*64
    elif mutation=='stale_dataset':
        next(d for d in bindings['datasets'] if d['target']==name)['source_item_ids'].append('new-case')
    elif mutation=='stale_evaluator': bindings['targets'][name]['metrics'].append('new-requirement')
    elif mutation=='missing_reason': entry['review']['dataset_decision']=''
    else: entry['consumers']=['apps/api/conversation_reply.py:removed_consumer']
    with pytest.raises(ValueError): validate(coverage, bindings)


def test_scored_dataset_items_do_not_certify_an_unverified_prompt_version():
    coverage, bindings = inputs()
    dataset=next(d for d in bindings['datasets'] if d['target']=='memoir/agents/mira/reply' and d['status']=='active')
    snapshot={'datasets':[dict(name=dataset['name'],runs=[{'id':'observed-run'}],scored_experiment_items=10)]}
    row=next(r for r in rows(coverage,bindings,snapshot) if r['name']=='memoir/agents/mira/reply')
    assert any(d['scored_items']==10 for d in row['datasets'])
    assert any('do not establish this prompt version' in gap for gap in row['gaps'])


def test_missing_datasets_and_media_quality_remain_visible():
    coverage, bindings = inputs()
    report=rows(coverage,bindings)
    speech=next(r for r in report if r['name']=='memoir/workflows/speech/synthesis/en-AU')
    assert not speech['datasets']
    assert any('modality-specific' in gap for gap in speech['gaps'])
    assert all(r['gaps'] for r in report if r['use']=='judge')


@pytest.mark.parametrize('mutation',['project','dataset','judge'])
def test_live_metadata_drift_is_distinct_from_declared_coverage(mutation):
    _, bindings=inputs()
    observed=json.loads((ROOT/'docs/prompt-audit-live.json').read_text())
    if mutation=='project':observed['project_id']='other-project'
    elif mutation=='dataset':observed['datasets'][0]['id']='different-dataset'
    else:
        next(e for e in observed['hosted_metadata']['evaluators'] if e['type']=='LLM_AS_JUDGE')['prompt_sha256']='0'*64
    with pytest.raises(ValueError):validate_snapshot(observed,bindings)
