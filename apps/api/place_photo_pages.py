"""Bounded, short-lived public search snapshots for stable gallery pagination."""
from collections import OrderedDict
from copy import deepcopy
import secrets
from threading import RLock
import time

from fastapi import HTTPException

from .place_photos import MAX_RESULTS, search_place_photos

MAX_SNAPSHOTS = 32
SNAPSHOT_TTL = 15 * 60


class PhotoPages:
    def __init__(self):
        self.snapshots = OrderedDict()
        self.lock = RLock()

    def page(self, owner: str, place: str, period: str, cursor: str | None) -> dict:
        query = (owner, place.strip().casefold(), period.strip().casefold())
        with self.lock:
            now = time.monotonic()
            for token in list(self.snapshots):
                if self.snapshots[token]['expires'] <= now:
                    del self.snapshots[token]
            if cursor:
                try:
                    token, raw_offset = cursor.rsplit(':', 1)
                    offset = int(raw_offset)
                except (ValueError, TypeError):
                    raise HTTPException(status_code=422, detail='Invalid photo cursor') from None
                snapshot = self.snapshots.get(token)
                if snapshot is None:
                    raise HTTPException(status_code=410, detail='Photo search expired; start again')
                if snapshot['query'] != query or offset < 0 or offset > len(snapshot['items']):
                    raise HTTPException(status_code=422, detail='Photo cursor does not match this search')
            else:
                # A rerender or duplicate request reuses the same public search.
                match = next(((key, value) for key, value in reversed(self.snapshots.items())
                              if value['query'] == query), None)
                token, snapshot = match if match else (None, None)
                offset = 0
        if snapshot is None:
            # Slow browser/network discovery never holds the cache lock.
            items = search_place_photos(place, period, limit=None)
            snapshot = {'query': query, 'items': items, 'expires': time.monotonic() + SNAPSHOT_TTL}
            with self.lock:
                token = secrets.token_urlsafe(18)
                self.snapshots[token] = snapshot
                while len(self.snapshots) > MAX_SNAPSHOTS:
                    self.snapshots.popitem(last=False)
        items = snapshot['items'][offset:offset + MAX_RESULTS]
        next_offset = offset + len(items)
        return {
            'items': deepcopy(items), 'count': len(snapshot['items']), 'target_count': MAX_RESULTS,
            'shortfall': max(0, MAX_RESULTS - len(snapshot['items'])),
            'status': 'READY' if len(items) >= MAX_RESULTS else 'PARTIAL' if items else 'NO_MATCH',
            'next_cursor': f'{token}:{next_offset}' if next_offset < len(snapshot['items']) else None,
        }
