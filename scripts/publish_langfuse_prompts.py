#!/usr/bin/env python3
"""Publish changed prompts only from the current, committed origin/main tree."""

import argparse
import fcntl
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
from scripts.prompt_registry import publication_prompt_registry as prompt_registry


def git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                            text=True, timeout=30,
                            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    if result.returncode:
        raise ValueError(f"Git {args[0]} failed; no prompt publication was authorized")
    return result.stdout.strip() if args[0] != "show" else result.stdout


def main_revision(root: Path) -> str:
    if git(root, "branch", "--show-current") != "main":
        raise ValueError("Prompt publication requires main; merge the PR and pull main first")
    receipts = {path + ".langfuse.json" for path in prompt_registry(root).values()}
    changed = set(git(root, "diff", "--name-only", "-z", "HEAD").split("\0")) - {""}
    if changed - receipts:
        raise ValueError("Commit or set aside local edits before publishing merged main prompts")
    revision = git(root, "rev-parse", "HEAD")
    remote = git(root, "ls-remote", "--exit-code", "origin", "refs/heads/main").split()
    if len(remote) != 2 or remote[0] != revision:
        raise ValueError("Local main must match origin/main; pull main before publishing")
    return revision


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


def publish(client, *, root: Path, revision: str, check: bool = False) -> list[dict]:
    if main_revision(root) != revision:
        raise ValueError("Git main changed before publication; retry after pulling main")
    plan = []
    for name, target in prompt_registry(root).items():
        text = git(root, "show", f"{revision}:{target}")
        if not text.strip() or (root / target).read_text(encoding="utf-8") != text:
            raise ValueError(f"Prompt differs from committed main: {target}")
        matches = [item for item in client.api.prompts.list(name=name, limit=100).data
                   if item.name == name]
        current = None
        if matches:
            if len(matches) != 1 or not matches[0].versions:
                raise ValueError(f"Ambiguous Langfuse prompt versions for {name}")
            current = client.get_prompt(name, version=max(matches[0].versions),
                                       type="text", cache_ttl_seconds=0, max_retries=0)
            if (current.name != name or current.version != max(matches[0].versions)
                    or getattr(current, "is_fallback", False) or not isinstance(current.prompt, str)):
                raise ValueError(f"Langfuse did not return {name}")
        plan.append((name, target, text, current))

    results = []
    for name, target, text, current in plan:
        changed = current is None or current.prompt != text
        receipt_pending = False
        if git(root, "branch", "--show-current") != "main" or git(root, "rev-parse", "HEAD") != revision:
            raise ValueError("Git main changed during prompt publication; retry after pulling main")
        if (root / target).read_text(encoding="utf-8") != text:
            raise ValueError(f"Prompt changed during publication: {target}")
        if not check:
            if changed:
                current = client.create_prompt(name=name, prompt=text, type="text",
                    config=current.config if current else {},
                    commit_message=f"Publish merged main {revision}")
            receipt = sync_prompt(client, target=target, name=name, version=current.version,
                                  root=root, expected_content=text)
            sync_prompt(client, target=target, name=name, version=current.version,
                        root=root, check=True)
        else:
            receipt = {"name": name, "target": target,
                       "version": current.version if current else None}
            if not changed:
                try:
                    receipt = sync_prompt(client, target=target, name=name, version=current.version,
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
            revision = main_revision(root)
            client = prompt_client(args.credential_file)
            results = publish(client, root=root, revision=revision, check=args.check)
        print(json.dumps({"mode": "check" if args.check else "sync", "main_commit": revision,
                          "artifacts": len(results),
                          "published": sum(row["published"] for row in results),
                          "changed": [row["name"] for row in results if row["content_changed"]],
                          "receipt_updates_needed": [row["name"] for row in results if row["receipt_pending"]]}))
        if not args.check:
            print("Prompt receipts are synchronized. Review and commit receipt updates; make prompt-check verifies them.")
        return int(args.check and any(row["content_changed"] or row["receipt_pending"] for row in results))
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
