#!/usr/bin/env python3
"""Publish changed prompts from the current committed branch."""

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.export_langfuse_prompt import sync_prompt
from scripts.langfuse_prompt_client import prompt_client
from scripts.prompt_registry import prompt_registry
from apps.api.prompt_composition import expanded_prompt


def git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                            text=True, timeout=30,
                            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    if result.returncode:
        raise ValueError(f"Git {args[0]} failed; no prompt publication was authorized")
    return result.stdout.strip() if args[0] != "show" else result.stdout


def publication_source(root: Path) -> tuple[str, str]:
    branch = git(root, "branch", "--show-current")
    if not branch:
        raise ValueError("Prompt publication requires a branch; check out the branch to publish")
    receipts = {path + ".langfuse.json" for path in prompt_registry(root, include_unpublished=True).values()}
    changed = set(git(root, "diff", "--name-only", "-z", "HEAD").split("\0")) - {""}
    if changed - receipts:
        raise ValueError("Commit or set aside local edits before publishing prompts")
    revision = git(root, "rev-parse", "HEAD")
    if branch == "main":
        remote = git(root, "ls-remote", "--exit-code", "origin", "refs/heads/main").split()
        if len(remote) != 2 or remote[0] != revision:
            raise ValueError("Local main must match origin/main; pull main before publishing")
    return branch, revision


def install_hook(root: Path) -> None:
    configured = subprocess.run(["git", "-C", str(root), "config", "--get", "core.hooksPath"],
                                capture_output=True, text=True, timeout=10)
    if configured.returncode not in {0, 1}:
        raise ValueError("Could not inspect the Git hooks configuration")
    if configured.stdout.strip() == ".githooks":
        return
    if configured.stdout.strip():
        raise ValueError("An existing Git hooksPath is configured; keep it and chain .githooks/post-merge")
    hooks = Path(git(root, "rev-parse", "--git-path", "hooks"))
    if not hooks.is_absolute():
        hooks = root / hooks
    if hooks.exists() and any(path.is_file() and not path.name.endswith(".sample")
                              for path in hooks.iterdir()):
        raise ValueError("Existing Git hooks must be preserved; chain .githooks/post-merge instead")
    if not os.access(root / ".githooks/post-merge", os.X_OK):
        raise ValueError("The tracked .githooks/post-merge hook must be executable")
    git(root, "config", "--local", "core.hooksPath", ".githooks")


def publish(client, *, root: Path, branch: str, revision: str, check: bool = False,
            names: list[str] | None = None) -> list[dict]:
    if publication_source(root) != (branch, revision):
        raise ValueError("Git branch or commit changed before publication; retry prompt sync")
    registry = prompt_registry(root, include_unpublished=True)
    if names and set(names) - registry.keys():
        raise ValueError('Unknown managed prompt name; use its full Langfuse name')
    plan = []
    for name, target in registry.items():
        if names and name not in names:
            continue
        text = git(root, "show", f"{revision}:{target}")
        if not text.strip() or (root / target).read_text(encoding="utf-8") != text:
            raise ValueError(f"Prompt differs from committed branch: {target}")
        expanded_prompt(root / target, content=text)
        matches = [item for item in client.api.prompts.list(name=name, limit=100).data
                   if item.name == name]
        current = None
        if matches:
            if len(matches) != 1 or not matches[0].versions:
                raise ValueError(f"Ambiguous Langfuse prompt versions for {name}")
            versions = matches[0].versions
            latest = max(versions)
            pin_path = root / (target + '.langfuse.json')
            try:
                pin = json.loads(pin_path.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                pin = {}
            pinned = pin.get('version') if isinstance(pin, dict) else None
            # A branch may have published a newer draft. Preserve this checkout's
            # immutable version when its verified text still matches exactly.
            version = (pinned if type(pinned) is int and pinned in versions
                       and pin.get('name') == name
                       and pin.get('sha256') == hashlib.sha256(text.encode('utf-8')).hexdigest()
                       else latest)
            def read_version(number):
                prompt = client.get_prompt(name, version=number, type="text",
                                           cache_ttl_seconds=0, max_retries=0)
                if (prompt.name != name or prompt.version != number
                        or getattr(prompt, "is_fallback", False) or not isinstance(prompt.prompt, str)):
                    raise ValueError(f"Langfuse did not return {name}")
                return prompt
            current = read_version(version)
            if current.prompt != text and version != latest:
                current = read_version(latest)
        plan.append((name, target, text, current))

    results = []
    for name, target, text, current in plan:
        changed = current is None or current.prompt != text
        receipt_pending = False
        if git(root, "branch", "--show-current") != branch or git(root, "rev-parse", "HEAD") != revision:
            raise ValueError("Git branch or commit changed during prompt publication; retry prompt sync")
        if (root / target).read_text(encoding="utf-8") != text:
            raise ValueError(f"Prompt changed during publication: {target}")
        if not check:
            if changed:
                from scripts.reset_development_prompts import configuration
                current = client.create_prompt(name=name, prompt=text, type="text",
                    config=current.config if current else configuration(name, root),
                    commit_message=f"Publish {branch} {revision}")
            receipt = sync_prompt(client, target=target, name=name, version=current.version if current else None,
                                  root=root, expected_content=text)
            sync_prompt(client, target=target, name=name, version=current.version if current else None,
                        root=root, check=True)
        else:
            receipt = {"name": name, "target": target,
                       "version": current.version if current else None}
            if not changed:
                try:
                    receipt = sync_prompt(client, target=target, name=name, version=current.version if current else None,
                                          root=root, check=True, expected_content=text)
                except ValueError:
                    receipt_pending = True
        results.append({**receipt, "published": changed and not check,
                        "content_changed": changed, "receipt_pending": receipt_pending})
    return results


def main(argv=None, *, root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credential-file", type=Path,
        default=Path(os.environ.get("PROMPT_CREDENTIAL_FILE", str(Path.home() / "llm_provider/.env"))))
    parser.add_argument("--check", action="store_true", help="Report changes without publishing or writing receipts")
    parser.add_argument("--name", action="append", help="Sync one full prompt name; repeat to select several")
    parser.add_argument("--after-pull", action="store_true", help="Git hook: quietly skip branches other than main")
    parser.add_argument("--install-hook", action="store_true", help="Enable the tracked post-merge hook in this clone")
    args = parser.parse_args(argv)
    client = None
    try:
        if args.install_hook:
            install_hook(root)
            print("Automatic prompt sync enabled after main pulls in this clone.")
            return 0
        if args.after_pull and git(root, "branch", "--show-current") != "main":
            return 0
        lock = Path(git(root, "rev-parse", "--git-path", "prompt-sync.lock"))
        if not lock.is_absolute():
            lock = root / lock
        with lock.open("a") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            branch, revision = publication_source(root)
            client = prompt_client(args.credential_file)
            from scripts.reset_development_prompts import reset
            resets = reset(client, root=root)
            if resets and args.name:
                raise ValueError('The pending development reset requires a full make prompt-sync')
            if not args.check:
                reset(client, root=root, execute=True)
            results = publish(client, root=root, branch=branch, revision=revision,
                              check=args.check, names=args.name)
            retired=[]
            if args.after_pull and not args.check:
                from scripts.retire_prompt_artifacts import retire
                retired=retire(client,root=root,execute=True)
        print(json.dumps({"mode": "check" if args.check else "sync", "git_branch": branch,
                          "git_commit": revision,
                          "artifacts": len(results),
                          "reset_pending": [row["name"] for row in resets] if args.check else [],
                          "retired": [row['name'] for row in retired if row['deleted']],
                          "published": sum(row["published"] for row in results),
                          "changed": [row["name"] for row in results if row["content_changed"]],
                          "receipt_updates_needed": [row["name"] for row in results if row["receipt_pending"]]}))
        if not args.check:
            print("Prompt receipts are synchronized. Review and commit receipt updates; make prompt-check verifies them.")
        return int(args.check and (bool(resets) or any(row["content_changed"] or row["receipt_pending"] for row in results)))
    except ValueError as error:
        print(f"Prompt sync stopped: {error}", file=sys.stderr)
        return 1
    except Exception as error:
        print(f"Prompt sync failed ({type(error).__name__}); retry with make prompt-sync after resolving it.", file=sys.stderr)
        return 1
    finally:
        if client is not None:
            client.flush()


if __name__ == "__main__":
    raise SystemExit(main())
