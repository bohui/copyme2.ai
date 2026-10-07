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

from .place_photos import MAX_RESULTS, PhotoResearchUnavailable, filter_place_photos, search_place_photos

MAX_SNAPSHOTS = 32
MAX_ACTIVE_SEARCHES = 4
SNAPSHOT_TTL = 15 * 60


class PhotoPages:
    def __init__(self, *, repository=None):
        self.repository = repository
        self.snapshots = OrderedDict()
        self.searches = OrderedDict()
        self.lock = RLock()
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='photo-search')

    def close(self):
        self.pool.shutdown(wait=False, cancel_futures=True)

    def _search(self, job, place, period):
        def save(complete):
            if self.repository and (job['items'] or not job['error']):
                self.repository.save(place, period, {'items': deepcopy(job['items']),
                    'complete': complete, 'failures': deepcopy(job['failures'])})
        def publish(items):
            with self.lock:
                # Arrival order stays stable even when later catalogues finish.
                job['items'] = filter_place_photos(job['items'] + items, period)[:150]
                job['revision'] += 1
                if items:
                    save(False)
        try:
            publish(search_place_photos(place, period, limit=None, on_items=publish))
        except Exception as error:
            with self.lock:
                job['error'] = True
                job['failures'] = error.failures if isinstance(error, PhotoResearchUnavailable) else []
        finally:
            with self.lock:
                save(True)
                job['revision'] += 1
                job['done'].set()
                job['expires'] = time.monotonic() + (0 if job['error'] and not job['items'] else SNAPSHOT_TTL)

    def _snapshot(self, owner, place, period, cursor, *, refresh=False, latitude=None, longitude=None):
        if (latitude is None) != (longitude is None):
            raise HTTPException(status_code=422, detail='Both photo search coordinates are required')
        from .place_photos import _coordinates
        center = _coordinates({'latitude': latitude, 'longitude': longitude})
        if latitude is not None and center is None:
            raise HTTPException(status_code=422, detail='Invalid photo search coordinates')
        search_query = (place.strip().casefold(), period.strip().casefold())
        query = (*search_query, latitude, longitude)
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
                        or offset > len(filter_place_photos(snapshot['job']['items'], period, center))):
                    raise HTTPException(status_code=422, detail='Photo cursor does not match this search')
                return token, snapshot['job'], offset, snapshot
            match = next(((token, snapshot) for token, snapshot in reversed(self.snapshots.items())
                          if snapshot['query'] == query and snapshot['owner'] == owner), None)
            if match and not refresh:
                return match[0], match[1]['job'], 0, match[1]
            job = self.searches.get(search_query)
            if refresh and job is not None and job['done'].is_set():
                del self.searches[search_query]
                job = None
            if job is None:
                if sum(not value['done'].is_set() for value in self.searches.values()) >= MAX_ACTIVE_SEARCHES:
                    raise HTTPException(status_code=503, detail='Photo research is busy; retry shortly')
                # Do not start unbounded queued browser work or evict active jobs.
                if len(self.searches) >= MAX_SNAPSHOTS:
                    completed = next((key for key, value in self.searches.items() if value['done'].is_set()), None)
                    if completed is None:
                        raise HTTPException(status_code=503, detail='Photo research is busy; retry shortly')
                    del self.searches[completed]
                job = {'items': [], 'done': Event(), 'error': False, 'failures': [], 'revision': 0,
                       'expires': float('inf')}
                cached = self.repository.load(place, period) if self.repository and not refresh else None
                if cached is not None:
                    items = filter_place_photos(cached['items'], period)
                    if items or (cached.get('complete') and not cached['items']):
                        job.update(items=items, failures=cached.get('failures', []),
                                   expires=now + SNAPSHOT_TTL)
                        job['done'].set()
                self.searches[search_query] = job
                if not job['done'].is_set():
                    self.pool.submit(self._search, job, place, period)
            token = secrets.token_urlsafe(18)
            self.snapshots[token] = {'owner': owner, 'query': query, 'job': job,
                                     'center': center, 'period': period,
                                     'expires': now + SNAPSHOT_TTL}
            while len(self.snapshots) > MAX_SNAPSHOTS:
                self.snapshots.popitem(last=False)
            return token, job, 0, self.snapshots[token]

    def _page(self, token, job, offset, snapshot):
        with self.lock:
            matches = filter_place_photos(job['items'], snapshot['period'], snapshot['center'])
            items = deepcopy(matches[offset:offset + MAX_RESULTS])
            count = len(matches)
            searching = not job['done'].is_set()
            status = ('PARTIAL' if items else 'SEARCHING') if searching else (
                'READY' if len(items) >= MAX_RESULTS else 'PARTIAL' if items else
                'UNAVAILABLE' if job['error'] else 'NO_MATCH')
            return {'items': items, 'count': count, 'target_count': MAX_RESULTS,
                    'search_center': deepcopy(snapshot['center']),
                    'shortfall': max(0, MAX_RESULTS - count), 'status': status,
                    'searching': searching,
                    'failures': deepcopy(job.get('failures', [])),
                    'next_cursor': f'{token}:{offset + len(items)}'
                    if not searching and offset + len(items) < count else None}

    def page(self, owner: str, place: str, period: str, cursor: str | None, *, refresh=False,
             latitude=None, longitude=None) -> dict:
        token, job, offset, snapshot = self._snapshot(owner, place, period, cursor, refresh=refresh,
                                           latitude=latitude, longitude=longitude)
        job['done'].wait()
        return self._page(token, job, offset, snapshot)

    async def stream(self, owner: str, place: str, period: str, cursor: str | None, *, snapshot=None,
                     latitude=None, longitude=None):
        token, job, offset, scope = snapshot or self._snapshot(owner, place, period, cursor,
                                                       latitude=latitude, longitude=longitude)
        # Flush a response immediately; photos follow as originals are verified.
        if not job['done'].is_set():
            yield json.dumps({'items': [], 'status': 'SEARCHING', 'searching': True}) + '\n'
        previous = -1 if job['done'].is_set() else 0
        heartbeat = time.monotonic()
        while True:
            with self.lock:
                revision = job['revision']
            if revision != previous or time.monotonic() - heartbeat >= 10:
                result = self._page(token, job, offset, scope)
                yield json.dumps(result, ensure_ascii=False) + '\n'
                previous, heartbeat = revision, time.monotonic()
                if not result['searching']:
                    break
            await asyncio.sleep(0.1)
