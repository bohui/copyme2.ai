from uuid import UUID

import httpx
import pytest

from apps.api.agent_storage import UserStorage


def test_storage_uses_verified_user_and_preserves_codex_relative_paths():
    calls = []
    owner = '11111111-1111-4111-8111-111111111111'

    def server(request):
        calls.append(request)
        if request.url.path == '/auth/v1/user':
            return httpx.Response(200, json={'id': owner})
        return httpx.Response(200, json={})

    client = httpx.Client(transport=httpx.MockTransport(server))
    storage = UserStorage('https://example.supabase.co', 'public-key', 'user-jwt', client=client)
    assert storage.user_id == str(UUID(owner))
    storage.put_agent_file('memories/rollout_summaries/first.md', b'a memory')
    assert calls[-1].url.path == f'/storage/v1/object/memory-spark/{owner}/agent/memories/rollout_summaries/first.md'
    assert calls[-1].headers['authorization'] == 'Bearer user-jwt'
    for path in ['../auth.json', 'auth.json', '/sessions/x', 'sessions/../../other', 'memories/.git/config']:
        with pytest.raises(ValueError):
            storage.put_agent_file(path, b'secret')
    assert len(calls) == 2


def test_storage_reads_anonymous_user_flag_and_profile_from_supabase():
    owner = '11111111-1111-4111-8111-111111111111'

    def server(request):
        if request.url.path == '/auth/v1/user':
            return httpx.Response(200, json={'id': owner, 'is_anonymous': True})
        if request.url.path == '/rest/v1/user_profile':
            return httpx.Response(200, json=[{'profile': {'story_flow': {'rounds_completed': 2}}}])
        return httpx.Response(200, json={})

    client = httpx.Client(transport=httpx.MockTransport(server))
    storage = UserStorage('https://example.supabase.co', 'public-key', 'user-jwt', client=client)

    assert storage.is_anonymous is True
    assert storage.profile() == {'story_flow': {'rounds_completed': 2}}
