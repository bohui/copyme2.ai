"""Synthetic Supabase HTTP adapter backed by the disposable real database.

Auth metadata and the external model/provider are controlled test boundaries.
All application RPCs, RLS, transactions, sources and revisions run in PostgreSQL.
This is a test adapter, never a production endpoint or an application mock.
"""
import base64
import hashlib
import json
import re
from datetime import datetime
from urllib.parse import quote
from uuid import UUID

import httpx

from apps.api.agent_storage import UserStorage
from apps.api.codex_artifacts import MAX_ARTIFACT_BYTES as ARTIFACT_MAX_BYTES


ARTIFACT_MAX_OBJECTS_PER_OWNER = 512
ARTIFACT_MAX_BYTES_PER_OWNER = 512 * 1024 * 1024


def artifact_storage_limits():
    return {'max_artifact_bytes': ARTIFACT_MAX_BYTES,
        'max_objects_per_owner': ARTIFACT_MAX_OBJECTS_PER_OWNER,
        'max_bytes_per_owner': ARTIFACT_MAX_BYTES_PER_OWNER}


def initialize_artifact_storage(sql):
    """Only call after allocating and verifying a new disposable fixture PG.

    Supabase normally supplies these Storage grants and RLS activation. This
    fixture stores bytes in the same disposable database, never real Storage.
    Existing application policies and lease/publication RPCs stay unchanged.
    """
    if getattr(sql, '_memoir_artifact_storage_initialized', False):
        raise ValueError('Artifact fixture already initialized')
    sql(f'''begin;
        alter table storage.objects add column fixture_content bytea
            check (fixture_content is null or octet_length(fixture_content)<={ARTIFACT_MAX_BYTES});
        alter table storage.objects add constraint memoir_fixture_object_identity unique(bucket_id,name);
        alter table storage.objects enable row level security;
        grant usage on schema storage to authenticated;
        grant select,insert on storage.objects to authenticated;
        commit;''')
    sql._memoir_artifact_storage_initialized = True
    return artifact_storage_limits()


def _sql_json_record(stdout):
    # A physical LF is framing; Unicode separators inside JSON are content.
    record = stdout.removesuffix('\n').rsplit('\n', 1)[-1]
    try:
        return (None if stdout.endswith('\n') and record in ('', '\r')
                else json.loads(record))
    except json.JSONDecodeError as error:
        error.parser_boundary = 'postgres_rest_json_record'
        error.json_line, error.json_column, error.json_position = error.lineno, error.colno, error.pos
        raise


async def verify_artifact_storage(sql, *, probe_owner):
    """Provider-free actual-runtime upload and fresh-facade byte readback.

    The caller supplies a fresh synthetic UUID outside all campaign owners.
    Every blocking operation joins before cancellation propagates or cleanup.
    Only this newly inserted owner's records may be removed by this helper.
    """
    from apps.api.agent_lock import AgentTurnLease
    from apps.api.codex_runtime import CodexRuntime
    if (type(probe_owner) is not str or str(UUID(probe_owner)) != probe_owner
            or getattr(sql, '_memoir_artifact_storage_initialized', False) is not True):
        raise ValueError('Initialized owned fixture and fresh probe UUID required')
    contents = (
        ('sessions/readiness.jsonl', b'{"synthetic":1}\n{"synthetic":2}\n'),
        ('memories/readiness.bin', b'\x00\xffsynthetic artifact\xe2\x80\xa8\n'),
    )
    created, stores, receipt = [False], [], None
    def create_owner():
        # An existing UUID must fail, never be adopted or later deleted.
        sql(f"insert into auth.users(id,is_anonymous) values({quoted(probe_owner)},false);")
        created[0] = True
    def clean_owner():
        sql(f'''begin;
            delete from storage.objects where bucket_id='memory-spark'
                and split_part(name,'/',1)={quoted(probe_owner)};
            delete from auth.users where id={quoted(probe_owner)};
            commit;''')
        result = sql(f'''select jsonb_build_object('owners',
            (select count(*) from auth.users where id={quoted(probe_owner)}),
            'objects',(select count(*) from storage.objects
                where split_part(name,'/',1)={quoted(probe_owner)}));''')
        if _sql_json_record(result.stdout) != {'owners': 0, 'objects': 0}:
            raise RuntimeError('Synthetic artifact probe cleanup unverified')
    try:
        await AgentTurnLease.io(create_owner)
        storage = await AgentTurnLease.io(lambda: PostgresRest(sql, probe_owner).storage())
        stores.append(storage)
        async with AgentTurnLease(storage) as lease:
            paths = await lease.io(CodexRuntime._save_worker_artifacts, storage,
                [{'path': path, 'content': base64.b64encode(content).decode('ascii')}
                    for path, content in contents], lease)
            await lease.check()
        reader = await AgentTurnLease.io(lambda: PostgresRest(sql, probe_owner).storage())
        stores.append(reader)
        if len(paths) != len(contents):
            raise RuntimeError('Synthetic artifact probe upload unverified')
        for path, (_, expected) in zip(paths, contents):
            actual = await AgentTurnLease.io(reader.get_agent_file, path)
            if actual != expected:
                raise RuntimeError('Synthetic artifact probe readback differs')
        receipt = {'status': 'verified', 'byte_readback_verified': True,
            'probe_cleaned': False, 'model_calls': 0, 'real_storage_writes': False,
            'backend': 'owned_disposable_postgres', 'artifacts': len(contents),
            'bytes': sum(len(content) for _, content in contents),
            'sha256': [hashlib.sha256(content).hexdigest() for _, content in contents],
            'limits': artifact_storage_limits()}
    finally:
        try:
            for storage in stores:
                await AgentTurnLease.io(storage.client.close)
        finally:
            if created[0]:
                await AgentTurnLease.io(clean_owner)
                if receipt is not None:
                    receipt['probe_cleaned'] = True
    return receipt


def quoted(value):
    if value is None:
        return 'null'
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (dict, list)):
        return "'" + json.dumps(value, ensure_ascii=False).replace("'", "''") + "'::jsonb"
    return "'" + str(value).replace("'", "''") + "'"


def read_filter(key, value):
    """Only the product recovery reader's structured filters, never raw SQL."""
    if key == 'or':
        matched = re.fullmatch(r'\(created_at\.lt\.([^,()]+),and\(created_at\.eq\.([^,()]+),id\.lt\.([0-9a-f-]{36})\)\)', value)
        if not matched or matched[1] != matched[2]:
            raise ValueError('Unsupported synthetic history cursor')
        date = datetime.fromisoformat(matched[1])
        if date.tzinfo is None or str(UUID(matched[3])) != matched[3]:
            raise ValueError('Invalid synthetic history cursor')
        timestamp, identifier = quoted(date.isoformat()), quoted(matched[3])
        return f'(created_at<{timestamp} or (created_at={timestamp} and id<{identifier}))'
    if not re.fullmatch('[a-z_]+', key):
        raise ValueError('Invalid synthetic field')
    if value.startswith('eq.'):
        return key + '=' + quoted(value[3:])
    if value == 'is.null':
        return key + ' is null'
    if value.startswith('gt.') and key == 'project_id' and re.fullmatch('[A-Za-z0-9][A-Za-z0-9_-]{0,127}', value[3:]):
        return key + '>' + quoted(value[3:])
    if value.startswith('in.(') and value.endswith(')') and key in {'kind', 'client_turn_id'}:
        values = value[4:-1].split(',')
        if not 1 <= len(values) <= 1001:
            raise ValueError('Invalid synthetic list filter')
        if key == 'kind':
            if not all(item in {'agent', 'agent_greeting'} for item in values):
                raise ValueError('Invalid synthetic memory kind')
        elif not all(str(UUID(item)) == item for item in values):
            raise ValueError('Invalid synthetic turn identifier')
        return key + ' in (' + ','.join(quoted(item) for item in values) + ')'
    raise ValueError('Unsupported synthetic REST filter')


class PostgresRest:
    def __init__(self, sql, owner, *, service=False, entitlement=None):
        self.sql, self.owner, self.service = sql, owner, service
        self.entitlement = entitlement

    def storage(self):
        return UserStorage('http://synthetic.invalid', 'synthetic-public', self.owner,
                           client=httpx.Client(transport=httpx.MockTransport(self.handle)))

    def handle(self, request):
        if request.url.path == '/auth/v1/user':
            return httpx.Response(200, json={'id': self.owner, 'is_anonymous': False})
        if request.url.path.startswith('/storage/'):
            return self._artifact_request(request)
        body = json.loads(request.content) if request.content else {}
        if request.method == 'GET' and request.url.path == '/rest/v1/rpc/read_user_interview_turn':
            if set(request.url.params) != {'p_project_id', 'p_client_turn_id'}:
                raise ValueError('Exact read-interview RPC arguments required')
            body = dict(request.url.params)
            if str(UUID(body['p_client_turn_id'])) != body['p_client_turn_id']:
                raise ValueError('Canonical client turn required')
        path = request.url.path.removeprefix('/rest/v1/')
        if path == 'story_entitlements':
            # External verified entitlement boundary: this storyteller is free.
            return httpx.Response(200, json=[self.entitlement] if self.entitlement else [])
        if path.startswith('rpc/'):
            name = path[4:]
            assert re.fullmatch('[a-z_]+', name)
            args = []
            for key, value in body.items():
                assert re.fullmatch('p_[a-z_]+', key)
                literal = quoted(value)
                if key == 'p_source_paths':
                    literal = 'array[' + ','.join(quoted(v) for v in value) + ']::text[]'
                args.append(f'{key}=>{literal}')
            query = f'select to_jsonb(public.{name}(' + ','.join(args) + '));'
        else:
            assert path in {'user_profile', 'user_memory', 'user_agent_session', 'user_place_journey',
                            'user_recall_usage', 'user_completed_round', 'user_private_draft_outbox', 'user_family_context',
                            'user_memoir_project', 'user_narrator_source'}
            if request.method == 'GET':
                selected = request.url.params.get('select', '*')
                if not re.fullmatch(r'\*|[a-z_]+(?:,[a-z_]+)*', selected):
                    raise ValueError('Invalid synthetic field selection')
                filters = []
                for key, value in request.url.params.multi_items():
                    if key in {'select', 'order', 'limit', 'offset'}:
                        continue
                    filters.append(read_filter(key, value))
                where = ' where ' + ' and '.join(filters) if filters else ''
                ordering = request.url.params.get('order', '')
                order_parts = []
                for part in ordering.split(',') if ordering else []:
                    field, _, direction = part.partition('.')
                    assert re.fullmatch('[a-z_]+', field) and direction in {'', 'asc', 'desc'}
                    order_parts.append(field + ' ' + (direction or 'asc'))
                order = ' order by ' + ','.join(order_parts) if order_parts else ''
                limit = int(request.url.params.get('limit', '1001'))
                offset = int(request.url.params.get('offset', '0'))
                if not 0 <= limit <= 1001 or not 0 <= offset <= 1200:
                    raise ValueError('Bounded synthetic page required')
                query = f"select coalesce(jsonb_agg(to_jsonb(r)),'[]'::jsonb) from (select * from public.{path}{where}{order} limit {limit} offset {offset}) r;"
            elif path == 'user_profile' and request.method == 'POST':
                query = f"with r as (insert into public.user_profile(user_id,profile) values({quoted(self.owner)},{quoted(body['profile'])}) on conflict(user_id) do update set profile=excluded.profile returning *) select jsonb_agg(to_jsonb(r)) from r;"
            elif path == 'user_memory' and request.method == 'PATCH':
                assert set(body).issubset({'life_stage', 'source_paths'})
                assignments = []
                for key, value in body.items():
                    value_sql = 'array[' + ','.join(quoted(v) for v in value) + ']::text[]' if key == 'source_paths' else quoted(value)
                    assignments.append(key + '=' + value_sql)
                id_value = request.url.params['id'].removeprefix('eq.')
                query = f"with r as (update public.user_memory set {','.join(assignments)} where user_id={quoted(self.owner)} and id={quoted(id_value)} returning *) select coalesce(jsonb_agg(to_jsonb(r)),'[]') from r;"
            else:
                raise AssertionError('Unsupported synthetic REST operation')
        result = self.sql(f"\\set VERBOSITY verbose\nset role {'service_role' if self.service else 'authenticated'}; set request.jwt.claim.sub={quoted(self.owner)}; {query}", check=False)
        if result.returncode:
            if self.service:
                raise AssertionError('Synthetic service SQL failed: ' + result.stderr)
            native_code = re.search(r'ERROR:\s+([A-Z0-9]{5}):', result.stderr)
            assert native_code, 'The disposable database must report its actual SQLSTATE'
            code = native_code[1]
            # PostgREST documents 40* (transaction rollback) as HTTP 500.
            # Never manufacture HTTP 409 from the word "conflict".
            status = 500 if code.startswith(('40', 'XX')) else 403 if code=='42501' else 409 if code in ('23503','23505') else 400
            return httpx.Response(status, json={'code': code, 'message': result.stderr})
        value = _sql_json_record(result.stdout)
        return httpx.Response(200, content=json.dumps(value), headers={'Content-Type': 'application/json'})

    def _artifact_request(self, request):
        def reject(status):
            return httpx.Response(status, json={'detail': 'Synthetic artifact storage unavailable'})
        if self.service:
            return reject(403)
        if getattr(self.sql, '_memoir_artifact_storage_initialized', False) is not True:
            return reject(503)
        prefix = {'POST': '/storage/v1/object/memory-spark/',
                  'GET': '/storage/v1/object/authenticated/memory-spark/'}.get(request.method)
        path = request.url.path
        if prefix is None or not path.startswith(prefix):
            return reject(405)
        if (request.url.query or request.url.fragment or len(path) > 4096
                or request.url.raw_path != quote(path, safe='/').encode('ascii')
                or '\\' in path or any(ord(char) < 32 or ord(char) == 127 for char in path)):
            return reject(400)
        name = path[len(prefix):]
        parts = name.split('/')
        if (len(parts) < 6 or parts[0] != self.owner or parts[1] != 'agent'
                or parts[2] not in {'sessions', 'archived_sessions', 'memories'}
                or parts[3] != 'turns' or any(not part or part.startswith('.') for part in parts)):
            return reject(403)
        try:
            if str(UUID(self.owner)) != self.owner or str(UUID(parts[4])) != parts[4]:
                return reject(400)
        except ValueError:
            return reject(400)
        if request.method == 'POST':
            content = request.content
            if (request.headers.get('content-type') != 'application/octet-stream'
                    or request.headers.get('x-upsert') != 'false'
                    or request.headers.get('content-encoding', 'identity') != 'identity'
                    or request.headers.get('content-length') != str(len(content))):
                return reject(400)
            if len(content) > ARTIFACT_MAX_BYTES:
                return reject(413)
            # Separate lock and INSERT statements are intentional: after a
            # concurrent holder commits, READ COMMITTED takes a fresh quota
            # snapshot for INSERT. A same-statement lock CTE would be stale.
            query = f'''begin isolation level read committed;
                set local role authenticated;
                set local request.jwt.claim.sub={quoted(self.owner)};
                select pg_advisory_xact_lock(hashtextextended({quoted('memoir-fixture-artifact:' + self.owner)},0));
                with quota as (
                    select count(*) as objects,coalesce(sum(octet_length(fixture_content)),0) as bytes
                    from storage.objects where bucket_id='memory-spark'
                    and split_part(name,'/',1)={quoted(self.owner)} and fixture_content is not null
                ), inserted as (
                    insert into storage.objects(bucket_id,name,fixture_content)
                    select 'memory-spark',{quoted(name)},decode('{content.hex()}','hex') from quota
                    where objects<{ARTIFACT_MAX_OBJECTS_PER_OWNER}
                        and bytes+{len(content)}<={ARTIFACT_MAX_BYTES_PER_OWNER}
                    on conflict(bucket_id,name) do nothing
                    returning octet_length(fixture_content) as bytes
                ) select coalesce((select jsonb_build_object('status','stored','bytes',bytes) from inserted),
                    jsonb_build_object('status',case when exists(select 1 from storage.objects
                        where bucket_id='memory-spark' and name={quoted(name)})
                        then 'conflict' else 'quota_exceeded' end));
                commit;'''
        else:
            query = f'''set role authenticated; set request.jwt.claim.sub={quoted(self.owner)};
                select jsonb_build_object('content_hex',encode(fixture_content,'hex'),
                    'bytes',octet_length(fixture_content)) from storage.objects
                where bucket_id='memory-spark' and name={quoted(name)} and fixture_content is not null;'''
        result = self.sql('\\set VERBOSITY verbose\n' + query, check=False)
        if result.returncode:
            code = re.search(r'ERROR:\s+([A-Z0-9]{5}):', result.stderr)
            return reject(403 if code and code[1] == '42501' else 500)
        # SELECT without rows produces no record, rather than fabricated bytes.
        if request.method == 'GET' and not result.stdout:
            return reject(404)
        value = _sql_json_record(result.stdout)
        if request.method == 'POST':
            if type(value) is not dict:
                return reject(500)
            if value.get('status') in {'conflict', 'quota_exceeded'}:
                return reject(409 if value['status'] == 'conflict' else 413)
            if (value.get('status') != 'stored' or type(value.get('bytes')) is not int
                    or value['bytes'] != len(content)):
                return reject(500)
            return httpx.Response(200, json={'Key': 'memory-spark/' + name})
        if value is None:
            return reject(404)
        if (type(value) is not dict or type(value.get('bytes')) is not int
                or not 0 <= value['bytes'] <= ARTIFACT_MAX_BYTES
                or type(value.get('content_hex')) is not str
                or len(value['content_hex']) != value['bytes'] * 2
                or not re.fullmatch('[0-9a-f]*', value['content_hex'])):
            return reject(500)
        return httpx.Response(200, content=bytes.fromhex(value['content_hex']),
            headers={'Content-Type': 'application/octet-stream'})
