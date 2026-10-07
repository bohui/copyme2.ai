#!/usr/bin/env python3
"""Check the reviewed mobile OpenAPI subset; regenerate only with --write.

Only schema construction runs: no ASGI lifespan, storage, workers, HTTP requests,
provider execution, migrations or live service settings are needed. Existing
legacy route handlers remain untouched; canonical names are snapshot aliases.
Loose existing response schemas and NDJSON still need the paired Zod fixtures.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import difflib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DEFAULT_SNAPSHOT = ROOT / 'packages/contracts/openapi.snapshot.json'
CANONICAL_BASE = '/api/v1/memoir'

# Explicit allowlist: unrelated legacy/demo, checkout, print and internal worker
# endpoints must not silently become part of the native delivery contract.
MOBILE_OPERATIONS = {
    '/v1/agent/config': ('get',),
    '/v1/agent/profile': ('get', 'patch'),
    '/v1/agent/greeting': ('post',),
    '/v1/agent/turn': ('post',),
    '/v1/agent/turns/{client_turn_id}': ('get',),
    '/v1/agent/place-journey': ('get',),
    '/v1/agent/places/{project_id}/photos': ('get',),
    '/v1/agent/family-context': ('get',),
    '/v1/agent/family-context/{project_id}/people/{person_id}/photo': ('put', 'delete'),
    '/v1/agent/collection/{project_id}': ('get', 'put'),
    '/v1/agent/collection/{project_id}/organise': ('post',),
    '/v1/agent/collection/{project_id}/tasks': ('post',),
    '/v1/agent/tasks/{task_id}': ('get',),
    '/v1/user/profile': ('get', 'put'),
    '/v1/user/conversations': ('get',),
    '/v1/user/projects': ('get',),
    '/v1/user/projects/{project_id}/history': ('get',),
    '/v1/user/projects/{project_id}/sources/{source_id}': ('get',),
    '/v1/user/conversation-transfer': ('post',),
    '/v1/user/conversation-transfer/attach': ('post',),
    '/v1/user/attachments': ('post',),
    '/v1/story/plans': ('get',),
    '/v1/story/state': ('get',),
    '/v1/story/readiness': ('get',),
    '/v1/story/private-draft': ('get',),
    '/v1/story/private-draft/retry': ('post',),
    '/v1/story/events': ('get',),
    '/v1/story/events/{project_id}/{event_id}': ('patch',),
    '/v1/story/transcriptions': ('post',),
    '/v1/story/question-audio': ('post',),
    '/v1/story/preview': ('post',),
    '/v1/story/preview/{job_id}': ('get',),
}


def load_openapi():
    """Use the production routers without constructing production services."""
    from fastapi import FastAPI
    from apps.api.agent_routes import router as agent_router
    from apps.api.collection_routes import router as collection_router
    from apps.api.supabase_routes import router as user_router
    from apps.api.story_routes import build_router

    def schema_only(*args, **kwargs):
        raise AssertionError('OpenAPI generation cannot execute a service')

    app = FastAPI()
    app.include_router(agent_router)
    app.include_router(collection_router)
    app.include_router(user_router)
    # These dependencies are never accessed by app.openapi(). The router's
    # lifespan is not entered, so configured background workers cannot start.
    app.include_router(build_router(schema_only, entitlement_store=object(),
                                   stripe_client=object(), speech_service=object()))
    return app.openapi()


_DOCUMENTATION = {'title', 'description', 'summary', 'operationId', 'tags',
                  'examples', 'example', 'externalDocs'}
_NAME_MAPS = {'properties', 'schemas', '$defs', 'definitions'}


def normalize(value, parent_key=None):
    if isinstance(value, dict):
        return {key: normalize(child, key) for key, child in sorted(value.items())
                if parent_key in _NAME_MAPS or key not in _DOCUMENTATION}
    if isinstance(value, list):
        values = [normalize(child) for child in value]
        if parent_key in {'required', 'enum'}:
            values.sort(key=lambda child: json.dumps(child, sort_keys=True))
        if parent_key == 'parameters':
            values.sort(key=lambda child: (child.get('in', ''), child.get('name', ''), child.get('$ref', '')))
        return values
    return value


def references(value):
    if isinstance(value, dict):
        if '$ref' in value:
            yield value['$ref']
        for child in value.values():
            yield from references(child)
    elif isinstance(value, list):
        for child in value:
            yield from references(child)


def build_snapshot(schema=None, *, operations=None):
    schema = load_openapi() if schema is None else schema
    operations = MOBILE_OPERATIONS if operations is None else operations
    selected = {}
    for path, methods in sorted(operations.items()):
        source = schema.get('paths', {}).get(path, {})
        missing = [method.upper() for method in methods if method not in source]
        if missing:
            raise ValueError(f'Missing mobile operation: {", ".join(missing)} {path}')
        if not path.startswith('/v1/'):
            raise ValueError(f'Unexpected mobile path: {path}')
        selected[CANONICAL_BASE + path[len('/v1'):]] = {
            key: deepcopy(value) for key, value in source.items()
            if key in methods or key in {'parameters', '$ref'}
        }
    selected = normalize(selected)
    components = {}
    pending = list(references(selected))
    seen = set()
    while pending:
        ref = pending.pop()
        if ref in seen:
            continue
        seen.add(ref)
        parts = ref.split('/')
        if len(parts) != 4 or parts[:2] != ['#', 'components']:
            raise ValueError(f'Unresolved OpenAPI reference: {ref}')
        section, name = parts[2:]
        try:
            definition = normalize(deepcopy(schema['components'][section][name]))
        except KeyError:
            raise ValueError(f'Unresolved OpenAPI reference: {ref}') from None
        components.setdefault(section, {})[name] = definition
        pending.extend(references(definition))
    return normalize({'snapshot_version': 1, 'openapi': schema['openapi'],
                      'canonical_base': CANONICAL_BASE,
                      'paths': selected, 'components': components})


def formatted(snapshot):
    return json.dumps(snapshot, ensure_ascii=False, sort_keys=True, indent=2) + '\n'


def snapshot_diff(expected, actual):
    return ''.join(difflib.unified_diff(formatted(expected).splitlines(keepends=True),
        formatted(actual).splitlines(keepends=True), fromfile='reviewed-openapi', tofile='current-openapi'))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument('--write', action='store_true', help='Explicitly regenerate the reviewed subset')
    args = parser.parse_args(argv)
    try:
        actual = build_snapshot()
        if args.write:
            args.snapshot.parent.mkdir(parents=True, exist_ok=True)
            args.snapshot.write_text(formatted(actual), encoding='utf-8')
            print(f'Wrote mobile OpenAPI snapshot: {args.snapshot}')
            return 0
        if not args.snapshot.is_file():
            print('Mobile OpenAPI snapshot missing; review the API and regenerate with --write')
            return 1
        expected = json.loads(args.snapshot.read_text(encoding='utf-8'))
        diff = snapshot_diff(expected, actual)
        if diff:
            print('Mobile OpenAPI contract drift detected; review runtime DTOs and regenerate explicitly')
            print(diff, end='')
            return 1
    except (OSError, ValueError) as error:
        print(f'Mobile OpenAPI check failed: {error}', file=sys.stderr)
        return 2
    count = sum(len(methods) for methods in MOBILE_OPERATIONS.values())
    print(f'Mobile OpenAPI snapshot matches ({count} operations)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
