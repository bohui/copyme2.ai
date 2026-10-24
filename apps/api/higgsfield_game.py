"""Astra's bounded tool loop for the separate Higgsfield game skill.

This Memoir adapter exports static scenery to the existing trusted player. It
has skill-file reads and document validation, never shell or deployment tools.
"""
import asyncio
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, Field

from .model_request import instruction_manifest, manifest_metadata
from .prompt_artifact import load_prompt_artifact, prompt_path
from .story_game_selection import public_scenes, selected_scenes, validate_brief
from .story_game_runtime import GameFence, GamePublication, GameRequestBody, game_ui
from .story_game_webpage import validate_webpage


MODEL = 'gpt-6-astra'
REQUIRED_FILES = frozenset({'SKILL.md', 'references/game-flow.md',
    'references/game-design-system.md', 'references/game-stylization.md'})


class BuildArtifact(BaseModel):
    model_config = {'extra': 'forbid'}
    artifact_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')


TOOLS = [dict(type='function', name='read_skill_file', strict=True, parameters=dict(
    type='object', additionalProperties=False, required=['paths'], properties=dict(
        paths=dict(type='array', minItems=1, maxItems=8, items=dict(type='string'))))),
    dict(type='function', name='validate_game_webpage', strict=True, parameters=dict(
        type='object', additionalProperties=False, required=['html'], properties=dict(
            html=dict(type='string', minLength=100, maxLength=150000))))]


def skill_snapshot(path=None):
    """Freeze installed instructions for one build; updates affect the next one."""
    root = Path(path or os.getenv('MEMOIR_HIGGSFIELD_SKILL_PATH',
        '/opt/memoir/external-skills/higgsfield-websites')).resolve(strict=True)
    files, total = {}, 0
    for file in sorted(root.rglob('*.md')):
        if file.is_symlink() or not file.resolve().is_relative_to(root):
            raise ValueError('game_external_skill_path_invalid')
        data = file.read_bytes()
        total += len(data)
        if len(data) > 256000 or total > 2000000 or len(files) >= 128:
            raise ValueError('game_external_skill_limit')
        files[file.relative_to(root).as_posix()] = data.decode('utf-8')
    if not REQUIRED_FILES <= files.keys() or 'name: higgsfield-websites' not in files['SKILL.md']:
        raise ValueError('game_external_skill_unavailable')
    digest = hashlib.sha256(json.dumps(files, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return files, digest


async def load_build_packet(fence):
    from psycopg import AsyncConnection
    connection = await AsyncConnection.connect(os.environ['MEMOIR_PUBLICATION_DATABASE_URL'], connect_timeout=2)
    try:
        await connection.execute('set local role service_role')
        await connection.execute("set local lock_timeout='2s'")
        cursor = await connection.execute('select public.read_story_game_input(%s,%s)', (fence.game_id, fence.token))
        packet = (await cursor.fetchone())[0]
        if packet['authority'] != fence.authority or packet['phase'] != 'build' or not packet.get('brief'):
            raise ValueError('game_human_selection_required')
        return packet
    finally:
        await connection.close()


async def run_higgsfield_game(fence, *, packet_loader=None, transport=None, skill_path=None,
                              issue14_admission=None):
    from .issue14_execution_admission import check_issue14_dispatch
    from .lifetime_memory_lane_engine import check_lane_generation
    from .llm_tracing import trace_llm_call, update_llm_trace
    fence = GameFence.model_validate(fence)
    check_issue14_dispatch(issue14_admission, role='tool_loop')
    check_lane_generation()
    packet = await (packet_loader or load_build_packet)(fence)
    proposal = selected_scenes(packet)
    brief = validate_brief(packet['brief'], len(proposal['scenes']))
    files, skill_digest = skill_snapshot(skill_path)
    instructions = '\n\n'.join(load_prompt_artifact(prompt_path('memoir/skills/memoir-story-game/' + name))
        for name in ('higgsfield', 'webpage'))
    schema = BuildArtifact.model_json_schema()
    manifest = instruction_manifest(instructions, schema, variant='higgsfield-game')
    payload = dict(type='game', target='memoir-private-player', locale=packet['authority']['locale'],
        ui=game_ui(packet['authority']['locale']), brief=brief, scenes=public_scenes(proposal))
    history = [dict(role='user', content=json.dumps(payload, ensure_ascii=False))]
    base, key = os.getenv('MEMORY_SPARK_LLM_BASE_URL', '').rstrip('/'), os.getenv('MEMORY_SPARK_LLM_API_KEY', '')
    endpoint = urlsplit(base)
    if (not key or endpoint.scheme not in {'http', 'https'} or not endpoint.hostname
            or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment):
        raise ValueError('game_provider_unavailable')
    publisher = GamePublication(os.getenv('MEMOIR_PUBLICATION_DATABASE_URL'))
    read, artifacts, responses = set(), {}, []
    async with asyncio.timeout(780), httpx.AsyncClient(timeout=180, transport=transport,
            trust_env=False, follow_redirects=False) as client:
        for _ in range(12):
            check_issue14_dispatch(issue14_admission, role='tool_loop')
            check_lane_generation()
            body = dict(model=MODEL, instructions=instructions, input=history, tools=TOOLS,
                tool_choice='auto', parallel_tool_calls=True, store=False,
                reasoning={'effort': 'low'}, include=['reasoning.encrypted_content'], max_output_tokens=20000,
                metadata={**manifest_metadata(manifest), 'generation_name': 'higgsfield-websites-game',
                    'trace_name': 'memoir-story-game-build'},
                text={'format': {'type': 'json_schema', 'name': 'memoir_game_artifact', 'strict': True, 'schema': schema}})
            encoded = json.dumps(body, ensure_ascii=False).encode()
            if len(encoded) > 2000000:
                raise ValueError('game_build_context_limit')
            request = GameRequestBody(encoded, publisher=publisher, fence=fence.model_dump(mode='json'))
            try:
                with trace_llm_call('story.game.higgsfield', MODEL, metadata={
                        'prompt_manifest': manifest, 'skill_sha256': skill_digest}) as trace:
                    async with client.stream('POST', base + '/responses', content=request,
                            headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json',
                                'Content-Length': str(len(encoded))}) as response:
                        response.raise_for_status()
                        raw = bytearray()
                        async for chunk in response.aiter_bytes():
                            raw.extend(chunk)
                            if len(raw) > 700000:
                                raise ValueError('game_response_limit')
                    if key.encode() in raw:
                        raise ValueError('unsafe_game_response')
                    result = json.loads(raw)
                    if result.get('status') != 'completed' or not result.get('id') or not result.get('model'):
                        raise ValueError('incomplete_game_response')
                    responses.append(result['id'])
                    update_llm_trace(trace, metadata={'response_id': result['id'], 'skill_sha256': skill_digest})
            finally:
                await request.aclose()
            output = result.get('output', [])
            history.extend(output)
            calls = [item for item in output if item.get('type') == 'function_call']
            if calls:
                if len(calls) > 8:
                    raise ValueError('game_tool_limit')
                for call in calls:
                    arguments = json.loads(call['arguments'])
                    if call['name'] == 'read_skill_file':
                        paths = arguments.get('paths')
                        if (set(arguments) != {'paths'} or not isinstance(paths, list) or not 1 <= len(paths) <= 8
                                or any(not isinstance(p, str) or p not in files for p in paths)):
                            raise ValueError('game_skill_file_invalid')
                        read.update(paths)
                        value = {p: files[p] for p in paths}
                    elif call['name'] == 'validate_game_webpage':
                        if set(arguments) != {'html'}:
                            raise ValueError('game_artifact_invalid')
                        try:
                            html = validate_webpage(arguments['html'], payload['ui'])
                        except ValueError as error:
                            value = {'valid': False, 'error': str(error)}
                        else:
                            digest = hashlib.sha256(html.encode()).hexdigest()
                            artifacts[digest] = html
                            value = {'valid': True, 'artifact_sha256': digest}
                    else:
                        raise ValueError('game_tool_invalid')
                    history.append(dict(type='function_call_output', call_id=call['call_id'], output=json.dumps(value)))
                continue
            text = ''.join(part.get('text', '') for item in output if item.get('type') == 'message'
                for part in item.get('content', []) if part.get('type') == 'output_text')
            artifact = BuildArtifact.model_validate_json(text)
            if not REQUIRED_FILES <= read or artifact.artifact_sha256 not in artifacts:
                raise ValueError('game_skill_or_validation_required')
            return dict(webpage={'html': artifacts[artifact.artifact_sha256]}, receipt=dict(
                status='completed', response_id=responses[-1], response_ids=responses,
                model=result['model'], requested_model=MODEL, skill='higgsfield-websites',
                skill_sha256=skill_digest, skill_files=sorted(read), artifact_sha256=artifact.artifact_sha256,
                prompt_manifest=manifest))
    raise ValueError('game_build_turn_limit')
