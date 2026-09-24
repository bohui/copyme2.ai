"""Authenticated Supabase API boundary, separate from prototype demo accounts."""
import os

import httpx
from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from .agent_routes_support import authenticated_storage

router = APIRouter(prefix='/v1/user', tags=['Supabase user data'])


storage = authenticated_storage


class MemoryInput(BaseModel):
    content: str = Field(min_length=1, max_length=100000)


@router.put('/profile')
def save_profile(payload: dict, authorization: str | None = Header(default=None)):
    service = storage(authorization)
    try:
        return service.save_profile(payload)
    finally:
        service.client.close()


@router.post('/attachments')
async def upload_attachment(request: Request, filename: str,
                            authorization: str | None = Header(default=None)):
    # Keep the same 50 MiB bound as the bucket, including chunked uploads.
    chunks = bytearray()
    async for chunk in request.stream():
        chunks.extend(chunk)
        if len(chunks) > 50 * 1024 * 1024:
            raise HTTPException(413, 'Attachment exceeds 50 MiB')
    service = storage(authorization)
    try:
        path = service.put_attachment(filename, bytes(chunks), request.headers.get('content-type', 'application/octet-stream'))
        return {'path': path}
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    finally:
        service.client.close()


@router.get('/memories')
def list_memories(authorization: str | None = Header(default=None)):
    service = storage(authorization)
    try:
        return {'items': service.memories()}
    finally:
        service.client.close()


@router.post('/memories')
def save_memory(payload: MemoryInput, authorization: str | None = Header(default=None)):
    service = storage(authorization)
    try:
        return service.save_memory(payload.content)
    finally:
        service.client.close()
