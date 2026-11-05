"""Private checkpoints for resumable Codex homes, outside the model sandbox."""
from io import BytesIO
import hashlib
import json
import logging
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
from uuid import UUID
from zipfile import BadZipFile, ZIP_DEFLATED, ZipFile

import httpx

from .codex_artifacts import ARTIFACT_ROOTS, iter_artifacts


BUCKET = 'memory-spark'
MAX_BYTES = 50 * 1024 * 1024
MAX_FILES = 4096
logger = logging.getLogger(__name__)


class HomeCheckpointUnavailable(RuntimeError):
    """Keep the accepted source retryable until its runtime upload is verified."""


def _allowed(path):
    parts = PurePosixPath(path).parts
    return (bool(parts) and path == '/'.join(parts) and '\\' not in path
        and all(not part.startswith('.') for part in parts)
        and ((len(parts) > 1 and parts[0] in ARTIFACT_ROOTS)
            or (len(parts) == 1 and (path == 'session_index.jsonl'
                or re.fullmatch(r'state_\d+\.sqlite(?:-wal)?', path) is not None))))


def _home_files(home):
    yield from iter_artifacts(home, strict=True)
    home_fd = os.open(home, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for name in sorted(os.listdir(home_fd)):
            if '/' in name or not _allowed(name):
                continue
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=home_fd)
            with os.fdopen(fd, 'rb') as source:
                info = os.fstat(source.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_BYTES:
                    raise ValueError('Unsafe or oversized Codex state file')
                content = source.read(MAX_BYTES + 1)
            if len(content) > MAX_BYTES:
                raise ValueError('Oversized Codex state file')
            yield name, content
    finally:
        os.close(home_fd)


def _identity(session):
    return dict(owner_id=str(UUID(str(session.packet.identity.owner_id))),
        conversation_id=str(UUID(str(session.packet.identity.conversation_id))), scope=session.scope)


def _pack(session, state):
    # The app-server must already be stopped: SQLite and any surviving WAL form
    # one snapshot. Config, authentication, logs and shared UID maps are excluded.
    buffer = BytesIO()
    manifest = json.dumps(dict(format=1, **_identity(session), state=state),
        ensure_ascii=False, separators=(',', ':')).encode()
    if len(manifest) > 512_000:
        raise ValueError('Oversized Codex checkpoint manifest')
    total = len(manifest)
    with ZipFile(buffer, 'w', compression=ZIP_DEFLATED) as archive:
        archive.writestr('manifest.json', manifest)
        for index, (path, content) in enumerate(_home_files(session.home), 1):
            total += len(content)
            if index > MAX_FILES or total > MAX_BYTES:
                raise ValueError('Codex checkpoint limit exceeded')
            archive.writestr('home/' + path, content)
    content = buffer.getvalue()
    if len(content) > MAX_BYTES:
        raise ValueError('Codex checkpoint limit exceeded')
    return content


def _unpack(content, session):
    if len(content) > MAX_BYTES:
        raise ValueError('Codex checkpoint limit exceeded')
    files = {}
    total = 0
    try:
        with ZipFile(BytesIO(content)) as archive:
            entries = archive.infolist()
            if len(entries) > MAX_FILES + 1 or len({entry.filename for entry in entries}) != len(entries):
                raise ValueError('Invalid Codex checkpoint entries')
            for entry in entries:
                path = entry.filename
                mode = entry.external_attr >> 16
                if (entry.is_dir() or stat.S_ISLNK(mode) or entry.flag_bits & 1
                        or entry.file_size > MAX_BYTES
                        or (path != 'manifest.json' and (not path.startswith('home/') or not _allowed(path[5:])))):
                    raise ValueError('Invalid Codex checkpoint path or file')
                total += entry.file_size
                if total > MAX_BYTES or (path == 'manifest.json' and entry.file_size > 512_000):
                    raise ValueError('Codex checkpoint limit exceeded')
                files[path] = archive.read(entry)
    except (BadZipFile, KeyError, RuntimeError) as error:
        raise ValueError('Invalid Codex checkpoint archive') from error
    manifest = json.loads(files.pop('manifest.json', b'null'))
    if (not isinstance(manifest, dict) or manifest.get('format') != 1
            or any(manifest.get(key) != value for key, value in _identity(session).items())
            or not isinstance(manifest.get('state'), dict)
            or not isinstance(manifest['state'].get('sources'), dict)):
        raise ValueError('Codex checkpoint identity mismatch')
    return manifest['state'], {path[5:]: value for path, value in files.items()}


class CodexHomeStore:
    def __init__(self, url, key, *, transport=None):
        if not url or not key:
            raise ValueError('Codex home storage requires Supabase server credentials')
        self.url = url.rstrip('/')
        self.headers = {'apikey': key, 'Authorization': 'Bearer ' + key}
        self.transport = transport

    @classmethod
    def configured(cls):
        if os.getenv('MEMOIR_CODEX_HOME_BACKUPS', '') != '1':
            return None
        return cls(os.getenv('SUPABASE_URL'),
            os.getenv('SUPABASE_SECRET_KEY') or os.getenv('SUPABASE_SERVICE_ROLE_KEY'))

    def _path(self, session, sequence, digest):
        identity = _identity(session)
        if (re.fullmatch('[a-f0-9]{64}', identity['scope']) is None
                or type(sequence) is not int or sequence < 1
                or not isinstance(digest, str) or re.fullmatch('[a-f0-9]{64}', digest) is None):
            raise ValueError('Invalid Codex checkpoint scope')
        return (identity['owner_id'] + '/sandbox/' + identity['conversation_id'] + '/'
            + identity['scope'] + '/' + str(sequence) + '-' + digest + '/checkpoint.zip')

    async def _download(self, client, path):
        async with client.stream('GET', self.url + '/storage/v1/object/authenticated/' + BUCKET + '/' + path) as response:
            if response.status_code == 404:
                return None
            if response.status_code != 400:
                response.raise_for_status()
            content = bytearray()
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > MAX_BYTES:
                    raise ValueError('Codex checkpoint limit exceeded')
            if response.status_code == 400:
                # Supabase's S3 compatibility layer wraps a missing object in
                # HTTP 400; missing buckets and authorization errors must fail.
                try:
                    error = json.loads(content)
                except ValueError:
                    error = {}
                if isinstance(error, dict) and str(error.get('statusCode')) == '404' and error.get('code') == 'NoSuchKey':
                    return None
                response.raise_for_status()
            return bytes(content)

    async def restore(self, session, *, uid, apply_owner):
        if session.home.is_symlink() or any(session.home.iterdir()):
            return False
        execution = session.packet.interview_context.get('execution') or {}
        checkpoint = execution.get('home_checkpoint')
        if checkpoint is None:
            return False
        if not isinstance(checkpoint, dict):
            raise ValueError('Invalid committed Codex checkpoint')
        path = self._path(session, checkpoint.get('sequence'), checkpoint.get('archive_sha256'))
        if (checkpoint.get('path') != path or checkpoint.get('scope') != session.scope
                or any(checkpoint.get(key) != execution.get(key)
                    for key in ('thread_id', 'sequence', 'source_id', 'reply_sha256'))):
            return False
        async with httpx.AsyncClient(headers=self.headers, timeout=5, transport=self.transport) as client:
            content = await self._download(client, path)
        if content is None:
            return False
        if len(content) != checkpoint.get('byte_size') or hashlib.sha256(content).hexdigest() != checkpoint['archive_sha256']:
            raise ValueError('Codex checkpoint integrity mismatch')
        state, files = _unpack(content, session)
        if any(state.get(key) != checkpoint.get(key)
                for key in ('thread_id', 'sequence', 'source_id', 'reply_sha256')):
            raise ValueError('Codex checkpoint does not match its committed turn')
        previous = session.state
        session.state = state
        if not session.compatible():
            session.state = previous
            return False
        staged = Path(tempfile.mkdtemp(prefix='.codex-restore-', dir=session.root))
        try:
            for name, value in files.items():
                path = staged / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(value)
            for path in [*staged.rglob('*'), staged]:
                os.chmod(path, 0o700 if path.is_dir() else 0o600)
                if apply_owner:
                    os.chown(path, uid, uid)
            os.replace(staged, session.home)
        except BaseException:
            session.state = previous
            raise
        finally:
            if staged.exists():
                shutil.rmtree(staged)
        return True

    async def save(self, session, state):
        content = _pack(session, state)
        digest = hashlib.sha256(content).hexdigest()
        path = self._path(session, state['sequence'], digest)
        async with httpx.AsyncClient(headers=self.headers, timeout=5, transport=self.transport) as client:
            response = await client.post(self.url + '/storage/v1/object/' + BUCKET + '/' + path, content=content,
                headers={'Content-Type': 'application/zip', 'x-upsert': 'false'})
            # An uncertain prior upload may already exist. The immutable key is
            # reusable only after an exact readback, including on a conflict.
            if response.status_code not in (400, 409):
                response.raise_for_status()
            if await self._download(client, path) != content:
                raise ValueError('Codex checkpoint readback mismatch')
        # shortcut: immutable orphan/superseded objects need a retention job
        # before long-running production use; they never replace a committed one.
        return dict(path=path, scope=session.scope, archive_sha256=digest, byte_size=len(content),
            **{key: state[key] for key in ('thread_id', 'sequence', 'source_id', 'source_version', 'reply_sha256')})


async def stage_checkpoint(publisher, fence, checkpoint):
    """Only the trusted worker records verification; SQL owns later promotion."""
    from psycopg import AsyncConnection
    from psycopg.types.json import Jsonb
    async with await AsyncConnection.connect(publisher._dsn, connect_timeout=2) as connection:
        await connection.execute("set local statement_timeout='5000ms'")
        await connection.execute('set local role service_role')
        await connection.execute("select set_config('request.jwt.claim.sub',%s,true)",
            (str(fence.identity.owner_id),))
        await connection.execute('select public.stage_lifetime_runtime_checkpoint(%s,%s,%s)',
            (Jsonb(fence.model_dump(mode='json')), Jsonb(checkpoint),
                publisher.lock_function == 'lock_lifetime_draft_reply'))


def checkpoint_failure(operation, error):
    # HTTP errors may contain credentials or private object paths. Log only type.
    logger.warning('codex_home_checkpoint_failed operation=%s error_type=%s', operation, type(error).__name__)
