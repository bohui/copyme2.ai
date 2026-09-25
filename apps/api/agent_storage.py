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

    def save_profile(self, profile):
        return self.request('POST', '/rest/v1/user_profile',
                            headers={'Prefer': 'resolution=merge-duplicates,return=representation'},
                            json={'user_id': self.user_id, 'profile': profile}).json()

    def profile(self):
        rows = self.request('GET', '/rest/v1/user_profile', params={
            'select': 'profile',
            'user_id': f'eq.{self.user_id}',
            'limit': '1',
        }).json()
        return rows[0].get('profile') or {} if rows else {}

    def save_memory(self, text, *, kind='memoir', source_paths=None):
        return self.request('POST', '/rest/v1/user_memory', headers={'Prefer': 'return=representation'},
                            json={'user_id': self.user_id, 'kind': kind, 'content': text,
                                  'source_paths': source_paths or []}).json()

    def memories(self):
        return self.request('GET', '/rest/v1/user_memory',
                            params={'order': 'created_at.desc', 'limit': '100'}).json()

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

    def commit_agent_turn(self, lease_token, thread_id, text, source_paths):
        return self.request('POST', '/rest/v1/rpc/commit_user_agent_turn', json={
            'p_lease_token': lease_token,
            'p_thread_id': thread_id,
            'p_content': text,
            'p_source_paths': source_paths,
        }).json()
