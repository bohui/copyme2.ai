"""Product skills include foreground prompt owners as well as background lanes."""
import hashlib
from pathlib import Path

from apps.api.background_skills import SKILLS
from apps.api.prompt_catalog import PROMPT_PATHS

ROOT = Path(__file__).resolve().parents[1]


def skill_inventory():
    owners = {name.split('/')[2] for name in PROMPT_PATHS if name.startswith('memoir/skills/')}
    result = {}
    for name in sorted(set(SKILLS) | owners):
        definition = SKILLS.get(name)
        paths = sorted({path for prompt, path in PROMPT_PATHS.items()
                        if prompt.startswith(f'memoir/skills/{name}/')})
        package = f'skills/{name}/SKILL.md'
        if (ROOT / package).is_file() and package not in paths:
            paths.append(package)
        if not paths:
            raise ValueError('skill_has_no_instruction_sources')
        result[name] = dict(
            execution=definition.execution if definition else 'foreground_model',
            production_status=definition.status if definition else 'implemented',
            sources=paths,
            sha256=hashlib.sha256(b''.join(
                path.encode() + b'\0' + (ROOT / path).read_bytes() + b'\0'
                for path in paths)).hexdigest())
    return result
