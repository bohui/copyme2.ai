"""Supabase-authenticated Codex conversation endpoints."""
import asyncio
import os

import httpx
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from .agent_lock import AgentTurnBusyError
from .agent_routes_support import authenticated_storage
from .codex_runtime import CodexRuntime

router = APIRouter(prefix='/v1/agent', tags=['Codex agent'])
runtime = CodexRuntime()


class TurnInput(BaseModel):
    text: str = Field(min_length=1, max_length=100000)


@router.get('/config')
def config():
    configured = bool(os.getenv('SUPABASE_URL') and os.getenv('SUPABASE_PUBLISHABLE_KEY'))
    return {
        'enabled': configured,
        'auth_mode': 'supabase' if configured else ('test' if os.getenv('MEMORY_SPARK_TEST_MODE') == '1' else 'disabled'),
        'supabase_url': os.getenv('SUPABASE_URL'),
        'supabase_publishable_key': os.getenv('SUPABASE_PUBLISHABLE_KEY'),
    }


@router.post('/turn')
async def turn(payload: TurnInput, authorization: str | None = Header(default=None)):
    storage = await asyncio.to_thread(authenticated_storage, authorization)
    try:
        return await runtime.turn(storage, payload.text)
    except (httpx.HTTPStatusError, httpx.RequestError) as error:
        raise HTTPException(502, f'Supabase persistence failed: {error}') from None
    except AgentTurnBusyError as error:
        raise HTTPException(409, str(error), headers={'X-Error-Code': 'AGENT_TURN_IN_PROGRESS'}) from None
    except RuntimeError as error:
        raise HTTPException(502, f'Codex agent failed: {error}') from None
    finally:
        await asyncio.to_thread(storage.client.close)
