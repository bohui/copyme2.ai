"""Pinned prompt requests for both the application and an installed photo skill."""
from contextlib import nullcontext
import hashlib
import json
from pathlib import Path

try:
    from apps.api.prompt_artifact import load_prompt_artifact, prompt_path
    from apps.api.model_request import prompt_manifest
    from apps.api.llm_tracing import trace_llm_call, gateway_trace_headers
except ModuleNotFoundError as error:
    if error.name != 'apps' and not error.name.startswith('apps.'):
        raise

    ROOT = Path(__file__).resolve().parents[1]
    PROMPTS = {'memoir/skills/memoir-place-photo-research/discovery': ROOT / 'prompts' / 'discovery.md'}

    def digest(value):
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(text.encode('utf-8')).hexdigest()

    def prompt_path(name):
        return PROMPTS[name]

    def load_prompt_artifact(path):
        text = path.read_text(encoding='utf-8')
        receipt = json.loads(path.with_name(path.name + '.langfuse.json').read_text(encoding='utf-8'))
        expected = next(name for name, source in PROMPTS.items() if source == path)
        if (receipt.get('schema_version') != 1 or receipt.get('type') != 'text'
                or receipt.get('name') != expected or type(receipt.get('version')) is not int
                or receipt['version'] < 1 or receipt.get('sha256') != digest(text)):
            raise ValueError('Invalid Langfuse prompt artifact')
        return text

    def prompt_manifest(names, instructions, schema=None, *, variant=None):
        artifacts = []
        for name in names:
            path = prompt_path(name)
            text = load_prompt_artifact(path)
            receipt = json.loads(path.with_name(path.name + '.langfuse.json').read_text(encoding='utf-8'))
            artifacts.append(dict(name=name, version=receipt['version'], sha256=digest(text), status='published'))
        manifest = dict(artifacts=artifacts, prompt_sha256=digest(instructions), schema_sha256=digest(schema), variant=variant)
        return {**manifest, 'manifest_sha256': digest(manifest)}

    def trace_llm_call(*args, **kwargs):
        return nullcontext()

    def gateway_trace_headers():
        return {}
