"""Read a checked-in prompt and verify its Langfuse version receipt."""

import hashlib
import json
from pathlib import Path

from .prompt_catalog import PROMPT_PATHS

ROOT = Path(__file__).resolve().parents[2]


def prompt_path(name: str) -> Path:
    return ROOT / PROMPT_PATHS[name]


def load_prompt_artifact(path: Path) -> str:
    prompt = path.read_text(encoding="utf-8")
    receipt_path = path.with_name(path.name + ".langfuse.json")
    if not receipt_path.is_file():
        raise ValueError(f"Missing Langfuse prompt receipt: {path}")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if (receipt.get("schema_version") != 1
            or receipt.get("type") != "text"
            or not isinstance(receipt.get("name"), str) or not receipt["name"]
            or type(receipt.get("version")) is not int
            or receipt["version"] < 1
            or receipt.get("sha256") != hashlib.sha256(prompt.encode("utf-8")).hexdigest()):
        raise ValueError(f"Invalid Langfuse prompt artifact: {path}")
    return prompt


def validate_runtime_prompt_artifacts() -> None:
    invalid = []
    for name, relative in PROMPT_PATHS.items():
        if name.startswith('memoir/evaluation/'):
            continue  # Evaluation inputs are not shipped in runtime containers.
        path = ROOT / relative
        try:
            load_prompt_artifact(path)
            receipt = json.loads(path.with_name(path.name + '.langfuse.json').read_text())
            if receipt['name'] != name:
                raise ValueError('Prompt receipt belongs to another managed name')
        except (OSError, ValueError):
            invalid.append(name)
    if invalid:
        raise ValueError('Runtime prompts need valid Langfuse publication receipts: '
            + ', '.join(invalid) + '. Commit the prompt changes on your branch '
            'and run make prompt-sync before starting services.')


if __name__ == '__main__':
    try:
        validate_runtime_prompt_artifacts()
    except ValueError as error:
        raise SystemExit(str(error)) from None
