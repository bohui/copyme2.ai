import asyncio

import pytest
from fastapi.testclient import TestClient

from apps.api.codex_runtime import CodexRuntime
from apps.api.main import create_app
from apps.api.recall import free_recall_rounds
from apps.api.store import MemoryStore
from apps.api.story_payments import LocalStoryEntitlementStore, checkout_summary
from test_story_flow import FakeSupabaseUserStorage, _auth_headers
from test_story_payments import FakeStripeCheckout


class RecallStorage(FakeSupabaseUserStorage):
    def __init__(self, *, completed=0, paid=False, anonymous=False):
        super().__init__(anonymous=anonymous)
        self.completed = completed
        self.paid = paid
        self.held = False
        self._profile = {'preferred_language': 'en-AU'}

    def acquire_agent_turn_lease(self, *args):
        assert not self.held
        self.held = True
        return True

    def renew_agent_turn_lease(self, *args):
        return self.held

    def release_agent_turn_lease(self, *args):
        self.held = False
        return True

    def recall_rounds_completed(self):
        return self.completed

    def story_entitlement(self):
        return {'status': 'paid'} if self.paid else None

    def agent_session(self):
        return None

    def commit_agent_turn(self, token, thread_id, text, source_paths, **kwargs):
        assert self.held
        self.saved_turn = text
        self.completed += 1
        return [{'id': f'reply-{self.completed}', 'content': text}]


@pytest.mark.parametrize('explicit_original', [True, False])
def test_original_conversation_text_is_saved_separately_from_agent_instructions(monkeypatch, explicit_original):
    storage = RecallStorage()
    runtime = CodexRuntime(worker_url='http://unused')
    prompt = "The storyteller said: My garden\nAcknowledge the storyteller naturally, then ask one gentle open-ended follow-up question."
    received = []

    async def worker(**kwargs):
        received.append(kwargs['text'])
        return {'thread_id': 'thread', 'reply': 'What grew there?', 'artifacts': []}

    monkeypatch.setattr(runtime, '_worker_turn', worker)
    options = {'conversation_text': 'My garden'} if explicit_original else {}
    asyncio.run(runtime.turn(storage, prompt, **options))
    assert received == [prompt]
    assert storage.saved_turn == 'Storyteller: My garden\nMemory Spark: What grew there?'


@pytest.mark.parametrize('limit', [1, 3, 20])
def test_final_free_reply_is_saved_then_next_turn_is_blocked(monkeypatch, limit):
    monkeypatch.setenv('MEMORY_SPARK_FREE_RECALL_ROUNDS', str(limit))
    storage = RecallStorage(completed=limit - 1)
    runtime = CodexRuntime(worker_url='http://unused')
    calls = []

    async def worker(**kwargs):
        calls.append(kwargs)
        return {'thread_id': 'thread', 'reply': 'What else do you remember?', 'artifacts': []}

    monkeypatch.setattr(runtime, '_worker_turn', worker)
    events = []

    async def emit(event):
        events.append(event)

    final = asyncio.run(runtime.turn(storage, 'A memory', on_event=emit))
    assert final['reply'] == 'What else do you remember?'
    assert final['recall_status']['payment_required'] is True
    saved = next(event['data'] for event in events if event['type'] == 'conversation_saved')
    assert saved['recall_status']['payment_required'] is True
    assert storage.completed == limit
    blocked = asyncio.run(runtime.turn(storage, 'Another memory'))
    assert blocked['reply'] is None
    assert blocked['recall_status']['payment_required'] is True
    assert len(calls) == 1
    assert storage.completed == limit
    assert not storage.held


def test_failed_reply_does_not_consume_allowance_and_paid_users_can_continue(monkeypatch):
    monkeypatch.setenv('MEMORY_SPARK_FREE_RECALL_ROUNDS', '2')
    storage = RecallStorage(completed=1)
    runtime = CodexRuntime(worker_url='http://unused')

    async def failed(**kwargs):
        raise RuntimeError('provider unavailable')

    monkeypatch.setattr(runtime, '_worker_turn', failed)
    with pytest.raises(RuntimeError, match='provider unavailable'):
        asyncio.run(runtime.turn(storage, 'A memory'))
    assert storage.completed == 1
    assert not storage.held

    storage.completed = 2
    storage.paid = True

    async def worker(**kwargs):
        return {'thread_id': 'thread', 'reply': 'Let’s continue.', 'artifacts': []}

    monkeypatch.setattr(runtime, '_worker_turn', worker)
    paid = asyncio.run(runtime.turn(storage, 'A paid memory'))
    assert paid['recall_status']['payment_required'] is False
    assert paid['reply'] == 'Let’s continue.'


def test_status_and_checkout_use_verified_payment_and_allow_purchase_without_legacy_chapter(monkeypatch):
    monkeypatch.setenv('MEMORY_SPARK_FREE_RECALL_ROUNDS', '20')
    storage = RecallStorage(completed=20)
    storage._profile = {'story_flow': {'payment_status': 'paid', 'rounds_completed': 0}}
    memory = MemoryStore()
    entitlements = LocalStoryEntitlementStore(memory)
    stripe = FakeStripeCheckout()
    client = TestClient(create_app(memory, story_storage_factory=lambda authorization: storage,
                                 story_entitlement_store=entitlements, story_stripe_client=stripe))
    state = client.get('/v1/story/state', headers=_auth_headers()).json()
    assert state['recall_status']['payment_required'] is True
    checkout = client.post('/v1/story/checkout', headers=_auth_headers(),
                           json={'plan_key': 'electronic_memoir_v1'})
    assert checkout.status_code == 200, checkout.text
    assert checkout.json()['checkout_url']
    assert stripe.calls[0]['summary']['amount_minor'] == 4900
    entitlements.mark_paid(user_id=storage.user_id, session_id='verified', payment_intent_id='payment',
                           summary=checkout_summary('electronic_memoir_v1'))
    assert client.get('/v1/story/state', headers=_auth_headers()).json()['recall_status']['payment_required'] is False


def test_guest_must_link_identity_before_checkout(monkeypatch):
    monkeypatch.setenv('MEMORY_SPARK_FREE_RECALL_ROUNDS', '20')
    storage = RecallStorage(completed=20, anonymous=True)
    client = TestClient(create_app(MemoryStore(), story_storage_factory=lambda authorization: storage))
    response = client.post('/v1/story/checkout', headers=_auth_headers(), json={})
    assert response.status_code == 403
    assert response.headers['X-Error-Code'] == 'AUTH_REQUIRED'


def test_default_and_invalid_configuration(monkeypatch):
    monkeypatch.delenv('MEMORY_SPARK_FREE_RECALL_ROUNDS', raising=False)
    assert free_recall_rounds() == 20
    monkeypatch.setenv('MEMORY_SPARK_FREE_RECALL_ROUNDS', '0')
    with pytest.raises(ValueError, match='positive integer'):
        free_recall_rounds()


@pytest.mark.parametrize('value',[1,7,20,31])
def test_configured_allowance_boundaries_are_independent_of_draft_cadence(monkeypatch,value):
    from apps.api.recall import private_draft_cadence,recall_status
    monkeypatch.setenv('MEMORY_SPARK_FREE_RECALL_ROUNDS',str(value))
    monkeypatch.setenv('MEMORY_SPARK_PRIVATE_DRAFT_CADENCE','3')
    assert free_recall_rounds()==value and private_draft_cadence()==3
    assert recall_status(value-1,None)['payment_required'] is False
    assert recall_status(value,None)['payment_required'] is True
    assert recall_status(value,{'status':'paid'})['payment_required'] is False


@pytest.mark.parametrize('name',['MEMORY_SPARK_FREE_RECALL_ROUNDS','MEMORY_SPARK_PRIVATE_DRAFT_CADENCE'])
@pytest.mark.parametrize('value',['-1','zero','2.5','1000001'])
def test_invalid_allowance_or_cadence_rejected(monkeypatch,name,value):
    from apps.api.recall import private_draft_cadence
    monkeypatch.setenv(name,value)
    with pytest.raises(ValueError,match='positive integer'):
        (free_recall_rounds if name.endswith('RECALL_ROUNDS') else private_draft_cadence)()
