"""Forward public photo research without exposing worker credentials."""
import asyncio
import json
import os

import httpx
from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from .turn_stream import STREAM_HEADERS


async def photo_response(cache, owner, place, period, cursor, *, stream=False):
    args = (owner, place, period, cursor)
    origin = os.getenv('MEMORY_SPARK_PHOTO_WORKER_URL', '').rstrip('/')
    if not origin:
        if stream:
            snapshot = cache._snapshot(*args)
            return StreamingResponse(cache.stream(*args, snapshot=snapshot), media_type='application/x-ndjson',
                                     headers=STREAM_HEADERS)
        return await asyncio.to_thread(cache.page, *args)

    client = httpx.AsyncClient(timeout=httpx.Timeout(240, connect=5))
    headers = {'X-Photo-Worker-Secret': os.getenv('MEMORY_SPARK_PHOTO_WORKER_SECRET', ''),
               'Accept': 'application/x-ndjson' if stream else 'application/json'}
    try:
        request = client.build_request('POST', origin + '/internal/photos', headers=headers,
            json={'owner': owner, 'place': place, 'period': period, 'cursor': cursor})
        response = await client.send(request, stream=True)
        if response.status_code in (410, 422):
            await response.aclose()
            raise HTTPException(status_code=response.status_code, detail='Photo cursor is expired or invalid')
        response.raise_for_status()
    except Exception:
        await client.aclose()
        raise

    if not stream:
        try:
            await response.aread()
            return response.json()
        finally:
            await response.aclose()
            await client.aclose()

    async def events():
        try:
            async for chunk in response.aiter_bytes():
                yield chunk
        except httpx.HTTPError:
            yield json.dumps({'items': [], 'status': 'UNAVAILABLE', 'searching': False}) + '\n'
        finally:
            await response.aclose()
            await client.aclose()
    return StreamingResponse(events(), media_type='application/x-ndjson', headers=STREAM_HEADERS)
