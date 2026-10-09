"""Synthetic Supabase HTTP adapter backed by the disposable real database.

Auth metadata and the external model/provider are controlled test boundaries.
All application RPCs, RLS, transactions, sources and revisions run in PostgreSQL.
This is a test adapter, never a production endpoint or an application mock.
"""
import json
import re
from datetime import datetime
from uuid import UUID

import httpx

from apps.api.agent_storage import UserStorage


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
        # psql frames records with physical LF, not Unicode line separators.
        # U+0085/U+2028/U+2029 are legal inside JSON strings and must survive.
        # Remove only the final record terminator; CRLF's CR is JSON whitespace.
        record = result.stdout.removesuffix('\n').rsplit('\n', 1)[-1]
        try:
            # A framed blank record is psql's SQL NULL representation. Missing
            # output and malformed nonempty JSON are errors, never a fallback.
            value = (None if result.stdout.endswith('\n') and record in ('', '\r')
                     else json.loads(record))
        except json.JSONDecodeError as error:
            # Consumers may publish only these fixed/numeric fields, never
            # the exception's document, message, query or SQL output streams.
            error.parser_boundary = 'postgres_rest_json_record'
            error.json_line, error.json_column, error.json_position = error.lineno, error.colno, error.pos
            raise
        return httpx.Response(200, content=json.dumps(value), headers={'Content-Type': 'application/json'})
