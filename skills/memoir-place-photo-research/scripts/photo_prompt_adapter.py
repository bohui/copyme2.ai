"""Pinned prompt requests for both the application and an installed photo skill."""
from contextlib import nullcontext
import hashlib
import json
from pathlib import Path
import re

try:
    from apps.api.prompt_artifact import load_prompt_artifact, prompt_path
    from apps.api.model_request import managed_json_request, decode_json_response, prompt_manifest
    from apps.api.llm_tracing import trace_llm_call
except ModuleNotFoundError as error:
    if error.name != 'apps' and not error.name.startswith('apps.'):
        raise

    ROOT = Path(__file__).resolve().parents[1]
    PROMPTS = {f'memoir/skills/memoir-place-photo-research/{part}': ROOT / 'prompts' / f'{part}.md'
               for part in ('discovery', 'capture-evidence')}

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

    def managed_json_request(name, payload, schema, *, model):
        instructions = load_prompt_artifact(prompt_path(name))
        manifest = prompt_manifest([name], instructions, schema)
        return dict(model=model, instructions=instructions, input=json.dumps(payload, ensure_ascii=False),
            store=False, reasoning={'effort': 'low'}, max_output_tokens=3000,
            text={'format': {'type': 'json_schema', 'name': 'memoir_proposal', 'strict': True, 'schema': schema}},
            metadata={key: manifest[key] for key in ('prompt_sha256', 'schema_sha256', 'manifest_sha256')}), manifest

    def decode_json_response(value):
        if (not isinstance(value, dict) or value.get('status') != 'completed'
                or not isinstance(value.get('id'), str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,1024}', value['id'])
                or not isinstance(value.get('output'), list)):
            raise ValueError('Model response did not complete')
        messages = [item for item in value['output'] if isinstance(item, dict) and item.get('type') == 'message']
        if not messages or any(item.get('status', 'completed') != 'completed' or not isinstance(item.get('content'), list) for item in messages):
            raise ValueError('Model response has no complete message')
        text = ''.join(part.get('text', '') for item in messages for part in item['content']
                       if isinstance(part, dict) and part.get('type') == 'output_text' and isinstance(part.get('text'), str))
        return json.loads(text)

    def trace_llm_call(*args, **kwargs):
        return nullcontext()
