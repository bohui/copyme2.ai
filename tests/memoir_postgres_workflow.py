"""Synthetic Supabase HTTP adapter backed by the disposable real database.

Auth metadata and the external model/provider are controlled test boundaries.
All application RPCs, RLS, transactions, sources and revisions run in PostgreSQL.
This is a test adapter, never a production endpoint or an application mock.
"""
import json
import re

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
                            'user_recall_usage', 'user_completed_round', 'user_private_draft_outbox', 'user_family_context'}
            if request.method == 'GET':
                filters = []
                for key, value in request.url.params.multi_items():
                    if key in {'select', 'order', 'limit', 'offset'}:
                        continue
                    assert re.fullmatch('[a-z_]+', key)
                    if value.startswith('eq.'):
                        filters.append(key + '=' + quoted(value[3:]))
                    elif value == 'is.null':
                        filters.append(key + ' is null')
                    else:
                        raise AssertionError('Unsupported synthetic REST filter')
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
        result = self.sql(f"set role {'service_role' if self.service else 'authenticated'}; set request.jwt.claim.sub={quoted(self.owner)}; {query}", check=False)
        if result.returncode:
            if self.service:
                raise AssertionError('Synthetic service SQL failed: ' + result.stderr)
            code = '40001' if 'conflict' in result.stderr else '42501'
            return httpx.Response(409 if code == '40001' else 403, json={'code': code, 'message': result.stderr})
        value = json.loads(result.stdout.splitlines()[-1] or 'null')
        return httpx.Response(200, content=json.dumps(value), headers={'Content-Type': 'application/json'})
