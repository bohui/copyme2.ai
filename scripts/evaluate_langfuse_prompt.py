#!/usr/bin/env python3
"""Select the current scenario dataset and graders from one managed prompt name."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.prompt_registry import prompt_registry


def prompt_pin(name):
    from apps.api.prompt_artifact import load_prompt_artifact
    registry = prompt_registry()
    if name not in registry:
        raise ValueError('Use a managed prompt name, for example memoir/agents/mira/reply')
    path = ROOT / registry[name]
    load_prompt_artifact(path)
    pin = json.loads(Path(str(path) + '.langfuse.json').read_text())
    if pin['name'] != name:
        raise ValueError('Published receipt belongs to another prompt')
    return pin


def select_cases(names, cases):
    """Prefer the prompt's own runnable target; share workflow cases for components."""
    from scripts.langfuse_dataset_names import SKILL_TARGETS
    targets = json.loads((ROOT / 'config/langfuse-evaluation-bindings.json').read_text())['targets']
    supported = {SKILL_TARGETS[c['skill']] for c in cases}
    selected_targets = set()
    for name in names:
        prompt_pin(name)
        candidates = {target for target, spec in targets.items()
            if name in spec['evaluated_prompts'] and target in supported}
        primary = {target for target in candidates if targets[target]['primary_prompt'] == name}
        selected_targets.update(primary or candidates)
    selected = [c for c in cases if SKILL_TARGETS[c['skill']] in selected_targets]
    if not selected:
        raise ValueError('No supported graded scenario for the requested prompts; see docs/prompt-coverage.md')
    return selected


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument('--name', help='Managed prompt name; dataset and graders are automatic')
    selection.add_argument('--skill', help='All managed prompts owned by a skill, for example author-timeline')
    parser.add_argument('--plan', action='store_true', help='Preview the selection without credentials or model calls')
    parser.add_argument('--credential-file', type=Path, default=Path.home() / 'llm_provider/.env')
    parser.add_argument('--env-file', type=Path, default=ROOT / '.env')
    parser.add_argument('--base-url', default='http://127.0.0.1:4000/v1')
    args, extra = parser.parse_known_args(argv)
    if any(value.split('=')[0] in {'--execute', '--publish', '--prompt', '--agent', '--component', '--judge'} for value in extra):
        parser.error('Execution and prompt selection are controlled by prompt-eval / prompt-eval-plan')
    names = ([args.name] if args.name is not None else [name for name in prompt_registry()
        if name.startswith('memoir/skills/' + args.skill.removeprefix('memoir-') + '/')])
    try:
        if not names:
            raise ValueError('No managed prompts owned by that skill')
        pins = [prompt_pin(name) for name in names]
    except ValueError as error:
        parser.error(str(error))
    common = ['--credential-file', str(args.credential_file), '--env-file', str(args.env_file)]
    if all(name.startswith('memoir/evaluators/') for name in names):
        from scripts.memoir_judge_calibration import judges
        from scripts.run_memoir_judge_calibration import main as calibrate
        selected = [name for name, spec in judges().items() if set(names) & set(spec['prompts'])]
        if not selected:
            parser.error('No shared calibration cases for the requested prompt')
        print(json.dumps(dict(prompts=pins, evaluator='scripts/run_memoir_judge_calibration.py:evaluations',
            selected_judges=selected)), flush=True)
        return calibrate(common + ['--base-url', args.base_url]
            + [v for name in selected for v in ('--judge', name)]
            + ([] if args.plan else ['--execute']) + extra)
    from scripts.run_memoir_agent_evaluation import main as evaluate
    return evaluate(common + [v for name in names for v in ('--prompt', name)]
        + ['--full', '--gateway-url', args.base_url,
        '--max-calls', '400', '--seconds', '7200', '--timeout', '150']
        + ([] if args.plan else ['--execute', '--publish']) + extra)


if __name__ == '__main__':
    raise SystemExit(main())
