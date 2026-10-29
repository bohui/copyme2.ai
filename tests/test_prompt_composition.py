import hashlib
import json
from types import SimpleNamespace

import pytest

from apps.api import prompt_composition as composition
from apps.api.memory_events import extraction_instructions
from apps.api.memoir_preview import composer_instructions
from apps.api.prompt_artifact import load_prompt_artifact, prompt_path
from scripts.evaluate_langfuse_prompt import experiment_task
from scripts.prompt_registry import ROOT, prompt_registry


def replace_component(monkeypatch, tmp_path, key, text):
    original = ROOT / composition.COMPONENTS[key]
    receipt = json.loads(original.with_name(original.name + '.langfuse.json').read_text())
    path = tmp_path / original.name
    path.write_text(text)
    receipt.update(version=receipt['version'] + 1, sha256=hashlib.sha256(text.encode()).hexdigest())
    path.with_name(path.name + '.langfuse.json').write_text(json.dumps(receipt))
    monkeypatch.setitem(composition.COMPONENTS, key, str(path))
    return path, receipt


def test_one_timeline_skill_version_reaches_both_extraction_schemas(monkeypatch, tmp_path):
    changed = 'Updated shared timeline policy.\n'
    path, _ = replace_component(monkeypatch, tmp_path, 'author_timeline', changed)
    for derived in (False, True):
        instructions = extraction_instructions(derived_hints=derived)
        assert instructions.startswith(changed)
        assert instructions.count(changed) == 1
        assert ('place_journeys' in instructions) is derived
    path.write_text('Unexported local edit')
    with pytest.raises(ValueError, match='Invalid Langfuse prompt artifact'):
        extraction_instructions()


def test_one_editorial_component_reaches_drafting_review_and_evaluation(monkeypatch, tmp_path):
    changed = 'Updated shared narrative policy.\n'
    _, receipt = replace_component(monkeypatch, tmp_path, 'narrative_enrichment', changed)
    for phase in ('draft', 'review'):
        instructions = composer_instructions(phase)
        assert instructions.count(changed) == 1
        path = prompt_path(f'memoir/skills/memoir-composer/{phase}')
        prompt = SimpleNamespace(prompt=load_prompt_artifact(path))
        calls = []
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
            create=lambda **kwargs: calls.append(kwargs) or SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content='reply'))]))))
        task = experiment_task(prompt, 'fixture', client,
            instructions=composition.render_prompt_artifact(path, content=prompt.prompt))
        assert task(item=SimpleNamespace(input='Synthetic memory')) == 'reply'
        assert calls[0]['messages'][0]['content'] == instructions
        manifest = composition.composition_receipt(path)
        assert receipt in manifest['components']
        assert manifest['sha256'] == hashlib.sha256(instructions.encode()).hexdigest()


def test_unknown_or_nested_prompt_components_fail_closed(monkeypatch, tmp_path):
    path = ROOT / 'skills/memoir-composer/prompts/review.md'
    with pytest.raises(ValueError, match='Unknown prompt component'):
        composition.render_prompt_artifact(path, content='{{prompt:missing}}')
    with pytest.raises(ValueError, match='malformed reference'):
        composition.render_prompt_artifact(path, content='{{prompt:unfinished')
    replace_component(monkeypatch, tmp_path, 'narrative_enrichment', '{{prompt:editorial_review}}')
    with pytest.raises(ValueError, match='Nested prompt components'):
        composition.render_prompt_artifact(path)


def test_policy_review_uses_one_agent_prompt_for_both_output_schemas():
    from apps.api.policy_review import PolicyReview, PolicyReviewOpening
    review = composition.render_prompt_artifact(prompt_path('memoir/agents/mira/policy-review'))
    assert 'acknowledgement_requested=true' in review
    assert 'acknowledgement' not in PolicyReview.model_json_schema()['properties']
    assert 'acknowledgement' in PolicyReviewOpening.model_json_schema()['properties']
    assert not composition.component_paths(review)


def test_shared_sources_have_one_registry_name_and_no_embedded_policy_copies():
    registry = prompt_registry()
    texts = {name: load_prompt_artifact(ROOT / relative) for name, relative in registry.items()}
    for relative in composition.COMPONENTS.values():
        assert list(registry.values()).count(relative) == 1
        body = load_prompt_artifact(ROOT / relative).strip()
        assert not any(body in text for name, text in texts.items() if registry[name] != relative)
    assert all('{{prompt:' not in composition.render_prompt_artifact(ROOT / relative)
               for relative in registry.values())
