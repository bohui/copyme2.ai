"""Reconcile prompt consumers, evaluation bindings and reviewed change receipts.

The offline check proves inventory and provenance, never model quality. A live
snapshot supplies dataset execution counts without changing that distinction.
"""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.api.prompt_composition import component_paths
from scripts.prompt_registry import prompt_registry


def digest(value):
    raw = value if isinstance(value, bytes) else json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    return hashlib.sha256(raw).hexdigest()


def validate_source_inventory(registry, root=ROOT):
    discovered=set()
    for directory in [root/'apps/api/prompts',root/'tests/evaluation/prompts',
                      *(root/'skills').glob('memoir-*/prompts')]:
        discovered.update(str(p.relative_to(root)) for p in directory.rglob('*.md'))
    unknown=discovered-set(registry.values())
    if unknown:
        raise ValueError('Unregistered prompt source: '+', '.join(sorted(unknown)))


def source_location(reference, root=ROOT):
    relative, symbol = reference.split(':', 1)
    path = root / relative
    if not path.is_file():
        raise ValueError('Missing source consumer: '+reference)
    if path.suffix == '.json' and symbol.startswith('/'):
        value=json.loads(path.read_text())
        for key in symbol.strip('/').split('/'):
            value=value[int(key)] if isinstance(value,list) else value[key]
        return dict(path=relative,symbol=symbol,line=1)
    if path.suffix != '.py':
        raise ValueError('Unsupported consumer reference: '+reference)
    tree = ast.parse(path.read_text())
    found = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
             and n.name == symbol]
    if not found:
        raise ValueError('Missing source symbol: '+reference)
    return dict(path=relative, symbol=symbol, line=min(n.lineno for n in found))


def review_digest(targets, bindings, *, evaluator=False, root=ROOT):
    datasets = [d for d in bindings['datasets'] if d['target'] in targets]
    if not evaluator:
        return digest(datasets)
    from scripts.prompt_registry import EVALUATION_PROMPT_PATHS
    return digest(dict(targets={t:bindings['targets'][t] for t in targets},
        configuration=json.loads((root/'config/langfuse-evaluators.json').read_text()),
        judges={n:digest((root/p).read_bytes()) for n,p in EVALUATION_PROMPT_PATHS.items()}))


def validate(coverage, bindings, registry=None, *, root=ROOT):
    registry = prompt_registry(root, include_unpublished=True) if registry is None else registry
    entries = coverage['prompts']
    if set(entries) != set(registry):
        raise ValueError('Prompt coverage inventory differs: '+', '.join(sorted(set(entries)^set(registry))))
    validate_source_inventory(registry,root)
    for name, relative in registry.items():
        entry = entries[name]
        if not entry['scenario'].strip() or not entry['consumers'] or not entry['regressions']:
            raise ValueError('Missing prompt scenario, consumer or regression: '+name)
        for reference in entry['consumers']:
            source_location(reference, root)
        for selector in entry['regressions']:
            if not (root/selector.split('::')[0]).is_file():
                raise ValueError('Missing regression dataset: '+selector)
        targets = sorted(t for t,s in bindings['targets'].items() if name in s['evaluated_prompts'])
        if not targets:
            raise ValueError('Prompt has no evaluation target: '+name)
        review = entry['review']
        if review['prompt_sha256'] != digest((root/relative).read_bytes()):
            raise ValueError('Prompt changed; review datasets and evaluators: '+name)
        if review['datasets_sha256'] != review_digest(targets, bindings):
            raise ValueError('Dataset binding changed; record prompt evaluation review: '+name)
        if review['evaluators_sha256'] != review_digest(targets, bindings, evaluator=True, root=root):
            raise ValueError('Evaluator changed; record prompt evaluation review: '+name)
        for key in ('dataset_decision', 'evaluator_decision'):
            if not review[key].strip():
                raise ValueError('Evaluation review needs a reason: '+name)
    for name, retired in coverage.get('retired', {}).items():
        if name in registry or (root/retired['source']).exists():
            raise ValueError('Retired prompt still active: '+name)
        if not (root/retired['archive']).is_file():
            raise ValueError('Retired prompt has no recovery archive: '+name)
        archived=[r for r in json.loads((root/retired['archive']).read_text()) if r['name']==name]
        if len(archived)!=1 or not archived[0].get('published_versions'):
            raise ValueError('Retired prompt needs every published recovery version: '+name)
        saved=archived[0]
        if saved['source']!=retired['source'] or saved['receipt']['sha256']!=digest(saved['content'].encode()):
            raise ValueError('Retired prompt source archive is invalid: '+name)
        for version in saved['published_versions']:
            if version['sha256']!=digest(version['prompt'].encode()):
                raise ValueError('Retired publication archive is invalid: '+name)
    return {'prompts':len(entries), 'retired':len(coverage.get('retired', {}))}


def rows(coverage, bindings, snapshot=None, *, root=ROOT):
    snapshot = snapshot or {}
    live = {d['name']:d for d in snapshot.get('datasets', [])}
    hosted=snapshot.get('hosted_metadata') or {}
    judges={e['id']:e for e in hosted.get('evaluators',[])}
    assignments={}
    for a in hosted.get('assignments',[]):
        assignments.setdefault(a['evaluation_rule_id'],[]).append(judges[a['evaluator_id']]['name'])
    result = []
    for name, relative in sorted(prompt_registry(root, include_unpublished=True).items()):
        entry = coverage['prompts'][name]
        targets = [t for t,s in bindings['targets'].items() if name in s['evaluated_prompts']]
        datasets = [d for d in bindings['datasets'] if d['target'] in targets and d['status']=='active']
        pin = json.loads((root/(relative+'.langfuse.json')).read_text())
        metrics = sorted({m for t in targets for m in bindings['targets'][t]['metrics']})
        relevant_rules=[r for r in hosted.get('rules',[]) if r['status']=='ACTIVE' and (
            r['name'] in {t+'/online/quality' for t in targets} or
            any(f.get('column')=='experimentDatasetId' and set(f.get('value',[])) & {d['id'] for d in datasets} for f in r['filter']))]
        evaluators=sorted({n for r in relevant_rules for n in assignments.get(r['id'],[])})
        sdk_evaluators=sorted({d['evaluator'] for d in datasets if d.get('evaluator')})
        declared=['memoir/evaluators/shared/'+m if m in {'correctness','relevance','completeness','safety'}
            else m+' (requires code/reference or manual grading)' for m in metrics]
        evidence = [dict(name=d['name'], id=d['id'], items=len(d['source_item_ids']),
            experiments=len(live.get(d['name'], {}).get('runs', [])),
            scored_items=live.get(d['name'], {}).get('scored_experiment_items'),
            source='live snapshot' if d['name'] in live else 'binding declaration') for d in datasets]
        gaps = []
        if not datasets: gaps.append('No active hosted dataset')
        if not evaluators: gaps.append('No active hosted grader verified; use the declared regression/calibration path')
        if entry['use']=='judge': gaps.append('Human calibration not established by wiring/contract tests')
        if entry['use']=='media': gaps.append('Audio/visual quality requires modality-specific review')
        if entry['use']=='conditional': gaps.append('Requires scenario/branch-specific execution evidence')
        if datasets and not any(d['scored_items'] for d in evidence):
            gaps.append('No scored experiment items verified for the current pin')
        elif datasets:
            gaps.append('Dataset scores alone do not establish this prompt version was exercised')
        result.append(dict(name=name, source=relative, version=pin['version'], sha256=pin['sha256'],
            use=entry['use'], scenario=entry['scenario'], consumers=[source_location(r,root) for r in entry['consumers']],
            targets=targets, evaluators=evaluators, sdk_evaluators=sdk_evaluators, declared_metrics=declared,
            hosted_rule_ids=[r['id'] for r in relevant_rules], datasets=evidence, regressions=entry['regressions'], gaps=gaps))
    return result


def validate_snapshot(snapshot, bindings, registry=None, *, root=ROOT):
    registry=prompt_registry(root,include_unpublished=True) if registry is None else registry
    if snapshot['project_id']!=bindings['project_id']:
        raise ValueError('Prompt audit snapshot belongs to another project')
    actual={d['name']:d for d in snapshot['datasets']}
    for dataset in bindings['datasets']:
        if dataset['name'] not in actual or actual[dataset['name']]['id']!=dataset['id']:
            raise ValueError('Dataset identity differs from verified snapshot: '+dataset['name'])
    for judge in snapshot.get('hosted_metadata',{}).get('evaluators',[]):
        if judge['type']=='LLM_AS_JUDGE' and judge['name'] in registry:
            if digest((root/registry[judge['name']]).read_bytes())!=judge['prompt_sha256']:
                raise ValueError('Hosted evaluator differs from reviewed prompt: '+judge['name'])


def upstream_sources(root=ROOT):
    from importlib import import_module
    runner=import_module('experiments.novel-to-game.stages')
    lock=json.loads((root/'deps/novel-to-game.lock.json').read_text())
    owners={}
    for stage,config in runner.STAGES.items():
        for relative in [config['skill']+'/SKILL.md', *[config['skill']+'/references/'+p for p in config['refs']]]:
            owners.setdefault('skills/'+relative,[]).append(stage)
    result=[]
    for relative,stages in sorted(owners.items()):
        path=root/'deps/novel-to-game'/relative
        sha=digest(path.read_bytes())
        if sha!=lock['files'][relative]:
            raise ValueError('Changed upstream prompt needs dependency lock review: '+relative)
        result.append(dict(source=str(path.relative_to(root)),sha256=sha,revision=lock['revision'],stages=stages))
    return result


def example_sources(root=ROOT):
    """Keep frozen example instructions distinct from supported runtime prompts."""
    base='experiments/novel-to-game/examples/age-eight-patch/'
    runner=root/(base+'stages.py')
    tree=ast.parse(runner.read_text())
    stages=next(n.value for n in tree.body
        if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='STAGES' for t in n.targets))
    # STAGES uses dict(...) calls, so enumerate its task literals without executing it.
    tasks=[keyword.value for stage in stages.values for keyword in stage.keywords if keyword.arg=='task']
    if not tasks or any(not isinstance(task,ast.Constant) or not isinstance(task.value,str) for task in tasks):
        raise ValueError('Frozen example task inventory changed; review the prompt scope')
    consumer=source_location(base+'stages.py:run_stage',root)
    return [dict(source=base+'adapter.md',consumer=consumer,
        sha256=digest((root/(base+'adapter.md')).read_bytes()),kind='Frozen example adapter'),
        dict(source=base+'stages.py',consumer=consumer,sha256=digest(runner.read_bytes()),
            kind=f'Frozen inline stage tasks ({len(tasks)})')]


def markdown(report, upstream=(), retired=None, examples=()):
    lines=['# Prompt coverage inventory', '',
        'Generated by `python3 scripts/audit_prompt_coverage.py --write`. See [the audit report](prompt-audit.md) for scope and quality limitations.', '',
        'See [the current execution report](prompt-evaluation-20261104.md) and [judge calibration results](judge-calibration-20261104.md) for version-specific observed outcomes and remaining gaps.', '',
        'A binding is a permitted dependency set, not proof of execution. Dataset counts are not prompt-version coverage. Regression selectors exercise controlled code; they do not certify live model quality.', '',
        'One dataset, evaluator and evaluation run may cover multiple prompts. Shared associations count for every linked prompt; actual case manifests establish which prompts and conditional branches ran.', '',
        '| Prompt / source pin | Source consumers | Scenario | Evaluator / regression | Active datasets (ID; items; experiments / scored items) | Gaps |',
        '| --- | --- | --- | --- | --- | --- |']
    for r in report:
        prompt=f"`{r['name']}` v{r['version']}<br>[source](../{r['source']})"
        consumers='<br>'.join(f"[{c['path']}:{c['line']}](../{c['path']}#L{c['line']}) `{c['symbol']}`" for c in r['consumers'])
        evaluation='<br>'.join([*('`'+e+'` (hosted)' for e in r['evaluators']),
            *('`'+e+'` (SDK/code)' for e in r['sdk_evaluators']),
            *('`'+e+'` (declared)' for e in r['declared_metrics'] if e not in r['evaluators']),
            *('`'+e+'` (controlled)' for e in r['regressions'])])
        datasets='<br>'.join(f"`{d['name']}`<br>`{d['id']}`; {d['items']}; {d['experiments']} / {d['scored_items'] if d['scored_items'] is not None else 'unverified'}" for d in r['datasets']) or 'None configured'
        cells=[prompt,consumers,r['use']+': '+r['scenario'],evaluation,datasets,'; '.join(r['gaps'])]
        lines.append('| '+' | '.join(c.replace('|','\\|').replace('\n',' ') for c in cells)+' |')
    if retired:
        lines.extend(['','## Retired prompt','',
            '| Prompt | Former source | Supported caller / current evaluation | Recovery / cleanup |',
            '| --- | --- | --- | --- |'])
        for name,spec in sorted(retired.items()):
            lines.append(f"| `{name}` | `{spec['source']}` | None; {spec['reason']} | [All published versions](../{spec['archive']}); exact-name cleanup after main merge/pull. |")
    lines.extend(['','## Pinned upstream instructions','',
        'These third-party instructions are also sent by the game pipeline. They are pinned by `deps/novel-to-game.lock.json`, consumed by `apps/api/novel_game.py:run_novel_game` and `experiments/novel-to-game/stages.py`, and retained outside the Memoir Langfuse prompt catalog. The game workflow dataset does not establish that every stage or this upstream revision was exercised.', '',
        '| Source | Stages | Locked SHA-256 |', '| --- | --- | --- |'])
    for item in upstream:
        lines.append(f"| [{item['source']}](../{item['source']}) | {', '.join(item['stages'])} | `{item['sha256']}` |")
    lines.extend(['', 'The experiment also supplies its code-defined `FORMAT` protocol field. The optional Higgsfield builder loads a separately installed skill package through `apps/api/higgsfield_game.py:load_skill`; availability and revision must be verified on the selected runtime before claiming its coverage.'])
    if examples:
        lines.extend(['','## Frozen example and invocation instructions','',
            'These repository sources are outside the current Langfuse catalog. They remain as historical/example material and have no active hosted evaluator or dataset. The frozen runner also embeds six stage-task strings in `STAGES`; its old external `var` skill path is not a supported current runtime. Use the maintained runner and versioned prompts for a new evaluation.', '',
            '| Source | Consumer / scenario | Evaluator / dataset | SHA-256 |',
            '| --- | --- | --- | --- |'])
        for item in examples:
            c=item['consumer']
            lines.append(f"| [{item['source']}](../{item['source']}) | {item['kind']}; [{c['path']}:{c['line']}](../{c['path']}#L{c['line']}) `{c['symbol']}` | No active hosted evaluator or dataset; frozen example only | `{item['sha256']}` |")
        lines.extend(['','[`skills/memoir-place-photo-research/examples/prompts.md`](../skills/memoir-place-photo-research/examples/prompts.md) contains user invocation/expected-behavior examples, not application model instructions. Its source labels them as examples rather than live evaluation results.'])
    return '\n'.join(lines)+'\n'


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write',action='store_true',help='Regenerate the inventory table and JSON; no network or model calls')
    parser.add_argument('--snapshot',type=Path,default=ROOT/'docs/prompt-audit-live.json')
    args=parser.parse_args(argv)
    coverage=json.loads((ROOT/'config/prompt-coverage.json').read_text())
    bindings=json.loads((ROOT/'config/langfuse-evaluation-bindings.json').read_text())
    summary=validate(coverage, bindings)
    snapshot=json.loads(args.snapshot.read_text()) if args.snapshot.exists() else None
    if snapshot is not None:validate_snapshot(snapshot,bindings)
    report=rows(coverage,bindings,snapshot)
    upstream=upstream_sources()
    examples=example_sources()
    if args.write:
        (ROOT/'docs/prompt-coverage.md').write_text(markdown(report,upstream,coverage.get('retired'),examples))
        (ROOT/'docs/prompt-coverage.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    elif json.loads((ROOT/'docs/prompt-coverage.json').read_text())!=report or (ROOT/'docs/prompt-coverage.md').read_text()!=markdown(report,upstream,coverage.get('retired'),examples):
        raise ValueError('Generated prompt inventory is stale; run make prompt-coverage')
    print(json.dumps({**summary,'upstream_sources':len(upstream),'without_active_hosted_dataset':sum(not r['datasets'] for r in report)}))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
