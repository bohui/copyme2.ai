"""Private photo research worker with one warm Chromium process."""
import asyncio
from contextlib import asynccontextmanager
import hmac
import os

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, model_validator

from .place_photo_browser import WarmPhotoBrowser, set_warm_browser
from .place_photo_pages import PhotoPages
from .place_photo_repository import configured_repository
from .turn_stream import STREAM_HEADERS


class PhotoSearchInput(BaseModel):
    owner: str = Field(min_length=1, max_length=128)
    place: str = Field(min_length=1, max_length=120)
    period: str = Field(default='', max_length=160)
    cursor: str | None = Field(default=None, max_length=160)
    refresh: bool = False
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)

    @model_validator(mode='after')
    def coordinate_pair(self):
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError('Both photo search coordinates are required')
        return self


def create_photo_worker(*, browser_factory=WarmPhotoBrowser, pages=None):
    cache = pages or PhotoPages(repository=configured_repository())

    @asynccontextmanager
    async def lifespan(app):
        browser = await browser_factory().start()
        set_warm_browser(browser)
        app.state.browser_ready = True
        try:
            yield
        finally:
            app.state.browser_ready = False
            set_warm_browser(None)
            cache.close()
            await browser.close()

    app = FastAPI(lifespan=lifespan)
    app.state.browser_ready = False

    @app.get('/health')
    async def health():
        if not app.state.browser_ready:
            raise HTTPException(status_code=503, detail='Photo browser is warming')
        return {'status': 'ready'}

    @app.post('/internal/photos')
    async def photos(payload: PhotoSearchInput, request: Request,
                     x_photo_worker_secret: str | None = Header(default=None)):
        expected = os.getenv('MEMORY_SPARK_PHOTO_WORKER_SECRET', '')
        if not expected or not hmac.compare_digest(x_photo_worker_secret or '', expected):
            raise HTTPException(status_code=401, detail='Worker authentication required')
        args = (payload.owner, payload.place, payload.period, payload.cursor)
        coordinates = {'latitude': payload.latitude, 'longitude': payload.longitude}
        if 'application/x-ndjson' in request.headers.get('accept', ''):
            snapshot = cache._snapshot(*args, refresh=payload.refresh, **coordinates)  # Validate before sending stream headers.
            return StreamingResponse(cache.stream(*args, snapshot=snapshot), media_type='application/x-ndjson',
                                     headers=STREAM_HEADERS)
        return await asyncio.to_thread(cache.page, *args, refresh=payload.refresh, **coordinates)

    return app


app = create_photo_worker()
