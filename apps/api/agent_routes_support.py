import os

import httpx
from fastapi import Header, HTTPException

from .agent_storage import UserStorage


def authenticated_storage(authorization: str | None = Header(default=None)):
    url = os.getenv('SUPABASE_URL')
    key = os.getenv('SUPABASE_PUBLISHABLE_KEY')
    if not url or not key:
        raise HTTPException(503, 'Supabase user storage is not configured')
    if not authorization or not authorization.startswith('Bearer '):
        raise HTTPException(401, 'Supabase sign-in required')
    try:
        return UserStorage(url, key, authorization[7:])
    except httpx.HTTPStatusError:
        raise HTTPException(401, 'Invalid or expired Supabase session') from None
    except httpx.RequestError:
        raise HTTPException(503, 'Supabase authentication unavailable') from None
