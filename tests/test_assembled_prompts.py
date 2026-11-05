"""Assembly preserves every reviewed fixed-worker instruction variant."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from apps.api.prompt_artifact import prompt_path
from apps.api.prompt_composition import expanded_prompt, render_prompt_artifact

FIXTURE = json.loads((Path(__file__).parent / 'fixtures/assembled-prompt-variants.json').read_text())


@pytest.mark.parametrize('case', FIXTURE['cases'])
def test_assembled_templates_preserve_original_instruction_bytes(case):
    instructions = render_prompt_artifact(prompt_path(case['name']), variables=case['variables'])
    assert '{{' not in instructions
    assert hashlib.sha256(instructions.encode()).hexdigest() == case['sha256']


def test_published_extraction_is_complete_and_has_one_operation_name():
    from apps.api.prompt_catalog import PROMPT_PATHS, LOCAL_PROMPT_NAMES
    names = {n for n in PROMPT_PATHS if n.startswith('memoir/skills/author-timeline/') and n not in LOCAL_PROMPT_NAMES}
    assert names == {'memoir/skills/author-timeline/extract'}
    template = expanded_prompt(prompt_path(next(iter(names))))
    assert '{{prompt:' not in template
    assert '# Memoir Author Timeline' in template
    assert '# Shared MemoryEvent service' in template
    assert 'passage_dispositions' in template
    assert 'continuity_updates' in template
    assert '{{#attribution}}' in template


@pytest.mark.parametrize('source', ['{{#enabled}}bad', '{{/enabled}}', '{{#a}}{{/b}}'])
def test_invalid_template_sections_fail_closed(source):
    with pytest.raises(ValueError, match='Malformed prompt section'):
        render_prompt_artifact(prompt_path('memoir/skills/memory-context/profile'), content=source)


def test_gateway_forwards_only_public_assembled_prompt_identity(monkeypatch):
    from apps.api import llm_tracing
    from test_llm_tracing import FakeLangfuse
    from opentelemetry import baggage, context
    tracer = FakeLangfuse()
    monkeypatch.setattr(llm_tracing, '_client_cache', tracer)
    token = context.attach(baggage.set_baggage('private_narration', 'never-forward-this'))
    manifest = {'artifacts': [dict(name='memoir/skills/memory-context/profile', version=1, status='published')]}
    try:
        with llm_tracing.trace_llm_call('profile', 'model', gateway=True, metadata={'prompt_manifest': manifest}):
            headers = llm_tracing.gateway_trace_headers()
        assert headers['baggage'] == 'langfuse_prompt_name=memoir%2Fskills%2Fmemory-context%2Fprofile,langfuse_prompt_version=1'
        assert 'private' not in str(headers) and 'never-forward-this' not in str(headers)
        assert not llm_tracing.gateway_trace_headers()
    finally:
        context.detach(token)
