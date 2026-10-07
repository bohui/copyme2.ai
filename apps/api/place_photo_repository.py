"""Global Supabase cache containing only public source-backed photo metadata."""
import hashlib
import json
import logging
import os
import unicodedata
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)


def search_key(place, period):
    from .place_photos import PHOTO_SEARCH_POLICY
    normalized = [' '.join(unicodedata.normalize('NFKC', value).casefold().split())
                  for value in (place, period)]
    return hashlib.sha256(json.dumps([PHOTO_SEARCH_POLICY, *normalized], ensure_ascii=False).encode()).hexdigest()


class PhotoRepository:
    def __init__(self, url, secret, *, transport=None):
        self.url = url.rstrip('/') + '/rest/v1/place_photo_searches'
        self.headers = {'apikey': secret, 'Authorization': 'Bearer ' + secret}
        self.transport = transport

    def load(self, place, period):
        try:
            with httpx.Client(timeout=10, transport=self.transport) as client:
                response = client.get(self.url, headers=self.headers, params={
                    'search_key': 'eq.' + search_key(place, period), 'select': 'result', 'limit': '1'})
                response.raise_for_status()
                rows = response.json()
                result = rows[0]['result'] if rows else None
                return result if isinstance(result, dict) and isinstance(result.get('items'), list) else None
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
