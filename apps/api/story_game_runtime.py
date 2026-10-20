"""Bounded game proposals; PostgreSQL owns evidence, consent, review and publication."""
import asyncio
from contextlib import asynccontextmanager
import json
import os
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from pydantic import BaseModel, Field

from .memoir_story_game import load_story_game_skill
from .lifetime_memory_lane_engine import LaneRequestBody, _settle
from .prompt_artifact import load_prompt_artifact, prompt_path


class SceneProposal(BaseModel):
    model_config = {'extra': 'forbid'}
    chapter_id: UUID
    block_index: int = Field(ge=0, le=7, strict=True)
    title: str = Field(min_length=1, max_length=100)
    person: str = Field(min_length=2, max_length=80)
    quote: str = Field(min_length=1, max_length=400)
    art: str = Field(pattern=r'^generic-(garden|workroom)$')


class GameProposal(BaseModel):
    model_config = {'extra': 'forbid'}
    scenes: list[SceneProposal] = Field(min_length=2, max_length=2)


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


async def propose_game(packet, *, token):
    base = os.getenv('MEMORY_SPARK_LLM_BASE_URL', '').rstrip('/')
    model = os.getenv('MEMORY_SPARK_MEMOIR_COMPOSER_MODEL') or os.getenv('MEMORY_SPARK_LLM_MODEL', '')
    key = os.getenv('MEMORY_SPARK_LLM_API_KEY', '')
    parsed = urlsplit(base)
    if (not key or not model or parsed.scheme not in {'http', 'https'} or not parsed.hostname
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise ValueError('game_provider_unavailable')
    instructions = load_story_game_skill() + '\n\n' + load_prompt_artifact(
        prompt_path('memoir/skills/memoir-story-game/proposal'))
    body = dict(model=model, instructions=instructions, input=json.dumps(packet, ensure_ascii=False),
        store=False, max_output_tokens=2500, reasoning={'effort': 'low'},
        metadata={'generation_name': 'memoir-story-game', 'trace_name': 'memoir-story-game'},
        text={'format': {'type': 'json_schema', 'name': 'memoir_game_proposal', 'strict': True,
                         'schema': GameProposal.model_json_schema()}})
    content = json.dumps(body, ensure_ascii=False).encode('utf-8')
    request = GameRequestBody(content,
        publisher=GamePublication(os.getenv('MEMOIR_PUBLICATION_DATABASE_URL')),
        fence=dict(game_id=packet['game_id'], token=token, authority=packet['authority']))
    try:
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
    proposal = GameProposal.model_validate_json(text).model_dump(mode='json')
    return proposal, dict(status='completed', response_id=result['id'], model=result['model'])


async def generate_story_game(broker, game_id, *, provider=None):
    game_id = str(UUID(str(game_id)))
    claim = await broker.rpc('claim_story_game', p_game_id=game_id)
    if claim['status'] != 'running':
        return claim
    token = str(UUID(claim['token']))
    try:
        async with asyncio.timeout(135):
            packet = await broker.rpc('read_story_game_input', p_game_id=game_id, p_token=token)
            proposal, receipt = await provider(packet) if provider else await propose_game(packet, token=token)
            proposal = GameProposal.model_validate(proposal).model_dump(mode='json')
            return await broker.rpc('stage_story_game', p_game_id=game_id, p_token=token,
                                    p_proposal=proposal, p_model_receipt=receipt)
    except BaseException:
        # The same durable job can be retried explicitly; an old lease cannot stage.
        try:
            await asyncio.shield(broker.rpc('fail_story_game', p_game_id=game_id, p_token=token))
        except (Exception, asyncio.CancelledError):
            pass
        raise
