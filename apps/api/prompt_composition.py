"""Render a complete operation template from its checked-in Markdown."""
from pathlib import Path
import re

from .prompt_artifact import load_prompt_artifact


def expanded_prompt(path, *, content=None, validate=True):
    """Read the same self-contained template that is published to Langfuse."""
    path = Path(path)
    template = (load_prompt_artifact(path) if validate else path.read_text(encoding='utf-8')) if content is None else content
    if '{{prompt:' in template:
        raise ValueError('Prompt templates must be self-contained; inline the referenced text')
    return template


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
