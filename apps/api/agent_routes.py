"""Supabase-authenticated Codex conversation endpoints."""
import os

import httpx
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from .agent_routes_support import authenticated_storage
from .codex_runtime import CodexRuntime

router = APIRouter(prefix='/v1/agent', tags=['Codex agent'])
runtime = CodexRuntime()


class TurnInput(BaseModel):
    text: str = Field(min_length=1, max_length=100000)


@router.get('/config')
def config():
    return {
        'enabled': bool(os.getenv('SUPABASE_URL') and os.getenv('SUPABASE_PUBLISHABLE_KEY')),
        'supabase_url': os.getenv('SUPABASE_URL'),
        'supabase_publishable_key': os.getenv('SUPABASE_PUBLISHABLE_KEY'),
    }


@router.post('/turn')
def turn(payload: TurnInput, authorization: str | None = Header(default=None)):
    try:
        storage = authenticated_storage(authorization)
    except HTTPException:
        raise
    try:
        import asyncio
        return asyncio.run(runtime.turn(storage, payload.text))
    except (httpx.HTTPStatusError, httpx.RequestError) as error:
        raise HTTPException(502, f'Supabase persistence failed: {error}') from None
    except RuntimeError as error:
        raise HTTPException(502, f'Codex agent failed: {error}') from None
    finally:
        storage.client.close()
