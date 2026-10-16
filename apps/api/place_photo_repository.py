"""Global Supabase cache containing only public source-backed photo metadata."""
import hashlib
import json
import logging
import os
import unicodedata
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)


def _expansion_enabled():
    return os.getenv('MEMOIR_PHOTO_EXPANSION', '').strip().lower() in {'1', 'true', 'yes'}


def search_key(place, period, *, policy=None):
    from .place_photos import PHOTO_SEARCH_POLICY
    if policy is None and _expansion_enabled():
        from .place_photos import _configured_env
        # Source-provider configuration affects completeness; never treat a
        # result from a different route as proof the current route was searched.
        if _configured_env('GOOGLE_CSE_API_KEY') and _configured_env('GOOGLE_CSE_ID'):
            google = 'cse-api'
        elif _configured_env('SERPAPI_KEY'):
            google = 'serpapi'
        elif _configured_env('GOOGLE_CSE_URL') or _configured_env('GOOGLE_CSE_ID'):
            google = 'cse-browser'
        else:
            google = 'none'
        flickr = 'flickr-api' if _configured_env('FLICKR_API_KEY') else 'flickr-browser'
        llm = 'llm-on' if _configured_env('MEMORY_SPARK_PHOTO_WEB_SEARCH').lower() in {'1', 'true', 'yes'} else 'llm-off'
        # Never include credential values, only provider modes, in a cache ID.
        policy = f'{PHOTO_SEARCH_POLICY}-expanded-v1-{google}-{flickr}-{llm}'
    normalized = [' '.join(unicodedata.normalize('NFKC', value).casefold().split())
                  for value in (place, period)]
    return hashlib.sha256(json.dumps([policy or PHOTO_SEARCH_POLICY, *normalized], ensure_ascii=False).encode()).hexdigest()


class PhotoRepository:
    def __init__(self, url, secret, *, transport=None):
        self.url = url.rstrip('/') + '/rest/v1/place_photo_searches'
        self.headers = {'apikey': secret, 'Authorization': 'Bearer ' + secret}
        self.transport = transport

    def load(self, place, period):
        try:
            with httpx.Client(timeout=10, transport=self.transport) as client:
                # Revalidate previous public research under the current filters
                # so source outages do not discard already found photographs.
                for policy in ((None,) if _expansion_enabled() else (None, 'place-fallback-gps-time-v8')):
                    response = client.get(self.url, headers=self.headers, params={
                        'search_key': 'eq.' + search_key(place, period, policy=policy), 'select': 'result', 'limit': '1'})
                    response.raise_for_status()
                    rows = response.json()
                    if rows:
                        result = rows[0]['result']
                        return result if isinstance(result, dict) and isinstance(result.get('items'), list) else None
                return None
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            logger.warning('Shared photo cache read unavailable')
            return None

    def save(self, place, period, result):
        try:
            with httpx.Client(timeout=10, transport=self.transport) as client:
                response = client.post(self.url, headers={**self.headers,
                    'Prefer': 'resolution=merge-duplicates,return=minimal'}, json={
                        'search_key': search_key(place, period), 'place': place, 'period': period,
                        'result': result, 'updated_at': datetime.now(timezone.utc).isoformat()}, params={'on_conflict': 'search_key'})
                response.raise_for_status()
        except (httpx.HTTPError, ValueError, TypeError):
            logger.warning('Shared photo cache write unavailable')


def configured_repository():
    url, secret = os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_SECRET_KEY')
    return PhotoRepository(url, secret) if url and secret else None
