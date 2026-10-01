"""Shared public research with incremental delivery and project-bound cursors."""
import asyncio
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import secrets
from threading import Event, RLock
import time

from fastapi import HTTPException

from .place_photos import MAX_RESULTS, _deduplicate, search_place_photos

MAX_SNAPSHOTS = 32
MAX_ACTIVE_SEARCHES = 4
SNAPSHOT_TTL = 15 * 60


class PhotoPages:
    def __init__(self):
        self.snapshots = OrderedDict()
        self.searches = OrderedDict()
        self.lock = RLock()
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='photo-search')

    def close(self):
        self.pool.shutdown(wait=False, cancel_futures=True)

    def _search(self, job, place, period):
        def publish(items):
            with self.lock:
                # Arrival order stays stable even when later catalogues finish.
                job['items'] = _deduplicate(job['items'] + items)[:150]
                job['revision'] += 1
        try:
            publish(search_place_photos(place, period, limit=None, on_items=publish))
        except Exception:
            with self.lock:
                job['error'] = True
        finally:
            with self.lock:
                job['revision'] += 1
                job['done'].set()
                job['expires'] = time.monotonic() + (0 if job['error'] and not job['items'] else SNAPSHOT_TTL)

    def _snapshot(self, owner, place, period, cursor):
        query = (place.strip().casefold(), period.strip().casefold())
        with self.lock:
            now = time.monotonic()
            for entries in (self.snapshots, self.searches):
                for key in list(entries):
                    entry = entries[key]
                    if min(entry['expires'], entry.get('job', entry)['expires']) <= now:
                        del entries[key]
            if cursor:
                try:
                    token, raw_offset = cursor.rsplit(':', 1)
                    offset = int(raw_offset)
                except (ValueError, TypeError):
                    raise HTTPException(status_code=422, detail='Invalid photo cursor') from None
                snapshot = self.snapshots.get(token)
                if snapshot is None:
                    raise HTTPException(status_code=410, detail='Photo search expired; start again')
                if (snapshot['query'] != query or snapshot['owner'] != owner or offset < 0
                        or offset > len(snapshot['job']['items'])):
                    raise HTTPException(status_code=422, detail='Photo cursor does not match this search')
                return token, snapshot['job'], offset
            match = next(((token, snapshot) for token, snapshot in reversed(self.snapshots.items())
                          if snapshot['query'] == query and snapshot['owner'] == owner), None)
            if match:
                return match[0], match[1]['job'], 0
            job = self.searches.get(query)
            if job is None:
                if sum(not value['done'].is_set() for value in self.searches.values()) >= MAX_ACTIVE_SEARCHES:
                    raise HTTPException(status_code=503, detail='Photo research is busy; retry shortly')
                # Do not start unbounded queued browser work or evict active jobs.
                if len(self.searches) >= MAX_SNAPSHOTS:
                    completed = next((key for key, value in self.searches.items() if value['done'].is_set()), None)
                    if completed is None:
                        raise HTTPException(status_code=503, detail='Photo research is busy; retry shortly')
                    del self.searches[completed]
                job = {'items': [], 'done': Event(), 'error': False, 'revision': 0,
                       'expires': float('inf')}
                self.searches[query] = job
                self.pool.submit(self._search, job, place, period)
            token = secrets.token_urlsafe(18)
            self.snapshots[token] = {'owner': owner, 'query': query, 'job': job,
                                     'expires': now + SNAPSHOT_TTL}
            while len(self.snapshots) > MAX_SNAPSHOTS:
                self.snapshots.popitem(last=False)
            return token, job, 0

    def _page(self, token, job, offset):
        with self.lock:
            items = deepcopy(job['items'][offset:offset + MAX_RESULTS])
            count = len(job['items'])
            searching = not job['done'].is_set()
            status = ('PARTIAL' if items else 'SEARCHING') if searching else (
                'READY' if len(items) >= MAX_RESULTS else 'PARTIAL' if items else
                'UNAVAILABLE' if job['error'] else 'NO_MATCH')
            return {'items': items, 'count': count, 'target_count': MAX_RESULTS,
                    'shortfall': max(0, MAX_RESULTS - count), 'status': status,
                    'searching': searching,
                    'next_cursor': f'{token}:{offset + len(items)}'
                    if not searching and offset + len(items) < count else None}

    def page(self, owner: str, place: str, period: str, cursor: str | None) -> dict:
        token, job, offset = self._snapshot(owner, place, period, cursor)
        job['done'].wait()
        return self._page(token, job, offset)

    async def stream(self, owner: str, place: str, period: str, cursor: str | None, *, snapshot=None):
        token, job, offset = snapshot or self._snapshot(owner, place, period, cursor)
        # Flush a response immediately; photos follow as originals are verified.
        if not job['done'].is_set():
            yield json.dumps({'items': [], 'status': 'SEARCHING', 'searching': True}) + '\n'
        previous = -1 if job['done'].is_set() else 0
        heartbeat = time.monotonic()
        while True:
            with self.lock:
                revision = job['revision']
            if revision != previous or time.monotonic() - heartbeat >= 10:
                result = self._page(token, job, offset)
                yield json.dumps(result, ensure_ascii=False) + '\n'
                previous, heartbeat = revision, time.monotonic()
                if not result['searching']:
                    break
            await asyncio.sleep(0.1)
