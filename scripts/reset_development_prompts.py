"""Apply the explicitly archived development prompt reset on merged main content."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
from urllib.parse import quote
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.api.prompt_composition import expanded_prompt
from scripts.langfuse_prompt_client import prompt_client
from scripts.prompt_registry import ROOT, prompt_registry
from scripts.publish_langfuse_prompts import git, publication_source

MANIFEST = 'config/development-prompt-reset.json'


def digest(content):
    return hashlib.sha256(content.encode('utf-8')).hexdigest()


def project(client, root):
    expected = json.loads((root / 'config/langfuse-evaluation-bindings.json').read_text())['project_id']
    projects = client.api.projects.get().data
    if len(projects) != 1 or projects[0].id != expected:
        raise ValueError('Development prompt reset credentials belong to another project')
    return expected


def metadata(client, name):
    matches = [p for p in client.api.prompts.list(name=name, limit=100).data if p.name == name]
    if len(matches) > 1:
        raise ValueError('Ambiguous remote prompt: ' + name)
    return matches[0] if matches else None


def archive(client, *, root=ROOT):
    expected = project(client, root)
    registry = prompt_registry(root, include_unpublished=True)
    scope = sorted(n for n in registry if n.startswith('memoir/skills/'))
    # Capture the previously committed source identity before changing any receipts.
    old = {}
    exec(git(root, 'show', 'HEAD:apps/api/prompt_catalog.py'), old)
    def capture(name):
        item = metadata(client, name)
        if item is None:
            return None
        versions = []
        for version in item.versions:
            raw = client.api.prompts.get(quote(name, safe=''), version=version)
            record = raw.model_dump(mode='json')
            record['sha256'] = digest(raw.prompt)
            versions.append(record)
        source = old['PROMPT_PATHS'].get(name)
        return dict(name=name, source=source,
            content=git(root, 'show', 'HEAD:' + source) if source else None,
            receipt=json.loads(git(root, 'show', 'HEAD:' + source + '.langfuse.json')) if source else None,
            published_versions=sorted(versions, key=lambda v: v['version']))
    with ThreadPoolExecutor(max_workers=6) as pool:
        records = [r for r in pool.map(capture, scope) if r]
    target = 'docs/prompt-history/development-20261105.json'
    path = root / target
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(records, ensure_ascii=False, indent=2) + '\n'
    path.write_text(content)
    manifest = dict(schema_version=1, project_id=expected, archive=target, archive_sha256=digest(content),
        reason='User requested one assembled prompt per operation and a current version 1 development baseline.',
        remove=[], reset=[r['name'] for r in records])
    (root / MANIFEST).write_text(json.dumps(manifest, indent=2) + '\n')
    return dict(prompts=len(records), versions=sum(len(r['published_versions']) for r in records),
                removed_components=len(manifest['remove']), reset_operations=len(manifest['reset']))


def configuration(name, root):
    path = root / MANIFEST
    if not path.is_file():
        return {}
    manifest = json.loads(path.read_text())
    if name not in manifest['reset']:
        return {}
    records = json.loads((root / manifest['archive']).read_text())
    saved = next(r for r in records if r['name'] == name)['published_versions'][-1]
    return {**saved.get('config', {}), 'development_baseline': manifest['archive_sha256']}


def reset(client, *, root=ROOT, execute=False):
    if not (root / MANIFEST).is_file():
        return []
    branch, revision = publication_source(root)
    manifest = json.loads((root / MANIFEST).read_text())
    if project(client, root) != manifest['project_id']:
        raise ValueError('Development reset project differs from its archive')
    source = (root / manifest['archive']).read_text()
    if digest(source) != manifest['archive_sha256']:
        raise ValueError('Development prompt recovery archive changed')
    records = {r['name']: r for r in json.loads(source)}
    registry = prompt_registry(root, include_unpublished=True)
    plan = []
    # Validate the entire scoped archive before the first remote deletion.
    for name in [*manifest['remove'], *manifest['reset']]:
        removed_source = name in manifest['remove']
        if name not in records or (name not in registry) != removed_source:
            raise ValueError('Development reset does not match the source catalog: ' + name)
        item = metadata(client, name)
        if item is None:
            continue
        if removed_source:
            raise ValueError('Archived component unexpectedly still exists in Langfuse: ' + name)
        current = [client.api.prompts.get(quote(name, safe=''), version=v) for v in item.versions]
        if name in manifest['reset'] and item.versions == [1] and (
                current[0].config.get('development_baseline') == manifest['archive_sha256']):
            # Ordinary later publications keep their own immutable history.
            continue
        saved = {v['version']: v for v in records[name]['published_versions']}
        if set(item.versions) != set(saved):
            # A successful baseline may have subsequently advanced normally.
            if name in manifest['reset'] and all(v.config.get('development_baseline') == manifest['archive_sha256'] for v in current):
                continue
            raise ValueError('Remote prompt history changed; archive again before resetting: ' + name)
        for prompt in current:
            old = saved[prompt.version]
            if (prompt.name != name or prompt.prompt != old['prompt'] or prompt.config != old.get('config', {})
                    or set(prompt.labels) != set(old.get('labels', []))
                    or set(prompt.tags) != set(old.get('tags', []))
                    or digest(prompt.prompt) != old['sha256']):
                raise ValueError('Remote prompt differs from its recovery archive: ' + name)
        plan.append(dict(name=name, deleted=False))
    if execute and plan:
        remote = git(root, 'ls-remote', '--exit-code', 'origin', 'refs/heads/main').split()
        if not remote or remote[0] != revision:
            raise ValueError('Development prompt reset waits for this exact commit on origin/main')
        for target in (MANIFEST, manifest['archive']):
            if git(root, 'show', revision + ':' + target) != (root / target).read_text():
                raise ValueError('Commit the development prompt recovery archive first')
    for row in plan:
        if not execute:
            continue
        if publication_source(root) != (branch, revision):
            raise ValueError('Development reset source changed during deletion')
        try:
            client.api.prompts.delete(quote(row['name'], safe=''), request_options={'max_retries': 0})
        except Exception:
            if metadata(client, row['name']) is not None:
                raise
        if metadata(client, row['name']) is not None:
            raise ValueError('Development prompt deletion was not verified: ' + row['name'])
        row['deleted'] = True
    return plan


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', action='store_true', help='Save the scoped source and every remote version; no deletion')
    parser.add_argument('--credential-file', type=Path, default=Path.home() / 'llm_provider/.env')
    args = parser.parse_args()
    client = prompt_client(args.credential_file)
    try:
        print(json.dumps(archive(client) if args.archive else reset(client)))
    finally:
        client.shutdown()
