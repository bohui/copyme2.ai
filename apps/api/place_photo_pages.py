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

from .place_photos import ANY_PHOTO_DATE, MAX_RESULTS, PhotoResearchUnavailable, filter_place_photos, search_place_photos

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

    def _search(self, job, place, period, *, refresh=False):
        def save(complete):
            if not self.repository:
                return
            # Serialize this job's writes, taking the newest snapshot only
            # after acquiring its persistence lock. Network waits never hold
            # the shared search lock or delay another project's delivery.
            with job['persistence_lock']:
                with self.lock:
                    result = ({'items': deepcopy(job['items']), 'complete': complete,
                               'failures': deepcopy(job['failures']), 'time_relaxed': job['time_relaxed']}
                              if job['items'] or not job['error'] else None)
                if result is not None:
                    self.repository.save(place, period, result)
        def publish(items):
            with self.lock:
                # Arrival order stays stable even when later catalogues finish.
                job['items'] = filter_place_photos(job['items'] + items,
                    ANY_PHOTO_DATE if job['time_relaxed'] else period)[:150]
                job['revision'] += 1
            if items:
                save(False)
        cached_complete = False
        try:
            cached = self.repository.load(place, period) if self.repository and not refresh else None
            if cached is not None:
                with self.lock:
                    job.update(time_relaxed=bool(cached.get('time_relaxed')),
                               items=filter_place_photos(cached['items'], ANY_PHOTO_DATE
                                   if cached.get('time_relaxed') else period),
                               failures=cached.get('failures', []))
                    job['revision'] += 1
                cached_complete = bool(cached.get('complete'))
                if cached_complete and (job['items'] or job['time_relaxed']):
                    return
            if not cached_complete:
                publish(search_place_photos(place, ANY_PHOTO_DATE if job['time_relaxed'] else period,
                                           limit=None, on_items=publish))
            # Removing GPS accepts every source-backed locality match in the
            # dated pool. Only an empty dated pool needs another discovery pass.
            if not job['items']:
                cached_complete = False
                job['time_relaxed'] = True
                publish(search_place_photos(place, ANY_PHOTO_DATE, limit=None, on_items=publish))
        except Exception as error:
            with self.lock:
                job['error'] = True
                job['failures'] = error.failures if isinstance(error, PhotoResearchUnavailable) else []
        finally:
            if not cached_complete:
                save(not job['error'])
            with self.lock:
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
                        or offset > len(self._matches(snapshot['job'], snapshot))):
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
                       'time_relaxed': False,
                       'expires': float('inf'), 'persistence_lock': RLock()}
                self.searches[search_query] = job
                self.pool.submit(self._search, job, place, period, refresh=refresh)
            token = secrets.token_urlsafe(18)
            self.snapshots[token] = {'owner': owner, 'query': query, 'job': job,
                                     'center': center, 'period': period, 'place': place,
                                     'expires': now + SNAPSHOT_TTL}
            while len(self.snapshots) > MAX_SNAPSHOTS:
                self.snapshots.popitem(last=False)
            return token, job, 0, self.snapshots[token]

    def _matches(self, job, snapshot):
        period, center = snapshot['period'], snapshot['center']
        matches = filter_place_photos(job['items'], period, center)
        fallback = 'none'
        # Wait for all strict candidates before exposing a relaxed tier. This
        # keeps progressive batches and cursor offsets on one stable tier.
        if not matches and job['done'].is_set():
            matches = filter_place_photos(job['items'], period)
            fallback = 'gps'
            if not matches and job['time_relaxed']:
                matches = filter_place_photos(job['items'], ANY_PHOTO_DATE)
                fallback = 'gps_time'
        return [{**item, 'search_fallback': fallback, 'requested_period': period,
                 'search_place': snapshot['place'],
                 **({'period_match': 'any_time'} if fallback == 'gps_time' else {})}
                for item in matches]

    def _page(self, token, job, offset, snapshot):
        with self.lock:
            matches = self._matches(job, snapshot)
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
