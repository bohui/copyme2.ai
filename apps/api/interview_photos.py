"""Owner-authenticated private interview photographs; never public/signed URLs."""
import asyncio
from io import BytesIO
from uuid import UUID
import warnings

import httpx
from fastapi import APIRouter, Header, HTTPException, Request, Response
from PIL import Image, UnidentifiedImageError

from .agent_routes_support import authenticated_storage
from .conversation_recovery import PROJECT_ID_PATTERN

PRIVATE_PHOTO_BUCKET = 'memoir-private-photos'
MAX_PHOTO_BYTES = 10 * 1024 * 1024
PHOTO_TYPES = {'image/jpeg':'JPEG', 'image/png':'PNG', 'image/webp':'WEBP'}
router = APIRouter(prefix='/v1/agent/projects', tags=['Private interview photos'])


def validate_photo_bytes(content, content_type):
    if content_type not in PHOTO_TYPES:
        raise HTTPException(415, 'Use a JPEG, PNG or WebP photo')
    if not content or len(content) > MAX_PHOTO_BYTES:
        raise HTTPException(413, 'Photo must be between 1 byte and 10 MiB')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(BytesIO(content)) as image:
                if image.format != PHOTO_TYPES[content_type]:
                    raise HTTPException(415, 'Photo contents do not match its image type')
                if image.width * image.height > 36_000_000 or getattr(image, 'n_frames', 1) != 1:
                    raise HTTPException(413, 'Use a still photo no larger than 36 megapixels')
                width, height = image.size
                image.verify()
        return {'content_type':content_type, 'byte_size':len(content), 'width':width, 'height':height}
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise HTTPException(422, 'The photo could not be read') from None


def photo_card(project_id, metadata):
    photo_id = str(UUID(metadata['id']))
    return {'id':photo_id, 'photo_id':'upload:' + photo_id, 'kind':'private_upload',
            'title':'Your private photo', 'content_type':metadata['content_type'],
            'byte_size':metadata['byte_size'],
            'content_url':f'/v1/agent/projects/{project_id}/photos/{photo_id}/content'}


def _project(project_id):
    import re
    if not re.fullmatch(PROJECT_ID_PATTERN, project_id):
        raise HTTPException(422, 'Invalid project identity')


def _storage_error(error):
    if isinstance(error, ValueError): return HTTPException(404, 'Photo not found')
    if isinstance(error, httpx.HTTPStatusError) and error.response.status_code in (400, 403, 404):
        return HTTPException(404, 'Photo not found')
    return HTTPException(503, 'The private photo could not be saved or loaded. Please try again.')


@router.post('/{project_id}/photos', status_code=201)
async def upload_photo(project_id: str, request: Request, authorization: str | None = Header(default=None),
                       x_upload_idempotency_key: UUID | None = Header(default=None)):
    _project(project_id)
    storage = await asyncio.to_thread(authenticated_storage, authorization)
    try:
        chunks = bytearray()
        async for chunk in request.stream():
            chunks.extend(chunk)
            if len(chunks) > MAX_PHOTO_BYTES:
                raise HTTPException(413, 'Photo exceeds 10 MiB')
        metadata = await asyncio.to_thread(validate_photo_bytes, bytes(chunks), request.headers.get('content-type', ''))
        saved = await asyncio.to_thread(storage.put_interview_photo, project_id, bytes(chunks), metadata,
                                        str(x_upload_idempotency_key) if x_upload_idempotency_key else None)
        return photo_card(project_id, saved)
    except (httpx.HTTPError, ValueError) as error:
        raise _storage_error(error) from None
    finally:
        await asyncio.to_thread(storage.client.close)


@router.get('/{project_id}/photos/{photo_id}/content')
async def read_photo(project_id: str, photo_id: UUID, authorization: str | None = Header(default=None)):
    _project(project_id)
    storage = await asyncio.to_thread(authenticated_storage, authorization)
    try:
        content, metadata = await asyncio.to_thread(storage.get_interview_photo, project_id, str(photo_id))
        return Response(content=content, media_type=metadata['content_type'], headers={
            'Cache-Control':'private, no-store', 'Vary':'Authorization',
            'X-Content-Type-Options':'nosniff', 'Content-Disposition':'inline'})
    except (httpx.HTTPError, ValueError) as error:
        raise _storage_error(error) from None
    finally:
        await asyncio.to_thread(storage.client.close)


@router.delete('/{project_id}/photos/{photo_id}', status_code=204)
async def delete_photo(project_id: str, photo_id: UUID, authorization: str | None = Header(default=None)):
    _project(project_id)
    storage = await asyncio.to_thread(authenticated_storage, authorization)
    try:
        await asyncio.to_thread(storage.delete_interview_photo, project_id, str(photo_id))
        return Response(status_code=204)
    except (httpx.HTTPError, ValueError) as error:
        raise _storage_error(error) from None
    finally:
        await asyncio.to_thread(storage.client.close)


@router.delete('/{project_id}/photo-associations/{association_id}', status_code=204)
async def unlink_photo_association(project_id: str, association_id: UUID,
                                   authorization: str | None = Header(default=None)):
    """Unlink narrator evidence without changing the photograph or favourites."""
    _project(project_id)
    storage = await asyncio.to_thread(authenticated_storage, authorization)
    try:
        await asyncio.to_thread(storage.unlink_interview_photo, project_id, str(association_id))
        return Response(status_code=204)
    except (httpx.HTTPError, ValueError) as error:
        raise _storage_error(error) from None
    finally:
        await asyncio.to_thread(storage.client.close)
