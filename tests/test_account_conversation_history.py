from unittest.mock import Mock

from fastapi.testclient import TestClient

from apps.api import supabase_routes
from apps.api.main import create_app
from apps.api.store import MemoryStore


def test_history_includes_saved_oauth_account_turns_and_attached_transcripts(monkeypatch):
    storage = Mock()
    storage.user_id = 'owner'
    attachment = {'id': 'attachment', 'project_id': 'guest-project',
                  'created_at': '2026-09-30', 'workspace': {'memory_id_map': {'old': 'imported'}},
                  'messages': [{'role': 'user', 'text': 'Guest childhood'}]}
    storage.request.return_value.json.return_value = [attachment]
    storage.all_memories.return_value = [
        {'id': 'older', 'kind': 'agent', 'created_at': '2026-09-28',
         'content': 'Storyteller: My previous history\nMemory Spark: Tell me more.'},
        {'id': 'imported', 'kind': 'agent', 'created_at': '2026-09-29',
         'content': 'Storyteller: Guest childhood\nMemory Spark: Welcome.'},
        {'id': 'note', 'kind': 'memoir', 'content': 'A collected memory'},
    ]
    monkeypatch.setattr(supabase_routes, 'storage', lambda auth: storage)
    monkeypatch.setattr(supabase_routes, '_queue_if_configured', lambda: None)
    result = supabase_routes.conversation_attachments('Bearer owner-session')
    assert result['resume_project_id'] == 'guest-project'
    items = result['items']
    messages = [message for item in items for message in item['messages']]
    assert {'role': 'user', 'text': 'My previous history'} in messages
    assert {'role': 'assistant', 'text': 'Tell me more.'} in messages
    assert sum(message['text'] == 'Guest childhood' for message in messages) == 1
    assert all(message['text'] != 'A collected memory' for message in messages)
    storage.client.close.assert_called_once()
    assert storage.request.call_args.kwargs['params']['user_id'] == 'eq.owner'


def test_conversation_history_requires_authentication(monkeypatch):
    monkeypatch.setenv('SUPABASE_URL', 'https://example.supabase.co')
    monkeypatch.setenv('SUPABASE_PUBLISHABLE_KEY', 'public-key')
    client = TestClient(create_app(MemoryStore()))
    assert client.get('/v1/user/conversations').status_code == 401


def test_history_returns_original_message_without_profile_instructions(monkeypatch):
    storage = Mock()
    storage.user_id = 'owner'
    storage.request.return_value.json.return_value = []
    original = '我叫小林\n我小时候住在北京。'
    storage.all_memories.return_value = [{
        'id': 'first', 'kind': 'agent', 'created_at': '2026-09-28',
        'content': "Storyteller: The storyteller said: " + original +
                   "\nThis is the storyteller's first answer to the shared profile-intake opening. "
                   "Extract only explicit facts\nMemory Spark: 你记得那里的什么？",
    }]
    monkeypatch.setattr(supabase_routes, 'storage', lambda auth: storage)
    monkeypatch.setattr(supabase_routes, '_queue_if_configured', lambda: None)
    messages = supabase_routes.conversation_attachments('Bearer owner-session')['items'][0]['messages']
    assert messages == [{'role': 'user', 'text': original},
                        {'role': 'assistant', 'text': '你记得那里的什么？'}]
