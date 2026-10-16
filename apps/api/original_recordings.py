"""Complete original audio ingestion. No public URLs or local persistence ledger.

Rollout and the database retention-authority hook both default to denial. The
hook must be implemented against approved identity/consent authority separately;
neither a request flag nor user-editable profile metadata is consent evidence.
"""
import asyncio
import base64
import binascii
from contextlib import contextmanager
import hashlib
import json
import logging
import time
import math
import os
from pathlib import Path
import subprocess
import tempfile
from urllib.parse import quote
from uuid import UUID, uuid4

import httpx
from fastapi import HTTPException, Response

from .speech import SpeechProviderError, SpeechUnavailable

MAX_AUDIO_BYTES = 10 * 1024 * 1024
MAX_ENCODED_AUDIO = 4 * ((MAX_AUDIO_BYTES + 2) // 3)
MAX_REQUEST_BYTES = MAX_ENCODED_AUDIO + 16384
MAX_DURATION = 300
PRIVATE_RECORDING_BUCKET = 'memoir-original-recordings'
logger = logging.getLogger(__name__)


class RecordingBodyLimit:
    """Bound encoded JSON before FastAPI buffers or decodes a request body."""
    def __init__(self, app): self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope.get('method') != 'POST' or not scope['path'].endswith('/story/transcriptions'):
            return await self.app(scope, receive, send)
        chunks, size = bytearray(), 0
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect': return
            size += len(message.get('body', b''))
            if size > MAX_REQUEST_BYTES:
                from fastapi.responses import JSONResponse
                return await JSONResponse({'detail':'Recording request exceeds the encoded byte limit'},
                    status_code=413, headers={'X-Error-Code':'AUDIO_TOO_LARGE'})(scope, receive, send)
            chunks.extend(message.get('body', b''))
            if not message.get('more_body'): break
        body = bytes(chunks)
        delivered = False
        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {'type':'http.request', 'body':body, 'more_body':False}
            return await receive()
        await self.app(scope, replay, send)


def error(status, code, message, **detail):
    return HTTPException(status, {'code':code, 'message':message, **detail},
                         headers={'X-Error-Code':code, 'Cache-Control':'private, no-store'})


def validate_original(encoded, content_type):
    if len(encoded) > MAX_ENCODED_AUDIO:
        raise error(413, 'AUDIO_TOO_LARGE', 'Recording exceeds 10 MiB')
    try:
        content = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        raise error(422, 'INVALID_AUDIO_PAYLOAD', 'Invalid base64 recording') from None
    if not content or len(content) > MAX_AUDIO_BYTES:
        raise error(413, 'AUDIO_TOO_LARGE', 'Use a complete recording between 1 byte and 10 MiB')
    mime = content_type.split(';')[0].lower().strip()
    matched = ((mime == 'audio/webm' and content.startswith(b'\x1aE\xdf\xa3'))
        or (mime in {'audio/mp4', 'audio/x-m4a'} and content[4:8] == b'ftyp')
        or (mime == 'audio/wav' and content[:4] == b'RIFF' and content[8:12] == b'WAVE')
        or (mime == 'audio/ogg' and content.startswith(b'OggS')))
    if not matched:
        raise error(415, 'UNSUPPORTED_AUDIO', 'Recording container does not match its media type')
    try:
        # Temporary decoder input is removed at scope exit. Only the private
        # object store is a durable original. No conversion replaces its bytes.
        with tempfile.TemporaryDirectory(prefix='memoir-audio-validate-') as directory:
            source, decoded = Path(directory)/'original', Path(directory)/'decoded.pcm'
            source.write_bytes(content)
            probe = subprocess.run(['ffprobe', '-v', 'error', '-protocol_whitelist', 'file,pipe',
                '-show_entries', 'stream=codec_type,codec_name:format=format_name', '-of', 'json', str(source)],
                capture_output=True, timeout=10, check=True)
            if len(probe.stdout) > 65536: raise ValueError()
            info = json.loads(probe.stdout)
            streams = info.get('streams', [])
            if len(streams) != 1 or streams[0].get('codec_type') != 'audio': raise ValueError()
            container = info['format']['format_name'].split(',')
            if not any(c in container for c in {'audio/webm':'webm', 'audio/mp4':'mp4',
                'audio/x-m4a':'mp4', 'audio/wav':'wav', 'audio/ogg':'ogg'}[mime].split(',')): raise ValueError()
            subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-xerror', '-err_detect', 'explode',
                '-protocol_whitelist', 'file,pipe', '-i', str(source), '-t', str(MAX_DURATION+1),
                '-map', '0:a:0', '-ac', '1', '-ar', '8000', '-f', 's16le', str(decoded)],
                capture_output=True, timeout=20, check=True)
            duration = decoded.stat().st_size / 16000
            if not math.isfinite(duration) or not 0 < duration <= MAX_DURATION:
                raise error(413, 'AUDIO_DURATION_EXCEEDED', 'Use a recording of at most five minutes')
        return {'content_type':'audio/mp4' if mime == 'audio/x-m4a' else mime,
            'codec':streams[0]['codec_name'], 'byte_size':len(content),
            'duration_seconds':duration, 'content_sha256':hashlib.sha256(content).hexdigest()}
    except HTTPException: raise
    except FileNotFoundError:
        raise error(503, 'AUDIO_DECODER_UNAVAILABLE', 'Recording validation is unavailable') from None
    except (subprocess.SubprocessError, ValueError, KeyError, OSError):
        raise error(422, 'INVALID_AUDIO_MEDIA', 'The complete recording could not be decoded') from None


PUBLIC_FIELDS = ('id','content_type','codec','byte_size','duration_seconds','content_sha256',
                 'storage_status','transcription_status','lifecycle','created_at')


def descriptor(record):
    result = {key:record[key] for key in PUBLIC_FIELDS}
    result['backend_saved'] = record['storage_status'] == 'ready' and record['lifecycle'] != 'deleted'
    result['content_url'] = '/api/v1/memoir/story/recordings/' + str(UUID(record['id'])) + '/content'
    return result


class OriginalContentResponse(Response):
    """Current policy stays locked through actual ASGI content publication."""
    def __init__(self, content, record, owner):
        super().__init__(content, media_type=record['content_type'], headers={
            'Cache-Control':'private, no-store','Vary':'Authorization','X-Content-Type-Options':'nosniff'})
        self.recording_id, self.owner = str(UUID(record['id'])), str(UUID(owner))

    async def __call__(self, scope, receive, send):
        from psycopg import AsyncConnection, Error
        from psycopg.types.json import Jsonb
        connection = None
        try:
            dsn = os.getenv('MEMOIR_PUBLICATION_DATABASE_URL')
            if not dsn: raise error(503,'RECORDING_DATABASE_UNAVAILABLE','Recording read guard unavailable')
            async with asyncio.timeout(5):
                connection = await AsyncConnection.connect(dsn, connect_timeout=2)
                await connection.execute("set local lock_timeout='2000ms'")
                await connection.execute('select public.recording_server_operation(%s,%s,%s,%s)',
                    (self.owner,'read',self.recording_id,Jsonb({})))
                await super().__call__(scope, receive, send)
        except Error as exc:
            if getattr(exc,'sqlstate',None)=='42501':
                raise error(404,'RECORDING_NOT_FOUND','Recording unavailable') from None
            raise error(503,'RECORDING_DATABASE_UNAVAILABLE','Recording read guard unavailable') from None
        finally:
            if connection is not None:
                import anyio
                with anyio.CancelScope(shield=True): await connection.close()


class RecordingStore:
    def __init__(self, storage):
        self.storage = storage

    def trusted(self, operation, recording_id=None, data=None):
        """Server-only attestation; never grant this RPC to authenticated JWTs.

        Reuse the existing transactional server connection, without exporting it
        or a new credential. SQL independently binds every operation to owner.
        """
        from psycopg import connect, Error
        from psycopg.types.json import Jsonb
        dsn = os.getenv('MEMOIR_PUBLICATION_DATABASE_URL')
        if not dsn: raise error(503, 'RECORDING_DATABASE_UNAVAILABLE', 'Recording persistence is unavailable')
        try:
            with connect(dsn, connect_timeout=2) as connection:
                connection.execute("set local statement_timeout='5000ms'")
                return connection.execute('select public.recording_server_operation(%s,%s,%s,%s)',
                    (self.storage.user_id, operation, recording_id, Jsonb(data or {}))).fetchone()[0]
        except Error as exc:
            code = getattr(exc, 'sqlstate', None)
            if code == '40001': raise error(409, 'RECORDING_CONFLICT', 'Recording retry identity changed') from None
            if code == '42501': raise error(403, 'RECORDING_AUTHORITY_REQUIRED', 'Approved recoverable identity and recording consent are required') from None
            raise error(503, 'RECORDING_DATABASE_UNAVAILABLE', 'Recording persistence is unavailable') from None

    def authorize(self, project_id=None):
        if os.getenv('MEMOIR_ORIGINAL_RECORDINGS', '') != '1':
            raise error(503, 'ORIGINAL_RECORDINGS_DISABLED', 'Original recording retention is disabled')
        if getattr(self.storage, 'is_anonymous', True):
            raise error(403, 'RECORDING_AUTHORITY_REQUIRED', 'Verify a recoverable identity and recording consent first')
        self.trusted('authorize', data={'project_id':project_id})

    def metadata(self, recording_id):
        try:
            result = self.trusted('read', str(UUID(recording_id)))
        except HTTPException as exc:
            if exc.status_code == 403: raise error(404, 'RECORDING_NOT_FOUND', 'Recording unavailable') from None
            raise
        if not result: raise error(404, 'RECORDING_NOT_FOUND', 'Recording unavailable')
        return result

    def content(self, record):
        if record['storage_status'] != 'ready' or record['lifecycle'] == 'deleted':
            raise error(409, 'RECORDING_NOT_READY', 'Original recording is not ready')
        content = self.storage.request('GET', '/storage/v1/object/authenticated/' + PRIVATE_RECORDING_BUCKET
            + '/' + quote(record['object_path'], safe='/')).content
        if len(content) != record['byte_size'] or hashlib.sha256(content).hexdigest() != record['content_sha256']:
            raise error(503, 'RECORDING_INTEGRITY_FAILED', 'Original recording verification failed')
        # Recheck current policy after the object read, before release/provider work.
        self.metadata(record['id'])
        return content

    def preserve(self, payload):
        self.authorize(payload.project_id)
        if payload.recording_id:
            record = self.metadata(str(payload.recording_id))
            if payload.project_id and record.get('project_id') not in (None,payload.project_id):
                raise error(409, 'RECORDING_CONFLICT', 'Recording belongs to a different project')
            return record, self.content(record)
        metadata = validate_original(payload.audio_base64, payload.mime_type)
        content = base64.b64decode(payload.audio_base64, validate=True)
        record = self.trusted('reserve', data={**metadata, 'project_id':payload.project_id,
            'upload_key':str(payload.upload_idempotency_key or uuid4())})
        if record['storage_status'] == 'ready': return record, self.content(record)
        attempt = None
        write_terminal = False
        try:
            record = self.trusted('begin_upload',record['id'])
            attempt = record['upload_attempt_id']
            try:
                self.storage.request('POST', '/storage/v1/object/' + PRIVATE_RECORDING_BUCKET + '/'
                    + quote(record['object_path'], safe='/'), content=content,
                    headers={'Content-Type':record['content_type'], 'x-upsert':'false'})
                write_terminal = True
            except httpx.HTTPStatusError as exc:
                write_terminal = exc.response.status_code < 500
                if exc.response.status_code != 409: raise
            # A duplicate object or success response is not a trusted finalization.
            observed = self.storage.request('GET', '/storage/v1/object/authenticated/' + PRIVATE_RECORDING_BUCKET
                + '/' + quote(record['object_path'], safe='/')).content
            if observed != content: raise ValueError('Original readback mismatch')
            record = self.trusted('finalize', record['id'], metadata)
            logger.info('recording_preserved recording_id=%s byte_size=%d', record['id'], record['byte_size'])
            return record, content
        except (httpx.HTTPError, ValueError, HTTPException):
            logger.warning('recording_preservation_failed recording_id=%s byte_size=%d', record['id'],record['byte_size'])
            raise error(503, 'RECORDING_PRESERVATION_FAILED', 'Original was not confirmed saved. Retry with the same upload key.',
                retryable=True, recording_id=record['id'], backend_saved=False, transcription_status='not_started') from None
        finally:
            if attempt and write_terminal:
                # A network timeout is not evidence that the upstream writer
                # stopped. Leave its durable attempt unresolved in that case.
                try:
                    current = self.trusted('finish_upload',record['id'],{'attempt_id':attempt})
                    if current['lifecycle']=='deleted': self.delete(current['id'])
                except (HTTPException,httpx.HTTPError):
                    logger.warning('recording_upload_reconciliation_pending recording_id=%s',record['id'])

    @contextmanager
    def provider_guard(self, recording_id):
        """Recheck policy under database locks before dispatching original audio."""
        from psycopg import connect, Error
        from psycopg.types.json import Jsonb
        dsn = os.getenv('MEMOIR_PUBLICATION_DATABASE_URL')
        if not dsn: raise error(503,'RECORDING_DATABASE_UNAVAILABLE','Recording provider guard unavailable')
        try:
            with connect(dsn,connect_timeout=2) as connection:
                connection.execute("set local lock_timeout='2000ms'")
                current = connection.execute('select public.recording_server_operation(%s,%s,%s,%s)',
                    (self.storage.user_id,'read',recording_id,Jsonb({}))).fetchone()[0]
                yield connection,current
        except Error as exc:
            if getattr(exc,'sqlstate',None)=='42501':
                raise error(403,'RECORDING_AUTHORITY_REQUIRED','Recording processing permission changed') from None
            raise error(503,'RECORDING_DATABASE_UNAVAILABLE','Recording provider guard unavailable') from None

    def transcribe(self, payload, speech):
        started = time.monotonic()
        record, content = self.preserve(payload)
        try:
            # The lock supplies the current persisted result, including a success
            # committed while this request was reading the original bytes.
            with self.provider_guard(record['id']) as (connection,current):
                record = current
                if record['transcription_status'] != 'succeeded':
                    transcription = speech.transcribe(content, filename='original.' +
                        {'audio/webm':'webm','audio/mp4':'m4a','audio/wav':'wav','audio/ogg':'ogg'}[record['content_type']],
                        mime_type=record['content_type'], language=payload.language, prompt=payload.prompt)
                    if not str(transcription.get('text') or '').strip(): raise SpeechProviderError('empty', retryable=True)
                    from psycopg.types.json import Jsonb
                    record = connection.execute('select public.recording_server_operation(%s,%s,%s,%s)',
                        (self.storage.user_id,'asr_succeeded',record['id'],Jsonb({'result':transcription}))).fetchone()[0]
                transcription = record['asr_result']
        except (SpeechUnavailable, SpeechProviderError):
            logger.warning('recording_transcription_failed recording_id=%s code=STT_FAILED', record['id'])
            try: self.trusted('asr_failed', record['id'])
            except HTTPException: pass
            raise error(503, 'RECORDING_TRANSCRIPTION_FAILED', 'Original saved; retry transcription using its recording ID.',
                retryable=True, recording_id=record['id'], backend_saved=True, transcription_status='failed') from None
        except HTTPException as exc:
            if exc.status_code == 403: raise
            raise error(503, 'RECORDING_TRANSCRIPTION_UNCERTAIN', 'Original saved; transcription outcome requires metadata reconciliation.',
                retryable=True, recording_id=record['id'], backend_saved=True, transcription_status='uncertain') from None
        logger.info('recording_transcription_ready recording_id=%s elapsed_ms=%d',record['id'],int((time.monotonic()-started)*1000))
        return {'text':str(transcription['text']).strip(), 'recording':descriptor(record),
            'source':{'source_kind':'transcript','transcription_method':transcription.get('provider') or 'openai',
                'transcription_model':transcription.get('model'), 'language':transcription.get('language'),
                'segments':transcription.get('segments') or []}}

    def delete(self, recording_id, *, draft_only=False):
        record = self.trusted('delete', str(UUID(recording_id)), {'draft_only':draft_only})
        try:
            self.storage.request('DELETE', '/storage/v1/object/' + PRIVATE_RECORDING_BUCKET,
                json={'prefixes':[record['object_path']]})
            # The receipt proves removal only for writers already stopped
            # before this DELETE began, regardless of HTTP response timing.
            finished = self.trusted('cleanup_complete', record['id'],
                {'write_revision':record['write_revision']})
            return {'id':record['id'], 'deleted':True, 'cleanup_status':finished['cleanup_status']}
        except httpx.HTTPError:
            return {'id':record['id'], 'deleted':True, 'cleanup_status':'pending'}


    def cancel_upload(self, upload_key):
        result = self.trusted('cancel_upload',data={'upload_key':str(UUID(upload_key))})
        if result.get('recording_id') and not result.get('already_attached'):
            deleted = self.delete(result['recording_id'],draft_only=True)
            result['cleanup_status'] = deleted['cleanup_status']
        return result
