"""Controlled-driver turn delivery through the production SQL/ASGI boundary.

The caller owns an authenticated UserStorage and its disposable authority
configuration. No identity, lease, publication guard or model admission is
substituted here. Public response bytes are consumed before success is returned;
redacted evaluation evidence remains a caller-private sidecar.
"""
import asyncio
import inspect
import json

from fastapi import HTTPException

from apps.api.agent_storage import UserStorage
from apps.api.lifetime_memory_runtime import lifetime_http_turn
from apps.api.trajectory_evaluation import TrajectoryRecorder


class CanonicalTurnFailed(RuntimeError):
    def __init__(self, trajectory, *, status_code=None, error_code=None):
        super().__init__('Canonical evaluation turn was not delivered')
        self.trajectory = trajectory
        self.status_code = status_code
        self.error_code = error_code


async def canonical_turn(runtime, storage, text, *, options, evaluation=None, on_event=None,
                         trajectory=None, evaluation_context=None):
    if not isinstance(storage, UserStorage):
        raise TypeError('Canonical evaluation requires authenticated UserStorage')
    recorder = trajectory or TrajectoryRecorder(evaluation)
    recorder.set_context(**{**(evaluation_context or {}), 'execution_contract':'canonical'})
    recorder.record('application','canonical.turn.started',input={'project_id':options.get('project_id')})
    events, status = [], None
    async def receive():
        return {'type':'http.request','body':b'','more_body':False}
    async def send(message):
        nonlocal status
        if message['type']=='http.response.start':
            status = message['status']
            return
        for line in message.get('body',b'').splitlines():
            if not line:
                continue
            event = json.loads(line)
            events.append(event)
            recorder.record('application','stream.'+event.get('type','unknown'),output=event)
            if on_event is not None:
                returned = on_event(event)
                if inspect.isawaitable(returned):
                    await returned
    try:
        response = await lifetime_http_turn(runtime,storage,text,accept='application/x-ndjson',
            options={**options,'evaluation':evaluation,'trajectory':recorder},close_storage=False)
        await response({'type':'http','asgi':{'version':'3.0','spec_version':'2.4'}},receive,send)
    except HTTPException as error:
        recorder.finish(status='failed',stop_reason='canonical.http.rejected',error={'status_code':error.status_code})
        raise CanonicalTurnFailed(recorder.payload(),status_code=error.status_code,
            error_code=(error.headers or {}).get('X-Error-Code')) from None
    except BaseException as error:
        recorder.finish(status='failed',stop_reason='canonical.delivery.interrupted',
            error={'error_type':type(error).__name__})
        if isinstance(error, asyncio.CancelledError):
            error.trajectory = recorder.payload()
            raise
        if not isinstance(error, Exception):
            raise
        raise CanonicalTurnFailed(recorder.payload(), status_code=status) from None
    terminal = next((event.get('data') for event in reversed(events) if event.get('type')=='result'),None)
    failure = next((event for event in events if event.get('type')=='error'),None)
    if status != 200 or failure is not None or not isinstance(terminal,dict):
        recorder.finish(status='failed',stop_reason='canonical.delivery.failed',error={'status_code':status,
            'code':failure.get('code') if failure else None})
        raise CanonicalTurnFailed(recorder.payload(),status_code=status,error_code=failure.get('code') if failure else None)
    recorder.finish(terminal,status='completed',stop_reason='canonical.delivery.completed')
    return {**terminal,'trajectory':recorder.payload()}


async def canonical_read(storage, project_id, reader):
    """Consume the normal frozen read response under its actual SQL guard."""
    from apps.api.lifetime_memory_reads import snapshot_lifetime_read
    def mapped_reader(fence):
        if fence is None:
            raise RuntimeError('Canonical evaluation read requires a mapped identity')
        return reader(fence)
    response = await asyncio.to_thread(snapshot_lifetime_read, storage, project_id,
        mapped_reader)
    if not callable(response):
        raise RuntimeError('Canonical evaluation read requires a mapped identity')
    chunks, status = [], None
    async def receive():
        return {'type': 'http.request', 'body': b'', 'more_body': False}
    async def send(message):
        nonlocal status
        if message['type'] == 'http.response.start':
            status = message['status']
        else:
            chunks.append(message.get('body', b''))
    await response({'type': 'http', 'asgi': {'version': '3.0', 'spec_version': '2.4'}}, receive, send)
    if status != 200:
        raise RuntimeError('Canonical evaluation read was not delivered')
    return json.loads(b''.join(chunks))
