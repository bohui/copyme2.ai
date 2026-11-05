"""Managed model requests and redacted, complete instruction provenance."""
import hashlib
import json
import os
import re
from urllib.parse import urlsplit

from .prompt_artifact import ROOT, load_prompt_artifact, prompt_path
from .prompt_catalog import PROMPT_PATHS, LOCAL_PROMPT_NAMES
from .prompt_composition import component_paths, render_prompt_artifact
from .llm_tracing import trace_llm_call, update_llm_trace, gateway_trace_headers, gateway_metadata
from .model_configuration import background_model, background_effort


def digest(value):
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def prompt_manifest(names, instructions, schema=None, *, variant=None):
    """Versions identify static instructions; private input is never recorded."""
    paths = []
    for name in names:
        path = prompt_path(name)
        if path not in paths:
            paths.append(path)
        for component in component_paths(load_prompt_artifact(path)):
            source = load_prompt_artifact(component)
            if component not in paths and (source in instructions or render_prompt_artifact(component) in instructions):
                paths.append(component)
    artifacts = []
    for path in paths:
        text = load_prompt_artifact(path)
        receipt_path = path.with_name(path.name + '.langfuse.json')
        receipt = json.loads(receipt_path.read_text()) if receipt_path.is_file() else {}
        from .prompt_composition import expanded_prompt
        published = receipt.get('sha256') == digest(expanded_prompt(path)) and type(receipt.get('version')) is int
        local = receipt.get('storage') == 'local' and receipt.get('sha256') == digest(text)
        artifacts.append(dict(name=receipt.get('name') if published or local else next(
            (name for name, relative in PROMPT_PATHS.items()
             if ROOT / relative == path), path.relative_to(ROOT).as_posix()),
            version=receipt.get('version') if published else None, sha256=receipt.get('sha256') if published else digest(text),
            status='published' if published else 'local' if local else 'unpublished'))
    result = dict(artifacts=artifacts, prompt_sha256=digest(instructions), schema_sha256=digest(schema), variant=variant)
    return {**result, 'manifest_sha256': digest(result)}


def managed_json_request(name, payload, schema, *, model=None, effort=None):
    instructions = render_prompt_artifact(prompt_path(name))
    body = dict(model=model or background_model(), instructions=instructions,
                input=json.dumps(payload, ensure_ascii=False), store=False,
                reasoning={'effort': effort or background_effort()}, max_output_tokens=3000,
                text={'format': {'type': 'json_schema', 'name': 'memoir_proposal', 'strict': True, 'schema': schema}})
    manifest=prompt_manifest([name],instructions,schema)
    body['metadata']=manifest_metadata(manifest)
    return body,manifest


def completed_response_text(value):
    if (not isinstance(value, dict) or value.get('status') != 'completed'
            or not isinstance(value.get('id'), str) or len(value['id']) > 1024
            or not re.fullmatch(r'[A-Za-z0-9_-]+={0,2}', value['id'])
            or not isinstance(value.get('output'),list)):
        raise ValueError('Model response did not complete')
    messages = [item for item in value['output'] if isinstance(item,dict) and item.get('type') == 'message']
    if not messages or any(item.get('status', 'completed') != 'completed' or not isinstance(item.get('content'),list) for item in messages):
        raise ValueError('Model response has no complete message')
    return ''.join(part.get('text', '') for item in messages for part in item['content']
                   if isinstance(part,dict) and part.get('type') == 'output_text' and isinstance(part.get('text'),str))


def decode_json_response(value):
    return json.loads(completed_response_text(value))


async def complete_json(name, payload, schema, *, model=None, effort=None, transport=None, body_factory=None,
                        base_url=None, api_key=None, trace_name=None, generation_name=None, diagnostic_request_id=None):
    import httpx
    body, manifest = managed_json_request(name, payload, schema, model=model, effort=effort)
    if trace_name is None and name.startswith(('memoir/evaluators/', 'memoir/probes/')):
        trace_name = 'evaluation/memoir-judges'
        generation_name = generation_name or trace_name + '.' + name.removeprefix('memoir/').replace('/', '.')
    call_name = generation_name or trace_name or name
    body['metadata'] = {**body.get('metadata', {}), **gateway_metadata(call_name, trace_name=trace_name)}
    if diagnostic_request_id is not None:
        from .diagnostics import new_request_id
        body['metadata']['request_id'] = new_request_id(diagnostic_request_id)
    base = (os.getenv('MEMORY_SPARK_LLM_BASE_URL', '') if base_url is None else base_url).rstrip('/')
    key = os.getenv('MEMORY_SPARK_LLM_API_KEY', '') if api_key is None else api_key
    endpoint=urlsplit(base)
    if (not key or not body['model'] or endpoint.scheme not in {'http','https'} or not endpoint.hostname
            or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment):
        raise ValueError('Model provider is not configured')
    encoded = json.dumps(body, ensure_ascii=False).encode('utf-8')
    if len(encoded)>65536:
        raise ValueError('Structured model request exceeds its byte budget')
    content = body_factory(encoded) if body_factory else encoded
    try:
        trace_metadata = {'prompt_manifest': manifest}
        if trace_name:
            trace_metadata.update(gateway_metadata(call_name, trace_name=trace_name))
        if diagnostic_request_id is not None:
            trace_metadata['request_id'] = body['metadata']['request_id']
        with trace_llm_call(call_name, body['model'], trace_name=trace_name,
                            input_summary={'kind': 'structured_input'},
                            metadata=trace_metadata, gateway=True) as trace:
            async with httpx.AsyncClient(transport=transport, timeout=60, trust_env=False, follow_redirects=False) as client:
                async with client.stream('POST', base + '/responses', content=content,
                    headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json',
                             'Content-Length': str(len(encoded)), **gateway_trace_headers()}) as response:
                    response.raise_for_status()
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        raw.extend(chunk)
                        if len(raw) > 256000:
                            raise ValueError('Model response exceeds the request limit')
            if key.encode() in raw:
                raise ValueError('Unsafe provider response')
            value = json.loads(raw)
            output = decode_json_response(value)
            update_llm_trace(trace, metadata={'response_id': value['id']})
            return output, {'response_id': value['id'], 'model': body['model'], 'prompt_manifest': manifest}
    finally:
        if body_factory:
            await content.aclose()


def instruction_manifest(instructions, schema=None, *, variant=None, extra_names=(), primary_name=None):
    """Identify exact managed components in a compiled static instruction block.

    This inventory never rewrites prose or examines request testimony. Assembly
    still resolves named artifacts; rendered templates and their shared sources
    retain published-template identities and local source hashes in the manifest.
    """
    names = ([primary_name] if primary_name else []) + list(extra_names)
    for name, relative in PROMPT_PATHS.items():
        path = ROOT / relative
        # Evaluation-only sources are catalogued for offline tooling but are
        # not shipped in the runtime worker image.
        if not path.is_file():
            continue
        template = path.read_text(encoding='utf-8')
        if template and (template in instructions or
                '{{prompt:' in template and render_prompt_artifact(path) in instructions):
            names.append(name)
    if primary_name is None and 'memoir/skills/author-timeline/instructions' in names:
        primary_name = 'memoir/skills/author-timeline/extract'
        names.insert(0, primary_name)
    if primary_name is not None:
        names = [name for name in names if name == primary_name or name in LOCAL_PROMPT_NAMES]
    if not names:
        raise ValueError('No managed instruction source in model request')
    return prompt_manifest(names, instructions, schema, variant=variant)


def manifest_metadata(manifest):
    metadata = {key: manifest[key] for key in ('prompt_sha256', 'schema_sha256', 'manifest_sha256')}
    published = [item for item in manifest.get('artifacts', []) if item.get('status') == 'published']
    if len(published) == 1:
        primary = published[0]
        if isinstance(primary.get('name'), str) and primary['name'] and type(primary.get('version')) is int and primary['version'] > 0:
            metadata.update(langfuse_prompt_name=primary['name'], langfuse_prompt_version=str(primary['version']))
    return metadata
