"""One local composition recipe for runtime and dataset prompt inputs."""
import hashlib
import json
from pathlib import Path
import re

from .prompt_artifact import load_prompt_artifact

ROOT = Path(__file__).resolve().parents[2]
COMPONENTS = {
    'author_timeline': 'skills/memoir-author-timeline/SKILL.md',
    'timeline_contract': 'skills/memoir-author-timeline/references/contract.md',
    'timeline_grounding': 'skills/memoir-author-timeline/prompts/shared/grounding.md',
    'collector_guidance': 'skills/memoir-interviewer/prompts/guidance.md',
    'strategy_selection': 'skills/memoir-interviewer/prompts/strategy/selection.md',
    'policy_review': 'skills/memoir-interviewer/prompts/policy-review.md',
    'narrative_enrichment': 'skills/memoir-composer/references/narrative-enrichment.md',
    'editorial_review': 'skills/memoir-composer/references/editorial-review.prompt.md',
    'lane_context': 'apps/api/prompts/shared/bounded-context/policy.md',
    'organiser_prefix': 'skills/memoir-composer/prompts/outline/shared/prefix.md',
    'organiser_suffix': 'skills/memoir-composer/prompts/outline/shared/suffix.md',
}
REFERENCE = re.compile(r'\{\{prompt:([^{}]+)\}\}')


def component_paths(template):
    try:
        return tuple(dict.fromkeys(ROOT / COMPONENTS[key] for key in REFERENCE.findall(template)))
    except KeyError as error:
        raise ValueError(f'Unknown prompt component: {error.args[0]}') from None


def render_prompt_artifact(path, *, content=None):
    template = load_prompt_artifact(path) if content is None else content
    parts = {path: load_prompt_artifact(path) for path in component_paths(template)}
    rendered = REFERENCE.sub(lambda match: parts[ROOT / COMPONENTS[match[1]]], template)
    if '{{prompt:' in rendered:
        raise ValueError('Nested prompt components or malformed reference')
    return rendered


def composition_receipt(path, *, content=None):
    template = load_prompt_artifact(path) if content is None else content
    rendered = render_prompt_artifact(path, content=template)
    return {
        'sha256': hashlib.sha256(rendered.encode('utf-8')).hexdigest(),
        'components': [json.loads(part.with_name(part.name + '.langfuse.json').read_text())
                       for part in component_paths(template)],
    }
