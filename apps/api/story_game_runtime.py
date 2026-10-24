"""Chapters/timeline to scenes, then Astra to a validated game webpage."""
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


class SceneProposal(BaseModel):
    model_config = {'extra': 'forbid'}
    chapter_id: str = Field(min_length=1, max_length=200)
    block_index: int = Field(ge=0, le=7, strict=True)
    title: str = Field(min_length=1, max_length=100)
    person: str | None = Field(min_length=2, max_length=80)
    quote: str = Field(min_length=1, max_length=400)
    event_ids: list[str] = Field(min_length=1, max_length=128)


class GameProposal(BaseModel):
    model_config = {'extra': 'forbid'}
    scenes: list[SceneProposal] = Field(min_length=1, max_length=128)


class GameWebpage(BaseModel):
    model_config = {'extra': 'forbid'}
    html: str = Field(min_length=100, max_length=150000)


def game_ui(locale):
    locale = 'zh-CN' if locale == 'zh-CN' else 'en-AU'
    path = Path(__file__).resolve().parents[1] / 'web/messages' / (locale + '.json')
    labels = json.loads(path.read_text())['Memoir']['game']
    return {key: labels[key] for key in ('title', 'framing', 'movement', 'controls',
        'left', 'right', 'interact', 'textVersion')}


def validate_scenes(packet, proposal):
    proposal = GameProposal.model_validate(proposal).model_dump(mode='json')
    chapters = {c['chapter_id']: c for c in packet['chapters']}
    event_ids = {e['id'] for e in packet['timeline']}
    covered = set()
    for scene in proposal['scenes']:
        chapter = chapters.get(scene['chapter_id'])
        index = scene['block_index']
        if not chapter or index >= len(chapter['blocks']):
            raise ValueError('game_chapter_required')
        quote = scene['quote']
        supported = set(chapter['event_ids'])
        if (chapter['blocks'][index]['text'].count(quote) != 1
                or scene['person'] and scene['person'] not in quote
                or not set(scene['event_ids']) <= supported & event_ids):
            raise ValueError('game_scene_grounding_invalid')
        if scene['title'] not in quote:
            # Titles are presentation; replace paraphrases with supported text.
            scene['title'] = quote[:100].rsplit(' ', 1)[0] if len(quote) > 100 and ' ' in quote[:100] else quote[:100]
        covered.update(scene['event_ids'])
    if covered != event_ids:
        raise ValueError('game_timeline_coverage_required')
    return proposal


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
    building = phase == 'webpage'
    model = (os.getenv('MEMORY_SPARK_STORY_GAME_BUILD_MODEL', 'gpt-6-astra') if building else
        os.getenv('MEMORY_SPARK_MEMOIR_COMPOSER_MODEL') or os.getenv('MEMORY_SPARK_LLM_MODEL', ''))
    effort = os.getenv('MEMORY_SPARK_MEMOIR_COMPOSER_REASONING_EFFORT', 'low').strip() or 'low'
    key = os.getenv('MEMORY_SPARK_LLM_API_KEY', '')
    parsed = urlsplit(base)
    if (not key or not model or parsed.scheme not in {'http', 'https'} or not parsed.hostname
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise ValueError('game_provider_unavailable')
    instructions = load_story_game_skill() + '\n\n' + load_prompt_artifact(
        prompt_path('memoir/skills/memoir-story-game/' + ('webpage' if building else 'proposal')))
    output = GameWebpage if building else GameProposal
    schema = output.model_json_schema()
    name = 'memoir-story-game-' + phase
    body = dict(model=model, instructions=instructions, input=json.dumps(payload, ensure_ascii=False),
        store=False, max_output_tokens=16384 if building else 32768, reasoning={'effort': effort},
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
            async with httpx.AsyncClient(trust_env=False, follow_redirects=False, timeout=180 if building else 120) as client:
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


async def build_game(packet, proposal, *, token):
    # The page designer needs scene text and public UI labels, not source/job IDs.
    payload = dict(locale=packet['authority']['locale'], ui=game_ui(packet['authority']['locale']),
        scenes=[dict(index=i, title=s['title'], person=s['person'], quote=s['quote'])
                for i, s in enumerate(proposal['scenes'])])
    return await _game_response(packet, token=token, phase='webpage', payload=payload)


async def generate_story_game(broker, game_id, *, provider=None, builder=None):
    game_id = str(UUID(str(game_id)))
    claim = await broker.rpc('claim_story_game', p_game_id=game_id)
    if claim['status'] != 'running':
        return claim
    token = str(UUID(claim['token']))
    try:
        async with asyncio.timeout(330):
            packet = await broker.rpc('read_story_game_input', p_game_id=game_id, p_token=token)
            proposal, receipt = await provider(packet) if provider else await propose_game(packet, token=token)
            proposal = validate_scenes(packet, proposal)
            webpage, build_receipt = (await builder(proposal) if builder else
                await build_game(packet, proposal, token=token))
            webpage = GameWebpage.model_validate(webpage).model_dump(mode='json')
            validate_webpage(webpage['html'], game_ui(packet['authority']['locale']))
            return await broker.rpc('stage_story_game', p_game_id=game_id, p_token=token,
                p_proposal={**proposal, **webpage}, p_model_receipt={**build_receipt,
                    'steps': {'scenes': receipt, 'webpage': build_receipt}})
    except BaseException:
        # The same durable job can be retried explicitly; an old lease cannot stage.
        try:
            await asyncio.shield(broker.rpc('fail_story_game', p_game_id=game_id, p_token=token))
        except (Exception, asyncio.CancelledError):
            pass
        raise
