"""Check that every dataset and rule resolves to an explicit evaluation target."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.langfuse_dataset_names import dataset_target
from scripts.prompt_registry import prompt_registry
from apps.api.prompt_composition import component_paths


def validate(config, prompts):
    root = Path(__file__).resolve().parents[1]
    by_path = {str(root/p):n for n,p in prompts.items()}
    targets = config['targets']
    datasets = config['datasets']
    if len({d['name'] for d in datasets}) != len(datasets) or len({d['id'] for d in datasets}) != len(datasets):
        raise ValueError('Duplicate dataset name or ID')
    by_id = {d['id']: d for d in datasets}
    for target, spec in targets.items():
        unknown = set(spec['evaluated_prompts']) - set(prompts)
        if unknown:
            raise ValueError('Unknown evaluated prompt: ' + ', '.join(sorted(unknown)))
        if spec['primary_prompt'] and spec['primary_prompt'] not in spec['evaluated_prompts']:
            raise ValueError('Primary prompt missing from target binding')
        for name in spec['evaluated_prompts']:
            components = {by_path[str(path)] for path in component_paths((root/prompts[name]).read_text())}
            if not components <= set(spec['evaluated_prompts']):
                raise ValueError('Missing composed prompt dependency: '+name)
        if spec['scope'] == 'code' and (spec['evaluated_prompts'] or not spec['validator']):
            raise ValueError('Deterministic target must declare its validator and no model prompt')
    for row in datasets:
        if dataset_target(row['name']) != row['target'] or row['target'] not in targets:
            raise ValueError('Dataset path does not identify its target')
        spec = targets[row['target']]
        if row['evaluated_prompts'] != spec['evaluated_prompts']:
            raise ValueError('Dataset prompt binding differs from its target')
        if row['status'] == 'historical' and row['metrics']:
            raise ValueError('Historical aggregate must not be evaluated again')
        if row['source_dataset_id']:
            parent = by_id[row['source_dataset_id']]
            if parent['status'] != 'historical' or not set(row['source_item_ids']) <= set(parent['source_item_ids']):
                raise ValueError('Invalid split lineage')
    for parent in datasets:
        if parent['status'] != 'historical':
            continue
        children = [d for d in datasets if d['source_dataset_id'] == parent['id']]
        ids = [i for child in children for i in child['source_item_ids']]
        if len(ids) != len(set(ids)) or set(ids) != set(parent['source_item_ids']):
            raise ValueError('Split must preserve every source item exactly once')
    exact, prefixes = set(), []
    for rule in config['online']:
        if rule['name'] != rule['target'] + '/online/quality' or rule['target'] not in targets:
            raise ValueError('Online rule path does not identify its target')
        if rule['sampling'] != 0.1 or rule['metrics'] != ['relevance','completeness','safety']:
            raise ValueError('Online judging must retain the agreed 10% sample')
        if rule['target'].startswith('memoir/evaluators/'):
            raise ValueError('A judge must not evaluate itself')
        for name in rule['observation_names']:
            if name in exact or any(name.startswith(p) for p in prefixes):
                raise ValueError('Overlapping online rules would sample twice')
            exact.add(name)
        prefix = rule['observation_prefix']
        if prefix:
            if any(n.startswith(prefix) for n in exact) or any(p.startswith(prefix) or prefix.startswith(p) for p in prefixes):
                raise ValueError('Overlapping online rule prefixes')
            prefixes.append(prefix)
    return {'targets':len(targets),'datasets':len(datasets),'online_rules':len(config['online'])}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bindings',type=Path,default=ROOT/'config/langfuse-evaluation-bindings.json')
    args=parser.parse_args()
    print(json.dumps(validate(json.loads(args.bindings.read_text()),prompt_registry(include_unpublished=True))))


if __name__=='__main__':
    main()
