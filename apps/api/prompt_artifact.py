"""Read a checked-in prompt and verify its Langfuse version receipt."""

import hashlib
import json
from pathlib import Path

from .prompt_catalog import PROMPT_PATHS, PENDING_EVALUATION_PROMPTS

ROOT = Path(__file__).resolve().parents[2]


def prompt_path(name: str) -> Path:
    return ROOT / {**PROMPT_PATHS, **PENDING_EVALUATION_PROMPTS}[name]


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
