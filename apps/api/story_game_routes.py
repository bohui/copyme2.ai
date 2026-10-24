"""Owner-authorized game preparation and guarded game delivery."""
import asyncio
import os
import re
from uuid import UUID

import httpx
from fastapi import APIRouter, BackgroundTasks, Header, HTTPException
from pydantic import BaseModel, Field
from starlette.responses import JSONResponse, Response

from .agent_routes_support import authenticated_storage
from .conversation_recovery import PROJECT_ID_PATTERN
from .formal_memoir_routes import _rpc_error

router = APIRouter(tags=['Private story game'])


class GameRequest(BaseModel):
    model_config = {'extra': 'forbid'}
    request_id: UUID


class SceneSelection(BaseModel):
    model_config = {'extra': 'forbid'}
    expected_pool_digest: str = Field(pattern=r'^[a-f0-9]{64}$')
    scene_ids: list[str] = Field(min_length=1, max_length=128)


class FormalAdvance(BaseModel):
    model_config = {'extra': 'forbid'}
    run_id: UUID


class PersonPermission(BaseModel):
    model_config = {'extra': 'forbid'}
    person_id: UUID
    adult: bool = Field(strict=True)
    permitted: bool = Field(strict=True)
    distinct_person: bool = Field(strict=True)


class PublishGame(BaseModel):
    model_config = {'extra': 'forbid'}
    expected_digest: str = Field(pattern=r'^[a-f0-9]{64}$')
    permissions: list[PersonPermission] = Field(min_length=2, max_length=2)


async def owned_storage(project_id, authorization):
    if not re.fullmatch(PROJECT_ID_PATTERN, project_id):
        raise HTTPException(422, 'Invalid project')
    return await asyncio.to_thread(authenticated_storage, authorization)


async def rpc(storage, name, project_id, **parameters):
    return (await asyncio.to_thread(storage.request, 'POST', '/rest/v1/rpc/' + name,
        json={'p_project_id': project_id, **parameters})).json()


class StoryGameResponse(Response):
    """Read and send under one transaction, so revocation cannot race the send."""
    def __init__(self, owner, project_id, game_id=None, *, review=False):
        super().__init__(headers={'Cache-Control': 'private, no-store'})
        self.owner = str(UUID(str(owner))) if owner is not None else None
        self.project_id, self.game_id, self.review = project_id, str(game_id) if game_id else None, review

    async def __call__(self, scope, receive, send):
        from psycopg import AsyncConnection, Error
        connection, started = None, False

        async def guarded_send(message):
            nonlocal started
            if message['type'] == 'http.response.start':
                started = True
            await send(message)

        try:
            async with asyncio.timeout(5):
                dsn = os.getenv('MEMOIR_PUBLICATION_DATABASE_URL')
                if not dsn:
                    raise ValueError('game_publication_unavailable')
                connection = await AsyncConnection.connect(dsn, connect_timeout=2)
                await connection.execute('set local role authenticated' if self.owner else 'set local role anon')
                await connection.execute("select set_config('request.jwt.claim.sub',%s,true)", (self.owner or '',))
                await connection.execute("set local lock_timeout='2s'")
                cursor = (await connection.execute('select public.read_story_game(%s,%s,%s)',
                    (self.project_id, self.game_id, self.review)) if self.game_id else
                    await connection.execute('select public.read_story_game_page(%s)', (self.project_id,)))
                value = (await cursor.fetchone())[0]
                response = JSONResponse(value, headers={'Cache-Control': 'private, no-store'})
                async with asyncio.timeout(2):
                    await response(scope, receive, guarded_send)
        except (Error, ValueError, TimeoutError) as error:
            if started:
                raise RuntimeError('game_delivery_interrupted') from None
            code = getattr(error, 'sqlstate', None)
            status = 404 if code == 'PT404' else 403 if code == '42501' else 409 if code in {'PT409', '40001', '55000'} else 503
            await JSONResponse({'detail': 'This game is unavailable or has changed. Reload before continuing.'},
                status_code=status, headers={'Cache-Control': 'private, no-store'})(scope, receive, send)
        finally:
            if connection is not None:
                from .lifetime_memory_reads import _settle
                await _settle(asyncio.create_task(connection.close()))


@router.get('/projects/{project_id}/story-game')
async def game_status(project_id: str, authorization: str | None = Header(default=None)):
    storage = await owned_storage(project_id, authorization)
    try:
        result = await rpc(storage, 'read_story_game_status', project_id)
        return JSONResponse(result, headers={'Cache-Control': 'no-store'})
    except httpx.HTTPStatusError as error:
        raise _rpc_error(error) from None
    finally:
        await asyncio.to_thread(storage.client.close)


@router.post('/projects/{project_id}/formal-memoir/advance')
async def advance_formal(project_id: str, payload: FormalAdvance,
                         authorization: str | None = Header(default=None)):
    from .formal_memoir import advance_formal_memoir
    from .memory_event_worker import MemoirLaneBroker
    storage = await owned_storage(project_id, authorization)
    broker = None
    try:
        status = await rpc(storage, 'read_formal_memoir_status', project_id)
        if (status.get('run') or {}).get('run_id') != str(payload.run_id):
            raise HTTPException(409, 'Formal memoir run changed.')
        broker = MemoirLaneBroker()
        result = await advance_formal_memoir(broker, payload.run_id)
        return JSONResponse(result, headers={'Cache-Control': 'no-store'})
    except httpx.HTTPStatusError as error:
        raise _rpc_error(error) from None
    finally:
        await asyncio.to_thread(storage.client.close)
        if broker is not None:
            await broker.client.aclose()


@router.post('/projects/{project_id}/story-game', status_code=202)
async def create_game(project_id: str, payload: GameRequest,
                      authorization: str | None = Header(default=None)):
    from .story_game_runtime import generate_story_game
    from .memory_event_worker import MemoirLaneBroker
    storage = await owned_storage(project_id, authorization)
    broker = None
    try:
        job = await rpc(storage, 'begin_story_game', project_id, p_request_id=str(payload.request_id))
        broker = MemoirLaneBroker()
        result = await generate_story_game(broker, job['game_id'])
        return JSONResponse(result, status_code=202, headers={'Cache-Control': 'no-store'})
    except httpx.HTTPStatusError as error:
        raise _rpc_error(error) from None
    except (httpx.RequestError, ValueError, KeyError, TimeoutError):
        raise HTTPException(503, 'Game preparation was not completed. Retry the same request.') from None
    finally:
        await asyncio.to_thread(storage.client.close)
        if broker is not None:
            await broker.client.aclose()


@router.get('/projects/{project_id}/story-game/{game_id}')
async def read_game(project_id: str, game_id: UUID, review: bool = False,
                    authorization: str | None = Header(default=None)):
    storage = await owned_storage(project_id, authorization)
    try:
        return StoryGameResponse(storage.user_id, project_id, game_id, review=review)
    finally:
        await asyncio.to_thread(storage.client.close)


@router.post('/projects/{project_id}/story-game/{game_id}/selection', status_code=202)
async def confirm_scenes(project_id: str, game_id: UUID, payload: SceneSelection,
                         background_tasks: BackgroundTasks,
                         authorization: str | None = Header(default=None)):
    storage = await owned_storage(project_id, authorization)
    try:
        result = await rpc(storage, 'confirm_story_game_scenes', project_id, p_game_id=str(game_id),
            p_expected_digest=payload.expected_pool_digest, p_scene_ids=payload.scene_ids)
        if result['status'] != 'published':
            background_tasks.add_task(_build_confirmed_game, game_id)
        return JSONResponse(result, status_code=202, headers={'Cache-Control': 'no-store'})
    except httpx.HTTPStatusError as error:
        raise _rpc_error(error) from None
    except (httpx.RequestError, ValueError, KeyError, TimeoutError):
        raise HTTPException(503, 'Scene confirmation could not be saved. Reload and retry.') from None
    finally:
        await asyncio.to_thread(storage.client.close)


async def _build_confirmed_game(game_id):
    """The durable claim owns retries; no long-lived browser request is needed."""
    from .story_game_runtime import generate_story_game
    from .memory_event_worker import MemoirLaneBroker
    broker = MemoirLaneBroker()
    try:
        await generate_story_game(broker, game_id)
    except (httpx.HTTPError, ValueError, KeyError, TimeoutError):
        # generate_story_game records failure against its lease. The owner can
        # retry the saved selection; no provider work is automatically repeated.
        pass
    finally:
        await broker.client.aclose()


@router.post('/projects/{project_id}/story-game/{game_id}/publish')
async def publish_game(project_id: str, game_id: UUID, payload: PublishGame,
                       authorization: str | None = Header(default=None)):
    storage = await owned_storage(project_id, authorization)
    try:
        result = await rpc(storage, 'publish_story_game', project_id, p_game_id=str(game_id),
            p_expected_digest=payload.expected_digest,
            p_permissions=[person.model_dump(mode='json') for person in payload.permissions])
        return JSONResponse(result, headers={'Cache-Control': 'no-store'})
    except httpx.HTTPStatusError as error:
        raise _rpc_error(error) from None
    finally:
        await asyncio.to_thread(storage.client.close)
