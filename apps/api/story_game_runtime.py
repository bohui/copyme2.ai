"""Scene pool → owner selection → brief → independently installed game skill."""
import asyncio
from contextlib import asynccontextmanager
import json
import os
from urllib.parse import urlsplit
from uuid import UUID
from pathlib import Path

import httpx
from pydantic import BaseModel, Field

from .memoir_story_game import load_story_game_skill
from .lifetime_memory_lane_engine import LaneRequestBody, _settle
from .prompt_artifact import load_prompt_artifact, prompt_path
from .story_game_webpage import validate_webpage
from .story_game_selection import (GameProposal, SceneProposal, ScenePool, GameBrief,
    validate_scenes, validate_pool, selected_scenes, public_scenes, validate_brief)


class GameWebpage(BaseModel):
    model_config = {'extra': 'forbid'}
    html: str = Field(min_length=100, max_length=150000)


def game_ui(locale):
    locale = 'zh-CN' if locale == 'zh-CN' else 'en-AU'
    path = Path(__file__).resolve().parents[1] / 'web/messages' / (locale + '.json')
    labels = json.loads(path.read_text())['Memoir']['game']
    return {key: labels[key] for key in ('title', 'framing', 'movement', 'controls',
        'left', 'right', 'interact', 'textVersion')}


class GameFence(BaseModel):
    model_config = {'extra': 'forbid'}
    game_id: UUID
    token: UUID
    authority: dict


class GamePublication:
    def __init__(self, dsn):
        if not dsn:
            raise ValueError('game_publication_unavailable')
        self.dsn = dsn

    @asynccontextmanager
    async def guard(self, fence):
        from psycopg import AsyncConnection, Error

        snapshot = GameFence.model_validate(fence)
        connection = None
        try:
            async with asyncio.timeout(5):
                connection = await AsyncConnection.connect(self.dsn, connect_timeout=2)
                await connection.execute('set local role service_role')
                await connection.execute("set local lock_timeout='2s'")
                started = asyncio.get_running_loop().time()
                cursor = await connection.execute('select authority, extract(epoch from lease_until-clock_timestamp()) '
                    'from public.lock_story_game(%s,%s,true)', (snapshot.game_id, snapshot.token))
                authority, remaining = await cursor.fetchone()
                if authority != snapshot.authority:
                    raise ValueError('game_authority_changed')
                deadline = started + float(remaining)
            allowance = min(2, deadline - asyncio.get_running_loop().time() - .1)
            if allowance <= 0:
                raise ValueError('game_lease_expiring')
            async with asyncio.timeout(allowance):
                yield
        except Error as error:
            raise ValueError('game_admission_unavailable') from error
        finally:
            if connection is not None:
                await _settle(asyncio.create_task(connection.close()))


class GameRequestBody(LaneRequestBody):
    """Keep edition, consent, source and job locks through actual body send."""
    fence_type = GameFence


async def _game_response(packet, *, token, phase, payload):
    base = os.getenv('MEMORY_SPARK_LLM_BASE_URL', '').rstrip('/')
    model = (os.getenv('MEMORY_SPARK_MEMOIR_COMPOSER_MODEL') or os.getenv('MEMORY_SPARK_LLM_MODEL', ''))
    effort = os.getenv('MEMORY_SPARK_MEMOIR_COMPOSER_REASONING_EFFORT', 'low').strip() or 'low'
    key = os.getenv('MEMORY_SPARK_LLM_API_KEY', '')
    parsed = urlsplit(base)
    if (not key or not model or parsed.scheme not in {'http', 'https'} or not parsed.hostname
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise ValueError('game_provider_unavailable')
    instructions = load_story_game_skill() + '\n\n' + load_prompt_artifact(
        prompt_path('memoir/skills/memoir-story-game/' + ('brief' if phase == 'brief' else 'proposal')))
    output = GameBrief if phase == 'brief' else ScenePool
    schema = output.model_json_schema()
    name = 'memoir-story-game-' + phase
    body = dict(model=model, instructions=instructions, input=json.dumps(payload, ensure_ascii=False),
        store=False, max_output_tokens=8192 if phase == 'brief' else 32768, reasoning={'effort': effort},
        metadata={'generation_name': name, 'trace_name': name},
        text={'format': {'type': 'json_schema', 'name': 'memoir_game_' + phase, 'strict': True,
                         'schema': schema}})
    from .model_request import instruction_manifest, manifest_metadata
    manifest = instruction_manifest(instructions, schema, variant='story-game-' + phase)
    body['metadata'].update(manifest_metadata(manifest))
    content = json.dumps(body, ensure_ascii=False).encode('utf-8')
    request = GameRequestBody(content,
        publisher=GamePublication(os.getenv('MEMOIR_PUBLICATION_DATABASE_URL')),
        fence=dict(game_id=packet['game_id'], token=token, authority=packet['authority']))
    try:
        from .llm_tracing import trace_llm_call
        with trace_llm_call('story.game.' + phase, model, metadata={'prompt_manifest': manifest}):
            async with httpx.AsyncClient(trust_env=False, follow_redirects=False, timeout=120) as client:
                async with client.stream('POST', base + '/responses', content=request,
                                         headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json',
                                                  'Content-Length': str(len(content))}) as response:
                    response.raise_for_status()
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        raw.extend(chunk)
                        if len(raw) > 512000:
                            raise ValueError('game_response_limit')

    finally:
        await request.aclose()
    if key.encode() in raw:
        raise ValueError('unsafe_game_response')
    result = json.loads(raw)
    if result.get('status') != 'completed' or not result.get('id') or not result.get('model'):
        raise ValueError('incomplete_game_response')
    text = ''.join(part.get('text', '') for item in result.get('output', []) if item.get('type') == 'message'
                   for part in item.get('content', []) if part.get('type') == 'output_text')
    value = output.model_validate_json(text).model_dump(mode='json')
    return value, dict(status='completed', response_id=result['id'], model=result['model'],
        requested_reasoning_effort=effort, provider_reasoning_effort=(result.get('reasoning') or {}).get('effort'),
        prompt_manifest=manifest)


async def propose_game(packet, *, token):
    return await _game_response(packet, token=token, phase='scenes', payload={
        'chapters': packet['chapters'], 'timeline': packet['timeline'],
        'locale': packet['authority']['locale']})


async def compose_game_brief(packet, proposal, *, token):
    payload = dict(locale=packet['authority']['locale'], ui=game_ui(packet['authority']['locale']),
        scenes=public_scenes(proposal))
    return await _game_response(packet, token=token, phase='brief', payload=payload)


async def build_game(packet, proposal, *, token):
    """The worker loads the installed skill and the saved, confirmed brief itself."""
    base = os.getenv('MEMORY_SPARK_CODEX_WORKER_URL', '').rstrip('/')
    secret = os.getenv('MEMORY_SPARK_CODEX_WORKER_SECRET', '')
    if not base or not secret:
        raise ValueError('game_worker_unavailable')
    content = json.dumps(dict(game_id=packet['game_id'], token=token, authority=packet['authority'])).encode()
    request = GameRequestBody(content, publisher=GamePublication(os.getenv('MEMOIR_PUBLICATION_DATABASE_URL')),
        fence=dict(game_id=packet['game_id'], token=token, authority=packet['authority']))
    try:
        async with httpx.AsyncClient(trust_env=False, follow_redirects=False, timeout=790) as client:
            response = await client.post(base + '/internal/story-game/build', content=request,
                headers={'X-Codex-Worker-Secret': secret, 'Content-Type': 'application/json',
                    'Content-Length': str(len(content))})
            response.raise_for_status()
        result = response.json()
        return result['webpage'], result['receipt']
    finally:
        await request.aclose()


async def generate_story_game(broker, game_id, *, provider=None, composer=None, builder=None):
    game_id = str(UUID(str(game_id)))
    claim = await broker.rpc('claim_story_game', p_game_id=game_id)
    if claim['status'] != 'running':
        return claim
    token = str(UUID(claim['token']))
    try:
        async with asyncio.timeout(840 if claim.get('phase') == 'build' else 150):
            packet = await broker.rpc('read_story_game_input', p_game_id=game_id, p_token=token)
            if claim.get('phase') != 'build':
                pool, receipt = await provider(packet) if provider else await propose_game(packet, token=token)
                pool = validate_pool(packet, pool)
                return await broker.rpc('save_story_game_pool', p_game_id=game_id, p_token=token,
                    p_pool=pool, p_model_receipt=receipt)
            proposal = selected_scenes(packet)
            if not packet.get('brief'):
                brief, receipt = (await composer(packet, proposal) if composer else
                    await compose_game_brief(packet, proposal, token=token))
                brief = validate_brief(brief, len(proposal['scenes']))
                await broker.rpc('save_story_game_brief', p_game_id=game_id, p_token=token,
                    p_brief=brief, p_model_receipt=receipt)
                packet['brief'] = brief
            webpage, build_receipt = (await builder(proposal) if builder else
                await build_game(packet, proposal, token=token))
            webpage = GameWebpage.model_validate(webpage).model_dump(mode='json')
            validate_webpage(webpage['html'], game_ui(packet['authority']['locale']))
            return await broker.rpc('stage_story_game', p_game_id=game_id, p_token=token,
                p_proposal={**proposal, **webpage}, p_model_receipt={**build_receipt,
                    'selection_digest': packet['selection_digest']})
    except BaseException:
        # The same durable job can be retried explicitly; an old lease cannot stage.
        try:
            await asyncio.shield(broker.rpc('fail_story_game', p_game_id=game_id, p_token=token))
        except (Exception, asyncio.CancelledError):
            pass
        raise
