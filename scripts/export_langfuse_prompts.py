#!/usr/bin/env python3
"""Export current Langfuse prompt versions to checked-in Memoir artifacts."""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.export_langfuse_prompt import sync_prompt
from scripts.langfuse_prompt_client import prompt_client
from scripts.prompt_registry import prompt_registry
from apps.api.prompt_artifact import load_prompt_artifact

BROWSER_MODULE = "apps/web/client/memoir/browser-prompts.generated.mjs"
BROWSER_EXPORTS = {
    "PROFILE_INTAKE_PROMPT": "browser-profile-intake.md",
    "FOLLOW_UP_PROMPT": "browser-follow-up.md",
    "MEMORY_FOLLOW_UP_PROMPT": "browser-memory-follow-up.md",
    "MEDIA_CONTEXT_PROMPT": "browser-media-context.md",
    "BROWSER_MESSAGE_PROMPT": "browser-message.md",
}


def browser_module(root: Path) -> str:
    lines = ["// Generated from pinned Langfuse prompt artifacts. Run make prompt-export."]
    for symbol, filename in BROWSER_EXPORTS.items():
        source = root / "apps/api/prompts" / filename
        lines.append(f"export const {symbol} = {json.dumps(load_prompt_artifact(source), ensure_ascii=False)};")
    return "\n".join(lines) + "\n"


def selected_prompts(name: str | None, registry: dict[str, str]) -> dict[str, str]:
    if not name:
        return registry
    full_name = name if name in registry else next(
        (registered for registered, path in registry.items()
         if Path(path).stem == name), "")
    if full_name not in registry:
        raise ValueError(f"Unknown managed prompt: {name}")
    return {full_name: registry[full_name]}


def export_prompts(client, *, name: str | None = None, check: bool = False,
                   root: Path = ROOT) -> list[dict]:
    selected = selected_prompts(name, prompt_registry(root))
    receipts = []
    for prompt_name, target in selected.items():
        path = root / target
        if check:
            receipt_path = path.with_name(path.name + ".langfuse.json")
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            if receipt.get("name") != prompt_name:
                raise ValueError(f"Wrong Langfuse prompt name in {target}")
            version = receipt.get("version")
        else:
            matches = [item for item in client.api.prompts.list(name=prompt_name, limit=100).data
                       if item.name == prompt_name]
            if len(matches) != 1 or not matches[0].versions:
                raise ValueError(f"No current Langfuse version for {prompt_name}")
            current = client.get_prompt(prompt_name, version=max(matches[0].versions),
                                        type="text", cache_ttl_seconds=0, max_retries=0)
            if getattr(current, "is_fallback", False) or current.name != prompt_name:
                raise ValueError(f"Langfuse did not return {prompt_name}")
            version = current.version
        receipts.append(sync_prompt(client, target=target, name=prompt_name,
                                    version=version, root=root, check=check))
    if not name or any(Path(target).name in BROWSER_EXPORTS.values() for target in selected.values()):
        generated = browser_module(root)
        destination = root / BROWSER_MODULE
        if check:
            if not destination.is_file() or destination.read_text(encoding="utf-8") != generated:
                raise ValueError("Browser prompt module differs from pinned artifacts")
        else:
            destination.write_text(generated, encoding="utf-8")
    return receipts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credential-file", type=Path, required=True)
    parser.add_argument("--name", help="One registry name or short name; default: all prompts")
    parser.add_argument("--check", action="store_true", help="Verify pinned files against exact remote versions")
    args = parser.parse_args()
    client = prompt_client(args.credential_file)
    receipts = export_prompts(client, name=args.name, check=args.check)
    print(json.dumps({"mode": "check" if args.check else "export",
                      "artifacts": len(receipts),
                      "versions": {r["name"]: r["version"] for r in receipts}}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
