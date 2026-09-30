"""Supabase operations always run as the verified end user, never service_role."""
import base64
import binascii
import json
from datetime import datetime, timezone
from pathlib import PurePosixPath
from urllib.parse import quote
from uuid import UUID

import httpx


class UserStorage:
    def __init__(self, url, public_key, access_token, *, client=None):
        self.url = url.rstrip('/')
        self.client = client or httpx.Client(timeout=30)
        self.headers = {'apikey': public_key, 'Authorization': f'Bearer {access_token}'}
        user = self.request('GET', '/auth/v1/user').json()
        self.user = user
        self.user_id = str(UUID(user['id']))
        claims = self._jwt_claims(access_token)
        self.is_anonymous = bool(
            user.get('is_anonymous')
            or user.get('user_metadata', {}).get('is_anonymous')
            or claims.get('is_anonymous')
        )

    @staticmethod
    def _jwt_claims(access_token):
        try:
            encoded = access_token.split('.')[1]
            encoded += '=' * (-len(encoded) % 4)
            return json.loads(base64.urlsafe_b64decode(encoded).decode('utf-8'))
        except (binascii.Error, IndexError, ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
            return {}

    def request(self, method, path, **kwargs):
        headers = {**self.headers, **kwargs.pop('headers', {})}
        response = self.client.request(method, self.url + path, headers=headers, **kwargs)
        response.raise_for_status()
        return response

    @staticmethod
    def agent_path(relative):
        path = PurePosixPath(relative)
        if (path.is_absolute() or relative != path.as_posix() or
                any(part.startswith('.') for part in path.parts) or len(path.parts) < 2 or
                path.parts[0] not in {'sessions', 'archived_sessions', 'memories'}):
            raise ValueError('Only Codex session and memory artifacts may be synchronized')
        return path.as_posix()

    def put_agent_file(self, relative, content):
        path = f'{self.user_id}/agent/{self.agent_path(relative)}'
        return self._put(path, content, 'application/octet-stream', overwrite=True)

    def get_agent_file(self, relative):
        path = f'{self.user_id}/agent/{self.agent_path(relative)}'
        return self.request('GET', '/storage/v1/object/authenticated/memory-spark/' + quote(path, safe='/')).content

    def put_attachment(self, filename, content, content_type):
        if not filename or PurePosixPath(filename).name != filename or '\\' in filename or filename.startswith('.'):
            raise ValueError('A plain filename is required')
        file = PurePosixPath(filename)
        timestamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        path = f'{self.user_id}/attachment/{file.stem}_{timestamp}{file.suffix}'
        self._put(path, content, content_type, overwrite=False)
        return path

    def _put(self, path, content, content_type, *, overwrite):
        return self.request('POST', '/storage/v1/object/memory-spark/' + quote(path, safe='/'),
                            content=content, headers={'Content-Type': content_type, 'x-upsert': str(overwrite).lower()})

    def save_profile(self, profile, *, source_sequences=None):
        if source_sequences is None and isinstance(profile, dict):
            source_sequences = profile.get('_agent_source_sequences')
        payload = {
            'user_id': self.user_id,
            'profile': {key: value for key, value in (profile or {}).items()
                        if key != '_agent_source_sequences'},
        }
        if source_sequences is not None:
            payload['agent_source_sequences'] = source_sequences
        return self.request('POST', '/rest/v1/user_profile',
                            headers={'Prefer': 'resolution=merge-duplicates,return=representation'},
                            json=payload).json()

    def profile(self):
        rows = self.request('GET', '/rest/v1/user_profile', params={
            'select': 'profile,agent_source_sequences',
            'user_id': f'eq.{self.user_id}',
            'limit': '1',
        }).json()
        if not rows:
            return {}
        profile = dict(rows[0].get('profile') or {})
        source_sequences = rows[0].get('agent_source_sequences')
        if isinstance(source_sequences, dict) and source_sequences:
            profile['_agent_source_sequences'] = source_sequences
        return profile

    def place_journey(self):
        rows = self.request('GET', '/rest/v1/user_place_journey', params={
            'select': 'schema_version,status,revision,source_sequence,place,hierarchy,granularity,latitude,longitude,duration_ms,created_at,updated_at',
            'user_id': f'eq.{self.user_id}',
            'limit': '1',
        }).json()
        return rows[0] if rows else None

    def save_place_journey(self, lease_token, journey, *, source_sequence=None):
        payload = {
            'p_lease_token': lease_token,
            'p_journey': journey,
        }
        if source_sequence is not None:
            payload['p_source_sequence'] = source_sequence
        return self.request('POST', '/rest/v1/rpc/upsert_user_place_journey', json=payload).json()

    def story_entitlement(self):
        rows = self.request('GET', '/rest/v1/story_entitlements', params={
            'select': 'status,plan_key,family_tree,timeline,expanded_details,stripe_price_id',
            'user_id': f'eq.{self.user_id}',
            'limit': '1',
        }).json()
        return rows[0] if rows else None

    def recall_rounds_completed(self):
        rows = self.request('GET', '/rest/v1/user_recall_usage', params={
            'select': 'rounds_completed',
            'user_id': f'eq.{self.user_id}',
            'limit': '1',
        }).json()
        return int(rows[0]['rounds_completed']) if rows else 0

    def family_context(self, project_id):
        """Read the renderable Family document under the user's RLS scope."""
        rows = self.request('GET', '/rest/v1/user_family_context', params={
            'select': 'document,revision,updated_at',
            'user_id': f'eq.{self.user_id}',
            'project_id': f'eq.{project_id}',
            'limit': '1',
        }).json()
        if not rows:
            return None
        document = rows[0].get('document')
        return document if isinstance(document, dict) else None

    def upsert_family_context(self, project_id, document, expected_revision=0):
        """Atomically persist a Family document and return its update envelope."""
        return self.request('POST', '/rest/v1/rpc/upsert_user_family_context', json={
            'p_project_id': project_id,
            'p_document': document,
            'p_expected_revision': expected_revision,
        }).json()

    def save_memory(self, text, *, kind='memoir', source_paths=None):
        return self.request('POST', '/rest/v1/user_memory', headers={'Prefer': 'return=representation'},
                            json={'user_id': self.user_id, 'kind': kind, 'content': text,
                                  'source_paths': source_paths or []}).json()

    def memories(self):
        return self.request('GET', '/rest/v1/user_memory',
                            params={'order': 'created_at.desc', 'limit': '100'}).json()

    def all_memories(self):
        """Read a bounded complete collection, never silently truncate a book."""
        rows = []
        for offset in range(0, 1200, 200):
            page = self.request('GET', '/rest/v1/user_memory', params={
                'order': 'created_at.asc,id.asc', 'limit': '200', 'offset': str(offset),
            }).json()
            rows.extend(page)
            if len(rows) > 1000:
                raise ValueError('Collection exceeds the current 1000-memory limit')
            if len(page) < 200:
                return rows
        raise ValueError('Collection exceeds the current memory limit')

    def agent_session(self):
        rows = self.request('GET', '/rest/v1/user_agent_session',
                            params={'select': '*', 'user_id': f'eq.{self.user_id}', 'limit': '1'}).json()
        return rows[0] if rows else None

    def save_agent_session(self, thread_id, status='active'):
        return self.request('POST', '/rest/v1/user_agent_session',
                            headers={'Prefer': 'resolution=merge-duplicates,return=representation'},
                            json={'user_id': self.user_id, 'codex_thread_id': thread_id, 'status': status}).json()

    def acquire_agent_turn_lease(self, lease_token, lease_seconds=300):
        return bool(self.request('POST', '/rest/v1/rpc/acquire_user_agent_turn_lease',
                                 json={'p_lease_token': lease_token,
                                       'p_lease_seconds': lease_seconds}).json())

    def renew_agent_turn_lease(self, lease_token, lease_seconds=300):
        return bool(self.request('POST', '/rest/v1/rpc/renew_user_agent_turn_lease',
                                 json={'p_lease_token': lease_token,
                                       'p_lease_seconds': lease_seconds}).json())

    def release_agent_turn_lease(self, lease_token):
        return bool(self.request('POST', '/rest/v1/rpc/release_user_agent_turn_lease',
                                 json={'p_lease_token': lease_token}).json())

    def put_agent_turn_file(self, lease_token, relative, content):
        root, tail = self.agent_path(relative).split('/', 1)
        path = f'{root}/turns/{UUID(lease_token)}/{tail}'
        self._put(f'{self.user_id}/agent/{path}', content,
                  'application/octet-stream', overwrite=False)
        return path

    def commit_agent_turn(self, lease_token, thread_id, text, source_paths, *, source_sequence=None):
        payload = {
            'p_lease_token': lease_token,
            'p_thread_id': thread_id,
            'p_content': text,
            'p_source_paths': source_paths,
        }
        if source_sequence is not None:
            payload['p_source_sequence'] = source_sequence
        return self.request('POST', '/rest/v1/rpc/commit_user_agent_turn', json=payload).json()

    def update_agent_memory_source_paths(self, memory_id, source_paths):
        try:
            memory_id = str(UUID(memory_id))
        except (ValueError, TypeError, AttributeError):
            raise ValueError('Invalid agent memory id') from None
        return self.request(
            'PATCH',
            '/rest/v1/user_memory',
            params={'id': f'eq.{memory_id}', 'user_id': f'eq.{self.user_id}'},
            headers={'Prefer': 'return=representation'},
            json={'source_paths': list(source_paths or [])},
        ).json()
