import hashlib
import json

import pytest

from apps.api import prompt_composition as composition
from apps.api.memory_events import extraction_instructions
from apps.api.memoir_preview import composer_instructions
from apps.api.prompt_artifact import load_prompt_artifact, prompt_path
from apps.api.prompt_catalog import PROMPT_PATHS
from scripts.run_memoir_skill_evaluation import evaluation_manifest
from scripts.prompt_registry import ROOT, prompt_registry


def test_compatibility_place_hints_are_owned_by_timeline():
    from apps.api.two_lane_memory import extraction_contract
    from apps.api.model_request import instruction_manifest
    instructions, schema = extraction_contract()
    assert '{{prompt:' not in instructions
    assert 'Read saved canonical' in instructions and 'place_journeys' in instructions
    assert {'events', 'place_journeys'} <= set(schema['required'])
    primary = 'memoir/skills/author-timeline/extract'
    assert [p['name'] for p in instruction_manifest(instructions, schema, primary_name=primary)['artifacts']] == [primary]


def replace_template(monkeypatch, tmp_path, name, text):
    original = prompt_path(name)
    receipt = json.loads(original.with_name(original.name + '.langfuse.json').read_text())
    receipt.pop('source_sha256', None)
    path = tmp_path / original.name
    path.write_text(text)
    receipt.update(version=receipt['version'] + 1, sha256=hashlib.sha256(text.encode()).hexdigest())
    path.with_name(path.name + '.langfuse.json').write_text(json.dumps(receipt))
    monkeypatch.setitem(PROMPT_PATHS, name, str(path))
    return path, receipt


def test_one_timeline_skill_version_reaches_both_extraction_schemas(monkeypatch, tmp_path):
    from apps.api.two_lane_memory import extraction_contract
    changed = 'Updated timeline policy.\n'
    name = 'memoir/skills/author-timeline/extract'
    path, _ = replace_template(monkeypatch, tmp_path, name, changed + load_prompt_artifact(prompt_path(name)))
    instructions, schema = extraction_contract()
    assert 'place_journeys' in schema['required']
    for text in (extraction_instructions(), instructions):
        assert text.startswith(changed)
        assert text.count(changed) == 1
    path.write_text('Unpublished local edit')
    with pytest.raises(ValueError, match='Invalid Langfuse prompt artifact'):
        extraction_instructions()


def test_each_editorial_template_is_used_by_its_phase_and_evaluation(monkeypatch, tmp_path):
    changed = 'Updated editorial policy.\n'
    for phase, other in (('draft', 'review'), ('review', 'draft')):
        baseline = composer_instructions(other)
        name = f'memoir/skills/composer/{phase}'
        with monkeypatch.context() as patch:
            _, receipt = replace_template(patch, tmp_path, name, changed + load_prompt_artifact(prompt_path(name)))
            instructions = composer_instructions(phase)
            assert instructions.count(changed) == 1
            assert composer_instructions(other) == baseline
            evaluated = evaluation_manifest(instructions)
            assert dict(name=name, version=receipt['version'], sha256=receipt['sha256'], status='published') in evaluated['artifacts']
            assert evaluated['prompt_sha256'] == hashlib.sha256(instructions.encode()).hexdigest()


def test_unknown_or_cyclic_prompt_components_fail_closed():
    path = prompt_path('memoir/skills/composer/review')
    for unresolved in ('{{prompt:missing}}', '{{prompt:unfinished', '{{prompt:review}}'):
        with pytest.raises(ValueError, match='self-contained'):
            composition.render_prompt_artifact(path, content=unresolved)


def test_policy_review_uses_one_agent_prompt_for_both_output_schemas():
    from apps.api.policy_review import PolicyReview, PolicyReviewOpening
    review = composition.render_prompt_artifact(prompt_path('memoir/agents/mira/policy-review'))
    assert 'acknowledgement_requested=true' in review
    assert 'acknowledgement' not in PolicyReview.model_json_schema()['properties']
    assert 'acknowledgement' in PolicyReviewOpening.model_json_schema()['properties']
    assert '{{prompt:' not in review


def test_each_operation_has_one_self_contained_registry_source():
    registry = prompt_registry()
    assert len(registry) == len(set(registry.values()))
    for name, relative in registry.items():
        path = ROOT / relative
        assert composition.expanded_prompt(path) == path.read_text(), name
        assert '{{prompt:' not in composition.render_prompt_artifact(path), name
