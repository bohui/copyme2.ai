"""Opt-in transaction held through actual transport send, never queue insertion.

Requires a server-configured transactional PostgreSQL connection. PostgREST RPC
alone cannot implement this boundary. No connection is opened on import.
"""
import asyncio
import json
from contextlib import asynccontextmanager
from uuid import UUID

from .lifetime_memory_contracts import ExecutionFence


class PublicationUnavailable(RuntimeError):
    pass


class PublicationDatabaseUnavailable(PublicationUnavailable):
    """A database guard failed before any response bytes were sent."""


class TransactionalPublication:
    lock_function = 'lock_lifetime_publication'
    def __init__(self, dsn, *, authenticated_owner, send_timeout=2.0, lock_timeout=5.0):
        if not dsn:
            raise PublicationUnavailable('Governed publication requires a transactional database connection')
        if not 0 < send_timeout <= 5 or not 0 < lock_timeout <= 5:
            raise ValueError('publication timeouts must be positive and at most five seconds')
        self._dsn = dsn
        self.owner = UUID(str(authenticated_owner))
        self.send_timeout = send_timeout
        self.lock_timeout = lock_timeout

    async def _lock_activation(self, connection):
        pass  # Saved publication and replay do not require new model activation.

    @asynccontextmanager
    async def guard(self, fence, *, recording_ids=None):
        from psycopg import AsyncConnection, Error
        from psycopg.types.json import Jsonb

        # Validate/copy before any connection. The verified authentication result,
        # not a browser field or queued event, supplies self.owner.
        snapshot = ExecutionFence.model_validate(fence).model_dump(mode='json')
        if snapshot['identity']['owner_id'] != str(self.owner):
            raise PublicationUnavailable('Publication owner mismatch')
        connection = None
        recordings = None
        try:
            activation_pending = False
            try:
                async with asyncio.timeout(self.lock_timeout):
                    connection = await AsyncConnection.connect(self._dsn, connect_timeout=2)
                    if recording_ids is not None:
                        from .original_recordings import descriptor
                        if len(recording_ids) > 20:
                            raise PublicationUnavailable('Recording publication limit exceeded')
                        await connection.execute("select set_config('lock_timeout',%s,true)",
                            (f'{int(self.lock_timeout*1000)}ms',))
                        # Acquire owner authority before project/record locks,
                        # matching withdrawal and original-byte operations.
                        await connection.execute('select public.recording_server_operation(%s,%s,null,%s)',
                            (str(self.owner),'consent_status',Jsonb({})))
                        identifiers=[str(UUID(value)) for value in recording_ids]
                        authorized={}
                        # Concurrent sends may reference the same clips in
                        # different presentation orders; lock them consistently.
                        for recording_id in sorted(set(identifiers)):
                            try:
                                async with connection.transaction():
                                    result=await connection.execute('select public.recording_server_operation(%s,%s,%s,%s)',
                                        (str(self.owner),'read',recording_id,Jsonb({})))
                                    record=(await result.fetchone())[0]
                                    if record['project_id']==snapshot['identity']['project_id'] and record['storage_status']=='ready':
                                        authorized[recording_id]=descriptor(record)
                            except Error as error:
                                if getattr(error,'sqlstate',None)!='42501':raise
                        recordings=[authorized[value] for value in identifiers if value in authorized]
                    # Apply transaction-local settings in one database round trip.
                    await connection.execute("select set_config('role','authenticated',true),"
                        "set_config('request.jwt.claim.sub',%s,true),set_config('lock_timeout',%s,true)",
                        (str(self.owner), f'{int(self.lock_timeout*1000)}ms'))
                    lease_started = asyncio.get_running_loop().time()
                    result = await connection.execute('select public.' + self.lock_function + '(%s)', (Jsonb(snapshot),))
                    remaining = float((await result.fetchone())[0])
                    lease_deadline = lease_started + remaining
                    activation_pending = True
                    await self._lock_activation(connection)
                    activation_pending = False
            except Error as error:
                from .lifetime_memory_policy import PolicyUnavailable, is_policy_pending
                if is_policy_pending(error):
                    raise PolicyUnavailable() from None
                if connection is None:
                    raise PublicationDatabaseUnavailable('Publication database connection unavailable') from error
                raise
            except TimeoutError:
                if activation_pending:
                    from .lifetime_memory_activation import CanonicalActivationUnavailable
                    raise CanonicalActivationUnavailable() from None
                raise PublicationDatabaseUnavailable('Publication database guard timed out') from None
            allowance = min(self.send_timeout, lease_deadline - asyncio.get_running_loop().time() - 0.1)
            if allowance <= 0:
                raise PublicationUnavailable('Publication lease expires too soon')
            # The caller awaits ASGI send (or yields from the response body)
            # inside this scope. Do not await producer work or another DB RPC.
            async with asyncio.timeout(allowance):
                yield recordings
        finally:
            if connection is not None:
                # Closing rolls back the read-only publication transaction and
                # releases locks even if ASGI disconnect cancellation repeats.
                closing = asyncio.create_task(connection.close())
                while not closing.done():
                    try:
                        await asyncio.shield(closing)
                    except asyncio.CancelledError:
                        continue
                closing.result()


class ProviderPublication(TransactionalPublication):
    """Only actual model request admission, never saved-output publication."""
    async def _lock_activation(self, connection):
        from .lifetime_memory_activation import require_provider_activation
        await require_provider_activation(connection)


class DraftPublication(TransactionalPublication):
    """Current-turn draft only; final publication still requires completed review."""
    lock_function = 'lock_lifetime_draft_reply'


class DraftProviderPublication(ProviderPublication):
    lock_function = 'lock_lifetime_draft_reply'


async def send_governed(send, message, *, publisher, fence):
    """Guard actual ASGI send completion. Snapshot belongs to this exact body.

    Use for non-streamed JSON and dequeued stream bodies, not their producers.
    Already-delivered or network-buffered text cannot be recalled on withdrawal.
    """
    snapshot = ExecutionFence.model_validate(fence).model_dump(mode='json')
    event = None
    data = None
    if message.get('more_body') and b'"recordings"' in message.get('body',b''):
        event=json.loads(message['body'])
        if event.get('type') in {'source_accepted','result'} and isinstance(event.get('data'),dict):
            data=event['data']
    records=data.get('recordings') if data is not None else None
    options={'recording_ids':[record['id'] for record in records]} if records else {}
    async with publisher.guard(snapshot,**options) as current_recordings:
        if records:
            data['recordings']=current_recordings
            message={**message,'body':json.dumps(event,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode()+b'\n'}
        await send(message)
    return message


class GovernedRequestBody:
    """One HTTP body guarded until the transport has consumed/sent its bytes.

    httpcore requests the next chunk after completing the previous socket write.
    The guard is released at that boundary, before waiting for response headers or
    generation. A correction after release treats this request as already admitted.
    """
    def __init__(self, content, *, publisher, fence):
        from copy import deepcopy
        self.content=bytes(content);self.publisher=publisher
        self.fence=ExecutionFence.model_validate(deepcopy(fence)).model_dump(mode='json')
        self._iterator=None

    async def _chunks(self):
        async with self.publisher.guard(self.fence):
            yield self.content

    def __aiter__(self):
        if self._iterator is not None:raise RuntimeError('Governed request bodies cannot be replayed')
        self._iterator=self._chunks()
        return self._iterator

    async def aclose(self):
        if self._iterator is not None:await self._iterator.aclose()
