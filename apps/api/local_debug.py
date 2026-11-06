"""Opt-in debug generation for the loopback workspace."""
import os
from urllib.parse import urlsplit

from fastapi import HTTPException


def _request_url(request):
    return 'http://' + (request.headers.get('x-forwarded-host') or request.headers.get('host', ''))


def _loopback(url):
    try:
        return urlsplit(url).hostname in {'localhost', '127.0.0.1', '::1'}
    except ValueError:
        return False


def loopback_browser(request):
    return _loopback(request.headers.get('origin') or request.headers.get('referer') or _request_url(request))


def debug_early_generation(request):
    return (os.getenv('MEMORY_SPARK_DEBUG_EARLY_GENERATION', '').strip().lower() in {'1', 'true', 'yes', 'on'}
            and _loopback(_request_url(request)) and loopback_browser(request))


async def debug_generation_rpc(name, owner_id, **parameters):
    from .memory_event_worker import MemoirLaneBroker
    try:
        broker = MemoirLaneBroker()
    except KeyError:
        raise HTTPException(503, 'Debug generation storage is unavailable') from None
    try:
        return await broker.rpc(name, p_owner=owner_id, **parameters)
    finally:
        await broker.client.aclose()
