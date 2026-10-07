"""Supabase operations always run as the verified end user, never service_role."""
import base64
import binascii
import json
from datetime import datetime, timezone
from pathlib import PurePosixPath
from urllib.parse import quote
from uuid import UUID

import httpx

from .family_context import normalise_family_context_document


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

    def _owned_attachment_path(self, path):
        if not isinstance(path, str):
            raise ValueError('An attachment owned by the current user is required')
        parsed = PurePosixPath(path)
        if (path != parsed.as_posix() or '\\' in path
                or any(part in {'.', '..'} for part in parsed.parts)
                or len(parsed.parts) < 3 or parsed.parts[:2] != (self.user_id, 'attachment')):
            raise ValueError('An attachment owned by the current user is required')
        return path

    def signed_attachment_url(self, path):
        path = self._owned_attachment_path(path)
        signed = self.request('POST', '/storage/v1/object/sign/memory-spark/' + quote(path, safe='/'),
                              json={'expiresIn': 3600}).json()['signedURL']
        if not signed.startswith('/object/sign/'):
            raise ValueError('Invalid signed attachment URL')
        return self.url + '/storage/v1' + signed

    def delete_attachment(self, path):
        return self.request('DELETE', '/storage/v1/object/memory-spark',
                            json={'prefixes': [self._owned_attachment_path(path)]})

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
        return normalise_family_context_document(document) if isinstance(document, dict) else None

    def upsert_family_context(self, project_id, document, expected_revision=0):
        """Atomically persist a Family document and return its update envelope."""
        result = self.request('POST', '/rest/v1/rpc/upsert_user_family_context', json={
            'p_project_id': project_id,
            'p_document': normalise_family_context_document(document),
            'p_expected_revision': expected_revision,
        }).json()
        if isinstance(result.get('document'), dict):
            result['document'] = normalise_family_context_document(result['document'])
        return result

    def save_memory(self, text, *, kind='memoir', source_paths=None):
        return self.request('POST', '/rest/v1/user_memory', headers={'Prefer': 'return=representation'},
                            json={'user_id': self.user_id, 'kind': kind, 'content': text,
                                  'source_paths': source_paths or []}).json()

    def memories(self):
        return self.request('GET', '/rest/v1/user_memory',
                            params={'order': 'created_at.desc', 'limit': '100'}).json()

    def first_narrator_reply(self):
        from .conversation_locale import first_narrator_reply
        for offset in range(0, 1200, 200):
            rows = self.request('GET', '/rest/v1/user_memory', params={
                'user_id': f'eq.{self.user_id}', 'kind': 'eq.agent',
                'order': 'created_at.asc,id.asc', 'limit': '200', 'offset': str(offset),
            }).json()
            first = first_narrator_reply(rows)
            if first or len(rows) < 200:
                return first
        raise ValueError('First-reply history exceeds the supported retrieval bound')

    def all_memories(self, *, order='created_at.asc,id.asc'):
        """Read a bounded complete collection, never silently truncate a book."""
        rows = []
        for offset in range(0, 1200, 200):
            page = self.request('GET', '/rest/v1/user_memory', params={
                'order': order, 'limit': '200', 'offset': str(offset),
            }).json()
            rows.extend(page)
            if len(rows) > 1000:
                raise ValueError('Collection exceeds the current 1000-memory limit')
            if len(page) < 200:
                return rows
        raise ValueError('Collection exceeds the current memory limit')

    def composition_memories(self):
        return self.all_memories(order='life_stage_order.asc,created_at.asc,id.asc')

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

    def commit_agent_turn(self, lease_token, thread_id, text, source_paths, *, source_sequence=None,
                          project_id=None, client_turn_id=None, user_response=True, life_stage=None):
        payload = {
            'p_lease_token': lease_token,
            'p_thread_id': thread_id,
            'p_content': text,
            'p_source_paths': source_paths,
        }
        if source_sequence is not None:
            payload['p_source_sequence'] = source_sequence
        if project_id is not None:
            payload.update(p_project_id=project_id, p_client_turn_id=client_turn_id, p_user_response=user_response)
            payload['p_life_stage'] = life_stage or 'unplaced'
        return self.request('POST', '/rest/v1/rpc/commit_user_agent_turn', json=payload).json()

    def agent_turn_by_id(self, project_id, client_turn_id):
        rows = self.request('GET', '/rest/v1/user_memory', params={
            'project_id':f'eq.{project_id}', 'client_turn_id':f'eq.{UUID(client_turn_id)}',
            'user_id':f'eq.{self.user_id}', 'limit':'1'}).json()
        return rows[0] if rows else None

    def narrator_source_by_id(self, project_id, source_id):
        rows = self.request('GET', '/rest/v1/user_narrator_source', params={
            'select': 'id,project_id,version,sequence,text,kind,status,language,created_at',
            'user_id': f'eq.{self.user_id}', 'project_id': f'eq.{project_id}',
            'id': f'eq.{UUID(source_id)}', 'limit': '1',
        }).json()
        return rows[0] if rows else None

    def narrator_source_by_turn(self, project_id, client_turn_id):
        rows = self.narrator_sources_by_turns(project_id, [client_turn_id])
        return rows[0] if rows else None

    def narrator_sources_by_turns(self, project_id, client_turn_ids):
        if not client_turn_ids:
            return []
        ids = ','.join(str(UUID(value)) for value in client_turn_ids)
        return self.request('GET', '/rest/v1/user_narrator_source', params={
            'select': 'id,client_turn_id,sequence,version,text,kind,language,status,processing_status',
            'user_id': f'eq.{self.user_id}', 'project_id': f'eq.{project_id}',
            'client_turn_id': f'in.({ids})', 'limit': str(len(client_turn_ids)),
        }).json()

    def completed_round_by_turn(self, project_id, client_turn_id):
        rows = self.request('GET', '/rest/v1/user_completed_round', params={
            'select': 'ordinal,memory_id', 'user_id': f'eq.{self.user_id}',
            'project_id': f'eq.{project_id}', 'turn_id': f'eq.{UUID(client_turn_id)}', 'limit': '1',
        }).json()
        return rows[0] if rows else None

    def memoir_projects(self, limit=51, after_project_id=None):
        params = {'select': 'project_id,source_sequence,event_sequence,policy_epoch',
                  'user_id': f'eq.{self.user_id}', 'order': 'project_id.asc', 'limit': str(limit)}
        if after_project_id is not None:
            params['project_id'] = f'gt.{after_project_id}'
        return self.request('GET', '/rest/v1/user_memoir_project', params=params).json()

    def memoir_project(self, project_id):
        rows = self.request('GET', '/rest/v1/user_memoir_project', params={
            'select': 'project_id,source_sequence,event_sequence,policy_epoch',
            'user_id': f'eq.{self.user_id}', 'project_id': f'eq.{project_id}', 'limit': '1',
        }).json()
        return rows[0] if rows else None

    def project_conversation_page(self, project_id, limit=51, boundary=None):
        params = {'select': 'id,client_turn_id,kind,content,source_sequence,created_at',
                  'user_id': f'eq.{self.user_id}', 'project_id': f'eq.{project_id}',
                  'kind': 'in.(agent,agent_greeting)', 'order': 'created_at.desc,id.desc', 'limit': str(limit)}
        if boundary is not None:
            created_at, memory_id = boundary
            params['or'] = f'(created_at.lt.{created_at},and(created_at.eq.{created_at},id.lt.{memory_id}))'
        return self.request('GET', '/rest/v1/user_memory', params=params).json()

    def accept_narrator_source(self, project_id, client_turn_id, text, *, kind='narrator_chat', language='en-AU'):
        """Commit original evidence and its durable intent before reply delivery."""
        return self.request('POST', '/rest/v1/rpc/accept_user_narrator_source', json={
            'p_project_id': project_id, 'p_client_turn_id': str(UUID(client_turn_id)),
            'p_text': text, 'p_kind': kind, 'p_language': language,
        }).json()

    def memory_events(self, project_id):
        return self.request('POST', '/rest/v1/rpc/read_user_memory_events',
                            json={'p_project_id': project_id}).json()

    def saved_memoir_draft(self, project_id, language=None):
        from .recall import private_draft_cadence
        locale = language or self.profile().get('preferred_language') or 'en-AU'
        view = self.request('POST', '/rest/v1/rpc/read_user_memoir_draft', json={
            'p_project_id': project_id, 'p_locale': locale, 'p_cadence': private_draft_cadence(),
        }).json()
        if view['revision'] == 0:
            from .legacy_memoir import import_saved_cache
            if import_saved_cache(self, project_id, locale):
                return self.request('POST', '/rest/v1/rpc/read_user_memoir_draft', json={
                    'p_project_id': project_id, 'p_locale': locale, 'p_cadence': private_draft_cadence(),
                }).json()
        return view

    def retry_memoir_lane(self, project_id, skill):
        return self.request('POST', '/rest/v1/rpc/retry_user_memoir_lane', json={
            'p_project_id': project_id, 'p_skill': skill,
        }).json()

    def change_narrator_source(self, project_id, source_id, expected_version, action, text=None):
        return self.request('POST', '/rest/v1/rpc/change_user_narrator_source', json={
            'p_project_id': project_id, 'p_source_id': source_id, 'p_expected_version': expected_version,
            'p_action': action, 'p_text': text,
        }).json()

    def correct_memory_event(self, project_id, event_id, expected_revision, patch, statement):
        return self.request('POST', '/rest/v1/rpc/correct_user_memory_event', json={
            'p_project_id': project_id, 'p_event_id': event_id, 'p_expected_revision': expected_revision,
            'p_patch': patch, 'p_statement': statement,
        }).json()

    def private_draft_rounds(self, project_id):
        return self.request('GET', '/rest/v1/user_completed_round', params={
            'project_id':f'eq.{project_id}', 'user_id':f'eq.{self.user_id}',
            'order':'ordinal.asc', 'limit':'1001'}).json()

    def private_draft_event(self,project_id):
        rows=self.request('GET','/rest/v1/user_private_draft_outbox',params={
            'select':'id','user_id':f'eq.{self.user_id}','project_id':f'eq.{project_id}',
            'order':'created_at.desc,id.desc','limit':'1'}).json()
        return rows[0]['id'] if rows else None

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

    def assign_memory_stage(self, memory_id, life_stage):
        from .stage_readiness import LIFE_STAGES
        if life_stage not in (*LIFE_STAGES, 'unplaced'):
            raise ValueError('Invalid life stage')
        return self.request('PATCH', '/rest/v1/user_memory',
            params={'id': f'eq.{UUID(memory_id)}', 'user_id': f'eq.{self.user_id}', 'kind': 'eq.agent'},
            json={'life_stage': life_stage}, headers={'Prefer': 'return=representation'}).json()
