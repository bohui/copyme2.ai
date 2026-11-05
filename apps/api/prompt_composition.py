"""One local composition recipe for runtime and dataset prompt inputs."""
import hashlib
import json
from pathlib import Path
import re

from .prompt_artifact import load_prompt_artifact

ROOT = Path(__file__).resolve().parents[2]
COMPONENTS = {
    'news_instructions': 'skills/memoir-historical-news-research/SKILL.md',
    'news_contract': 'skills/memoir-historical-news-research/references/contract.md',
    'news_discovery': 'skills/memoir-historical-news-research/prompts/discovery.md',
    'game_instructions': 'skills/memoir-story-game/SKILL.md',
    **{'game_' + phase: 'skills/memoir-story-game/prompts/' + phase + '.md'
       for phase in ('proposal', 'brief', 'higgsfield', 'webpage')},
    **{'novel_' + phase: 'skills/memoir-story-game/prompts/novel-to-game/' + phase + '.md'
       for phase in ('adapter', 'journey', 'assets', 'analyze', 'concept', 'design', 'whitebox', 'art', 'production')},
    'timeline_base': 'skills/memoir-author-timeline/prompts/extract.md',
    'narrator_profile': 'skills/memoir-memory-context/SKILL.md',
    'timeline_attribution': 'skills/memoir-author-timeline/prompts/attribution.md',
    'timeline_continuity': 'skills/memoir-author-timeline/prompts/continuity.md',
    'timeline_hints': 'skills/memoir-author-timeline/prompts/derived-hints.md',
    'place_extraction': 'skills/memoir-place-journey/references/two-lane.md',
    'place_conflicts': 'apps/api/prompts/shared/place-conflicts.md',
    'summary': 'skills/memoir-memory-context/prompts/summary.md',
    **{'composer_' + phase: 'skills/memoir-composer/prompts/' + phase + '.md'
       for phase in ('prepare', 'draft', 'review')},
    'batch_prepare': 'skills/memoir-composer/prompts/batch/prepare.md',
    'batch_compose': 'skills/memoir-composer/prompts/batch/compose.md',
    'author_timeline': 'skills/memoir-author-timeline/SKILL.md',
    'timeline_contract': 'skills/memoir-author-timeline/references/contract.md',
    'timeline_grounding': 'skills/memoir-author-timeline/prompts/shared/grounding.md',
    'narrative_enrichment': 'skills/memoir-composer/references/narrative-enrichment.md',
    'editorial_review': 'skills/memoir-composer/references/editorial-review.prompt.md',
    'lane_context': 'apps/api/prompts/shared/bounded-context/policy.md',
    'organiser_prefix': 'skills/memoir-composer/prompts/outline/shared/prefix.md',
    'organiser_suffix': 'skills/memoir-composer/prompts/outline/shared/suffix.md',
}
REFERENCE = re.compile(r'\{\{prompt:([^{}]+)\}\}')


def component_paths(template):
    paths = []
    def visit(text):
        for reference in REFERENCE.findall(text):
            key = reference.removesuffix('|trim')
            if key not in COMPONENTS:
                raise ValueError(f'Unknown prompt component: {key}')
            path = ROOT / COMPONENTS[key]
            if path not in paths:
                paths.append(path)
                visit(path.read_text(encoding='utf-8'))
    visit(template)
    return tuple(paths)


def expanded_prompt(path, *, content=None, root=ROOT, validate=True, seen=()):
    """Expand local source references for publication; retain template sections."""
    path = Path(path)
    if path in seen:
        raise ValueError('Cyclic prompt components')
    read = load_prompt_artifact if validate else lambda p: p.read_text(encoding='utf-8')
    template = read(path) if content is None else content
    def expand(match):
        key = match[1].removesuffix('|trim')
        if key not in COMPONENTS:
            raise ValueError(f'Unknown prompt component: {key}')
        result = expanded_prompt(root / COMPONENTS[key], root=root, validate=validate, seen=(*seen, path))
        return result.strip() if match[1].endswith('|trim') else result
    rendered = REFERENCE.sub(expand, template)
    if '{{prompt:' in rendered:
        raise ValueError('Unknown or malformed reference')
    return rendered


def render_prompt_artifact(path, *, content=None, variables=None):
    template = expanded_prompt(path, content=content)
    values = {**dict.fromkeys(('places', 'place_rules', 'attribution', 'continuity', 'batch', 'bounded', 'conflicts'), False),
              'events_only': True, **(variables or {})}
    section = re.compile(r'\{\{#(\w+)\}\}((?:(?!\{\{[#/]).)*?)\{\{/\1\}\}', re.S)
    while section.search(template):
        def choose(match):
            if match[1] not in values:
                raise ValueError('Unknown prompt section: ' + match[1])
            enabled = values[match[1]]
            if type(enabled) is not bool:
                raise ValueError('Prompt section requires a boolean: ' + match[1])
            return match[2] if enabled else ''
        template = section.sub(choose, template)
    if '{{#' in template or '{{/' in template:
        raise ValueError('Malformed prompt section')
    return re.sub(r'\{\{(\w+)\}\}', lambda m: str(values[m[1]]) if m[1] in values else m[0], template)


def composition_receipt(path, *, content=None):
    template = load_prompt_artifact(path) if content is None else content
    rendered = render_prompt_artifact(path, content=template)
    return {
        'sha256': hashlib.sha256(rendered.encode('utf-8')).hexdigest(),
        'components': [json.loads(part.with_name(part.name + '.langfuse.json').read_text())
                       for part in component_paths(template)],
    }
