"""Read-only lifetime snapshots, fenced through actual ASGI publication.

These requests neither acquire nor refresh a generation lease. A database-issued
capture time limits every snapshot to thirty seconds; stale payloads are never
relabelled with a newer fence. Already delivered bytes cannot be retracted.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
import json
import os
from uuid import UUID

import anyio
from fastapi.encoders import jsonable_encoder
from pydantic import Field
from starlette.responses import JSONResponse

from .lifetime_memory_contracts import Contract, IdentityEnvelope
from .lifetime_memory_publication import (PublicationUnavailable, filter_recording_payload,
    lock_recording_publication, recording_payload)


class ReadFence(Contract):
    identity: IdentityEnvelope
    policy_epoch: int = Field(ge=1, strict=True)
    source_revision: int = Field(ge=0, strict=True)
    execution_generation: int = Field(ge=1, strict=True)
    phase_revision: int = Field(ge=0, strict=True)
    preference_revision: int = Field(ge=0, strict=True)
    draft_revision: int = Field(default=0, ge=0, strict=True)
    event_revision: int = Field(default=0, ge=0, strict=True)
    captured_at_ms: int = Field(ge=1, strict=True)


def _copy_fence(fence):
    return ReadFence.model_validate(ReadFence.model_validate(fence).model_dump(mode='json'))


@dataclass(frozen=True, init=False)
class ReadSnapshot:
    body: bytes
    fence: ReadFence

    def __init__(self, content, fence):
        object.__setattr__(self, 'fence', _copy_fence(fence))
        object.__setattr__(self, 'body', json.dumps(jsonable_encoder(content), ensure_ascii=False,
            allow_nan=False, separators=(',', ':')).encode('utf-8'))


class RecordingReadScope(Contract):
    """Authenticated scope for an existing unmapped project, not a lifetime fence."""
    owner_id: UUID
    project_id: str = Field(min_length=1)


@dataclass(frozen=True, init=False)
class RecordingReadSnapshot:
    body: bytes
    fence: RecordingReadScope

    def __init__(self, content, *, owner, project_id):
        object.__setattr__(self, 'fence', RecordingReadScope(owner_id=owner, project_id=project_id))
        object.__setattr__(self, 'body', json.dumps(jsonable_encoder(content), ensure_ascii=False,
            allow_nan=False, separators=(',', ':')).encode('utf-8'))


async def _settle(task):
    """Finish rollback/close even under repeated cancellation or an ASGI scope."""
    with anyio.CancelScope(shield=True):
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
        task.result()


class ReadPublication:
    def __init__(self, dsn, *, authenticated_owner, send_timeout=2.0, lock_timeout=5.0):
        if not dsn:
            raise PublicationUnavailable('Governed reads require a transactional database connection')
        if not 0 < send_timeout <= 5 or not 0 < lock_timeout <= 5:
            raise ValueError('read publication timeouts must be positive and at most five seconds')
        self._dsn = dsn
        self.owner = UUID(str(authenticated_owner))
        self.send_timeout = send_timeout
        self.lock_timeout = lock_timeout

    def _snapshot(self, fence):
        return _copy_fence(fence).model_dump(mode='json')

    async def _lock_snapshot(self, connection, snapshot):
        from psycopg.types.json import Jsonb
        await connection.execute('set local role authenticated')
        await connection.execute("select set_config('request.jwt.claim.sub',%s,true)", (str(self.owner),))
        await connection.execute("select set_config('lock_timeout',%s,true)", (f'{int(self.lock_timeout*1000)}ms',))
        result = await connection.execute('select public.lock_lifetime_read_publication(%s)', (Jsonb(snapshot),))
        return float((await result.fetchone())[0])

    @asynccontextmanager
    async def guard(self, fence, *, recording_ids=None):
        snapshot = self._snapshot(fence)
        if snapshot['identity']['owner_id'] != str(self.owner):
            raise PublicationUnavailable('Read publication owner mismatch')
        from psycopg import AsyncConnection, Error
        connection = None
        recordings = None
        try:
            try:
                async with asyncio.timeout(self.lock_timeout):
                    connection = await AsyncConnection.connect(self._dsn, connect_timeout=2)
                    if recording_ids is not None:
                        recordings = []
                        # Each turn has at most 20 descriptors, but an existing
                        # paginated history response can contain several turns.
                        # Lock all unique IDs in global order on this connection;
                        # keep the per-turn helper's bound and authority checks.
                        identifiers = sorted({str(UUID(value)) for value in recording_ids})
                        for offset in range(0, len(identifiers), 20):
                            recordings.extend(await lock_recording_publication(connection,
                                owner=self.owner, project_id=snapshot['identity']['project_id'],
                                recording_ids=identifiers[offset:offset+20], lock_timeout=self.lock_timeout))
                    remaining = await self._lock_snapshot(connection, snapshot)
            except Error as error:
                from .lifetime_memory_policy import PolicyUnavailable, is_policy_pending
                if is_policy_pending(error):
                    raise PolicyUnavailable() from None
                raise PublicationUnavailable('Read snapshot is unavailable or stale') from error
            allowance = self.send_timeout if remaining is None else min(self.send_timeout, remaining - .1)
            if allowance <= 0:
                raise PublicationUnavailable('Read snapshot expires too soon')
            async with asyncio.timeout(allowance):
                yield recordings
        finally:
            if connection is not None:
                # Closing rolls back; no publication transaction is committed.
                await _settle(asyncio.create_task(connection.close()))


class RecordingReadPublication(ReadPublication):
    """Existing owned legacy reads get recording locks without inventing a fence."""
    def _snapshot(self, scope):
        return {'identity': RecordingReadScope.model_validate(scope).model_dump(mode='json')}

    async def _lock_snapshot(self, connection, snapshot):
        await connection.execute('set local role authenticated')
        await connection.execute("select set_config('request.jwt.claim.sub',%s,true)", (str(self.owner),))
        # Recording reads already hold the owner's project/record authority.
        # If adoption happened since lookup, require a fresh canonical read;
        # this scope must never become a fallback for a mapped project.
        result = await connection.execute('select public.read_lifetime_project_identity(%s)',
            (snapshot['identity']['project_id'],))
        if (await result.fetchone())[0] is not None:
            raise PublicationUnavailable('Mapped recording reads require their original lifetime fence')
        return None  # No generation lease or fabricated lifetime capture time.


class ReadJSONResponse(JSONResponse):
    """Frozen JSON sent while read and recording authority locks remain held."""
    def __init__(self, snapshot, *, publisher, status_code=200, headers=None):
        if not isinstance(snapshot, (ReadSnapshot, RecordingReadSnapshot)):
            raise TypeError('ReadJSONResponse requires a ReadSnapshot')
        self.snapshot = snapshot
        self.publisher = publisher
        super().__init__(None, status_code=status_code,
            headers={'Cache-Control': 'no-store', **(headers or {})})
        self.body = snapshot.body
        self.init_headers({'Cache-Control': 'no-store', **(headers or {})})

    async def _send_response(self, send):
        from .lifetime_memory_policy import PolicyUnavailable
        started = False
        try:
            payload, containers = recording_payload(self.snapshot.body)
            identifiers = [record['id'] for container in containers for record in container['recordings']]
            options = {'recording_ids': identifiers} if identifiers else {}
            # Validate before even publishing headers, retaining the original fence.
            async with self.publisher.guard(self.snapshot.fence.model_dump(mode='json'), **options) as recordings:
                body = filter_recording_payload(self.snapshot.body, payload, containers, recordings)
                headers = [(name, str(len(body)).encode('ascii')) if name == b'content-length' else (name, value)
                           for name, value in self.raw_headers]
                # A failed await may still have handed headers to the transport.
                started = True
                await send({'type': 'http.response.start', 'status': self.status_code,
                            'headers': headers})
                await send({'type': 'http.response.body', 'body': body})
        except PolicyUnavailable:
            if started:
                raise
            # This fixed response is metadata only: never reuse snapshot bytes,
            # original headers, identifiers, or exception attributes.
            pending = JSONResponse(
                {'detail': 'Accepted conversation policy requires maintenance before private content can be used'},
                status_code=503, headers={'X-Error-Code': PolicyUnavailable.code,
                    'Retry-After': '60', 'Cache-Control': 'no-store'})
            await send({'type': 'http.response.start', 'status': pending.status_code,
                        'headers': pending.raw_headers})
            await send({'type': 'http.response.body', 'body': pending.body})

    async def __call__(self, scope, receive, send):
        if tuple(map(int, scope.get('asgi', {}).get('spec_version', '2.0').split('.'))) >= (2, 4):
            await self._send_response(send)
            return

        async def disconnected():
            while (await receive())['type'] != 'http.disconnect':
                pass
        sending = asyncio.create_task(self._send_response(send))
        listening = asyncio.create_task(disconnected())
        try:
            done, _ = await asyncio.wait((sending, listening), return_when=asyncio.FIRST_COMPLETED)
            if sending in done:
                await sending
            else:
                await listening
        finally:
            sending.cancel()
            listening.cancel()
            async def finish():
                await asyncio.gather(sending, listening, return_exceptions=True)
            await _settle(asyncio.create_task(finish()))


def find_lifetime_read_identity(service, project_id):
    """Read an existing mapping; never create identity or select a legacy project."""
    rpc = getattr(service, 'lifetime_rpc', None)
    # Guests may reload an explicit owned conversation, never choose one implicitly.
    if not callable(rpc) or (project_id is None and getattr(service, 'is_anonymous', False) is True):
        return None
    value = rpc('read_lifetime_project_identity', p_project_id=project_id)
    if value is None:
        return None
    owner = UUID(str(service.user_id))
    identity = IdentityEnvelope.model_validate(value)
    if identity.owner_id != owner or (project_id is not None and identity.project_id != project_id):
        raise PublicationUnavailable('Read identity owner or project mismatch')
    return identity


def snapshot_lifetime_read(service, project_id, reader, *, publisher=None):
    """Capture before reader(fence), freeze its result, retain that read fence.

    service must be the authenticated server-side UserStorage. Unmapped legacy
    projects retain their explicitly owner/project-scoped read adapter; a mapped
    project never falls back on capture/publication failure. No GET creates an
    identity, chooses a historical project or acquires a generation lease.
    """
    identity = find_lifetime_read_identity(service, project_id)
    absent = object()
    previous = getattr(service, 'lifetime_read_identity', absent)
    try:
        if identity is None:
            service.lifetime_read_identity = None
            result = reader(None)
            body = json.dumps(jsonable_encoder(result), ensure_ascii=False,
                allow_nan=False, separators=(',', ':')).encode('utf-8')
            if not recording_payload(body)[1]:
                return result
            if project_id is None:
                raise PublicationUnavailable('Recording reads require an explicit owned project')
            snapshot = RecordingReadSnapshot(result, owner=UUID(str(service.user_id)), project_id=project_id)
            publisher = publisher or RecordingReadPublication(os.getenv('MEMOIR_PUBLICATION_DATABASE_URL'),
                authenticated_owner=service.user_id)
            return ReadJSONResponse(snapshot, publisher=publisher)
        owner = UUID(str(service.user_id))
        project_id = identity.project_id
        publisher = publisher or ReadPublication(os.getenv('MEMOIR_PUBLICATION_DATABASE_URL'),
            authenticated_owner=owner)
        fence = _copy_fence(service.lifetime_rpc('capture_lifetime_read_fence', p_project_id=project_id))
        if fence.identity.owner_id != owner or fence.identity.project_id != project_id:
            raise PublicationUnavailable('Read snapshot owner or project mismatch')
        service.lifetime_read_identity = fence.identity.model_dump(mode='json')
        snapshot = ReadSnapshot(reader(fence), fence)
    finally:
        if previous is absent:
            if hasattr(service, 'lifetime_read_identity'):
                del service.lifetime_read_identity
        else:
            service.lifetime_read_identity = previous
    return ReadJSONResponse(snapshot, publisher=publisher)
