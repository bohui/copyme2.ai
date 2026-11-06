"""Assembly preserves every reviewed fixed-worker instruction variant."""
import hashlib
import json
from pathlib import Path

import pytest

from apps.api.prompt_artifact import prompt_path
from apps.api.prompt_composition import expanded_prompt, render_prompt_artifact

FIXTURE = json.loads((Path(__file__).parent / 'fixtures/assembled-prompt-variants.json').read_text())


@pytest.mark.parametrize('case', FIXTURE['cases'])
def test_assembled_templates_match_reviewed_instruction_bytes(case):
    instructions = render_prompt_artifact(prompt_path(case['name']), variables=case['variables'])
    assert '{{' not in instructions
    assert hashlib.sha256(instructions.encode()).hexdigest() == case['sha256']


def test_extraction_is_complete_and_keeps_named_examples_separate():
    from apps.api.prompt_catalog import PROMPT_PATHS
    names = {n for n in PROMPT_PATHS if n.startswith('memoir/skills/author-timeline/')}
    assert names == {'memoir/skills/author-timeline/extract', 'memoir/skills/author-timeline/reconcile'}
    template = expanded_prompt(prompt_path('memoir/skills/author-timeline/extract'))
    assert '{{prompt:' not in template
    assert '# Memoir Author Timeline' in template
    rules, examples = template.split('## Worked examples', 1)
    examples, conditional_rules = examples.split('{{#events_only}}', 1)
    for place in ('Cairns', 'Darwin', '承德市', '大石庙镇', 'Bendigo', 'Toowoomba'):
        assert place in examples
        assert place not in rules + conditional_rules
    assert 'locationConfidenceScore' in rules and 'temporal_estimate' in rules
    assert 'passage_dispositions' in template
    assert 'continuity_updates' in template
    assert '{{#attribution}}' in template


@pytest.mark.parametrize('source', ['{{#enabled}}bad', '{{/enabled}}', '{{#a}}{{/b}}'])
def test_invalid_template_sections_fail_closed(source):
    with pytest.raises(ValueError, match='Malformed prompt section'):
        render_prompt_artifact(prompt_path('memoir/skills/memory-context/profile'), content=source)


@pytest.mark.parametrize('places', [False, True])
def test_one_managed_template_owns_each_fixed_request(places):
    from apps.api.model_request import instruction_manifest
    name = 'memoir/skills/author-timeline/extract'
    path = prompt_path(name)
    instructions = render_prompt_artifact(path, variables={
        'places': places, 'events_only': not places, 'place_rules': places})
    manifest = instruction_manifest(instructions, {}, primary_name=name)
    artifact, = manifest['artifacts']
    receipt = json.loads(path.with_name(path.name + '.langfuse.json').read_text())
    sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    published = receipt['sha256'] == sha256
    assert artifact == dict(name=name, sha256=sha256, version=receipt['version'] if published else None,
                           status='published' if published else 'unpublished')
