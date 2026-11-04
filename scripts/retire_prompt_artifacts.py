"""Retire only archived, unregistered prompts after their removal reaches main."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))

from scripts.prompt_registry import prompt_registry
from scripts.langfuse_prompt_client import prompt_client
from scripts.publish_langfuse_prompts import git, publication_source


def retire(client, *, root=ROOT, execute=False):
    manifest=root/'config/prompt-coverage.json'
    if not manifest.exists():return []
    branch,revision=publication_source(root)
    if execute and branch!='main':
        raise ValueError('Remote prompt retirement waits for the source removal to reach origin/main')
    expected=json.loads((root/'config/langfuse-evaluation-bindings.json').read_text())['project_id']
    projects=client.api.projects.get().data
    if len(projects)!=1 or projects[0].id!=expected:
        raise ValueError('Prompt retirement credentials belong to another project')
    coverage=json.loads(manifest.read_text())
    active=prompt_registry(root,include_unpublished=True)
    plan=[]
    # Finish every archive/version check before the first deletion.
    for name,spec in coverage.get('retired',{}).items():
        if name in active or (root/spec['source']).exists():
            raise ValueError('Retired prompt still has an active source: '+name)
        archive_path=root/spec['archive']
        if git(root,'show',f'{revision}:{spec["archive"]}')!=archive_path.read_text():
            raise ValueError('Commit the recovery archive before retiring '+name)
        records=[r for r in json.loads(archive_path.read_text()) if r['name']==name]
        if len(records)!=1:raise ValueError('Missing unique recovery archive: '+name)
        saved_versions=records[0]['published_versions']
        versions={v['version']:v for v in saved_versions}
        if not versions or len(versions)!=len(saved_versions):
            raise ValueError('Empty or duplicate recovery versions: '+name)
        matches=[p for p in client.api.prompts.list(name=name,limit=100).data if p.name==name]
        if len(matches)>1:raise ValueError('Ambiguous remote prompt: '+name)
        if matches:
            if set(matches[0].versions)!=set(versions):
                raise ValueError('Remote prompt versions changed; archive again before retiring '+name)
            for number,saved in versions.items():
                current=client.api.prompts.get(name,version=number)
                if (getattr(current,'is_fallback',False) or current.name!=name or current.version!=number
                        or current.prompt!=saved['prompt']
                        or current.config!=saved.get('config',{})
                        or set(current.labels)!=set(saved.get('labels',[]))
                        or set(current.tags)!=set(saved.get('tags',[]))
                        or hashlib.sha256(current.prompt.encode()).hexdigest()!=saved['sha256']):
                    raise ValueError('Recovery archive differs from remote prompt: '+name)
        plan.append(dict(name=name,versions=sorted(versions),present=bool(matches),deleted=False))
    for row in plan:
        if not execute or not row['present']:continue
        if publication_source(root)!=(branch,revision):
            raise ValueError('Prompt retirement source changed')
        try:
            client.api.prompts.delete(row['name'])
        except Exception:
            # A transport error may follow a successful write; inspect before any retry.
            if any(p.name==row['name'] for p in client.api.prompts.list(name=row['name'],limit=100).data):
                raise
        if any(p.name==row['name'] for p in client.api.prompts.list(name=row['name'],limit=100).data):
            raise ValueError('Prompt retirement was not verified: '+row['name'])
        row['deleted']=True
    return plan


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--credential-file',type=Path,default=Path.home()/'llm_provider/.env')
    parser.add_argument('--execute',action='store_true')
    args=parser.parse_args(argv)
    client=prompt_client(args.credential_file)
    try:print(json.dumps(retire(client,execute=args.execute)))
    finally:client.shutdown()


if __name__=='__main__':
    try:main()
    except ValueError as error:
        raise SystemExit(str(error)) from None
    except Exception as error:
        raise SystemExit('Prompt retirement stopped: '+type(error).__name__) from None
