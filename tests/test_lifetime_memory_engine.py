"""Provider-free governed execution contracts for both collector transports."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
import tomllib
from uuid import UUID

import pytest
from pydantic import ValidationError

from apps.api.codex_agent import provider_config
from apps.api.codex_worker_service import CodexWorker, WorkerTurnInput
from apps.api.lifetime_memory_context import build_context, ContextSource, TailCoverage, serialize_packet
from apps.api.lifetime_memory_contracts import ContextBudget, ExecutionFence, IdentityEnvelope, PinnedContinuity
from apps.api.lifetime_memory_engine import (
    GOVERNED_TURN_PROMPT, GovernedCollectorInput, governed_request_overhead,
    governed_request_tokens, run_governed_collector,
)

IDENTITY = IdentityEnvelope(owner_id=UUID(int=1), conversation_id=UUID(int=2), project_id='p')
FENCE = ExecutionFence(identity=IDENTITY, policy_epoch=1, source_revision=1,
    execution_generation=1, phase_revision=0, preference_revision=0, lease_token=UUID(int=3))
BUDGET = ContextBudget(model='synthetic-byte-bpe', context_window=40000,
    input_budget=30000, output_headroom=4000)
TEXT = 'I carried a blue umbrella in Sydney.'


def fixture():
    source = ContextSource(identity=IDENTITY, policy_epoch=1, source_id=UUID(int=4),
        version=1, sequence=1, original=TEXT, language='en-AU')
    context = {'source': {'id': str(source.source_id), 'version': 1, 'text': TEXT, 'status': 'active'},
        'sources': [], 'events': [], 'photo_context': [], 'interview_language': 'en-AU'}
    packet = build_context(identity=IDENTITY, policy_epoch=1,
        pinned=PinnedContinuity(preference_revision=0, language='en-AU'),
        instructions='Use only authorized narrator evidence.', current=source,
        tail=[], retrieved=[], budget=BUDGET, tail_coverage=TailCoverage(identity=IDENTITY,
            policy_epoch=1, after_sequence=0, through_sequence=0, complete=True))
    packet.update(fence=FENCE.model_dump(mode='json'), model=BUDGET.model, prompt_version='lifetime-v1',
        interview_context={k:v for k,v in context.items() if k not in {'source', 'sources'}})
    return encode(packet), context


def encode(packet, **kwargs):
    packet = deepcopy(packet)
    for _ in range(8):
        count = BUDGET.count(serialize_packet(packet))
        if count == packet['input_tokens_upper_bound']:
            break
        packet['input_tokens_upper_bound'] = count
    return GovernedCollectorInput(packet=serialize_packet(packet), fence=FENCE,
        budget=BUDGET, prompt_version='lifetime-v1', **kwargs)


def valid_reply():
    return json.dumps({'acknowledgement': 'You remember that blue umbrella.',
        'plan': {'candidates': [{'id':'q1', 'question':'Where did you carry it?',
            'context': {'event_id':None, 'photo_id':None, 'life_stage':None, 'year':None},
            'order':0, 'bridge':''}], 'chosen_id':'q1', 'active_event_id':None},
        'associations':[], 'response_photo_ids':[], 'stopped':False})


class FakeConnection:
    instances = []
    failure = None
    reply = None

    def __init__(self, command, home, **options):
        self.command, self.home, self.options = command, Path(home), options
        self.requests, self.turns = [], []
        self.instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def request(self, method, params):
        self.requests.append((method, params))
        if self.failure:
            raise self.failure
        return {'thread': {'id':'fresh-thread'}}

    async def turn(self, thread_id, prompt, **options):
        self.turns.append((thread_id, prompt, options))
        return self.reply or valid_reply()


@pytest.fixture(autouse=True)
def reset_fake(monkeypatch):
    monkeypatch.setenv("MEMOIR_LIFETIME_MEMORY","true")
    FakeConnection.instances = []
    FakeConnection.failure = None
    FakeConnection.reply = None
    monkeypatch.delenv('MEMOIR_PUBLICATION_DATABASE_URL', raising=False)
    monkeypatch.delenv('MEMORY_SPARK_COLLECTOR_MODEL', raising=False)
    monkeypatch.delenv('MEMORY_SPARK_COLLECTOR_PROMPT_VERSION', raising=False)


def run(tmp_path, governed=None, context=None, **options):
    default_governed, default_context = fixture()
    options.setdefault('publisher', FakePublisher())
    options.setdefault('connection_factory', FakeConnection)
    return asyncio.run(run_governed_collector(command=['fake-codex'], home_root=tmp_path,
        base_url='http://provider.invalid/v1', api_key='transient-test-secret', model=BUDGET.model,
        governed=governed or default_governed, interview_context=context or default_context,
        **options))


def test_governed_config_disables_both_memory_paths_without_changing_legacy():
    legacy = tomllib.loads(provider_config('http://provider.invalid/v1', BUDGET.model))
    governed = tomllib.loads(provider_config('http://provider.invalid/v1', BUDGET.model, governed=True))
    assert legacy['features']['memories'] is True
    assert legacy['memories'] == {'generate_memories':True, 'use_memories':True}
    assert governed['features']['memories'] is False
    assert governed['memories'] == {'generate_memories':False, 'use_memories':False}


def test_fresh_turn_uses_exact_packet_once_and_no_secret_or_old_home(tmp_path):
    governed, context = fixture()
    old_home = tmp_path / str(IDENTITY.owner_id)
    old_home.mkdir()
    (old_home / 'MEMORY.md').write_text('WITHDRAWN PRIVATE FACT')
    result = run(tmp_path, governed, context, thread_id='old-thread')
    connection = FakeConnection.instances[-1]
    assert [m for m,_ in connection.requests] == ['thread/start']
    assert connection.requests[0][1]['baseInstructions'] == governed.packet
    assert connection.requests[0][1]['ephemeral'] is True
    assert connection.turns[0][1] == GOVERNED_TURN_PROMPT
    assert TEXT not in connection.turns[0][1]
    assert connection.requests[0][1]['baseInstructions'].count(TEXT) == 1
    assert connection.home != old_home
    assert str(IDENTITY.conversation_id) in connection.home.name
    assert 'epoch-1' in connection.home.name and 'generation-1' in connection.home.name
    assert not (connection.home / 'MEMORY.md').exists()
    assert 'transient-test-secret' not in (connection.home / 'config.toml').read_text()
    assert connection.options['provider_env']['MEMORY_SPARK_LLM_API_KEY'] == 'transient-test-secret'
    assert result['thread_id'] == 'fresh-thread' and result['artifacts'] == []
    assert result['cold_resume_reason'] == 'unvalidated_transcript'
    assert (old_home / 'MEMORY.md').read_text() == 'WITHDRAWN PRIVATE FACT'


def test_each_turn_has_new_home_even_for_same_fence(tmp_path):
    run(tmp_path)
    run(tmp_path)
    assert FakeConnection.instances[0].home != FakeConnection.instances[1].home


@pytest.mark.parametrize('changes', [
    {'text':TEXT}, {'memories':['private']}, {'profile':{'name':'private'}},
    {'place_journey':{'places':['private']}}, {'family_context':{'people':['private']}},
    {'agent_role':'workspace'}, {'project_id':'other'}, {'user_id':UUID(int=999)},
    {'conversation_rounds_completed':40}, {'task_sources':[{'id':'s', 'text':'private'}]},
])
def test_worker_rejects_mixed_legacy_or_foreign_governed_payload(changes):
    governed, context = fixture()
    args = dict(user_id=IDENTITY.owner_id, project_id='p', governed=governed,
        interview_context=context, model=BUDGET.model)
    args.update(changes)
    with pytest.raises((ValueError, ValidationError)):
        WorkerTurnInput(**args)


def test_worker_requires_governed_context_and_exact_source():
    governed, context = fixture()
    for bad_context in (None, {**context, 'source':{**context['source'], 'text':'other'}}):
        with pytest.raises((ValueError, ValidationError)):
            WorkerTurnInput(user_id=IDENTITY.owner_id, governed=governed,
                interview_context=bad_context, model=BUDGET.model)


@pytest.mark.parametrize('field,value', [
    ('model', 'unknown-model'), ('prompt_version', 'stale-prompt'),
    ('policy_epoch', 2), ('input_tokens_upper_bound', 1),
])
def test_governed_packet_rejects_incompatible_or_false_metadata(field, value):
    governed,_ = fixture()
    packet = json.loads(governed.packet)
    packet[field] = value
    with pytest.raises((ValueError, ValidationError)):
        GovernedCollectorInput(packet=serialize_packet(packet), fence=FENCE, budget=BUDGET,
            prompt_version='lifetime-v1')


def test_governed_packet_rejects_mismatched_fence_and_duplicate_narrator():
    governed,_ = fixture()
    packet = json.loads(governed.packet)
    packet['fence']['source_revision'] += 1
    with pytest.raises((ValueError, ValidationError)):
        encode(packet)
    packet = json.loads(governed.packet)
    packet['retrieved'] = [packet['current']['narrator']]
    with pytest.raises((ValueError, ValidationError)):
        encode(packet)


def test_governed_packet_rejects_unsupported_tokenizer_model():
    governed,_ = fixture()
    packet = json.loads(governed.packet)
    packet['model'] = 'arbitrary-provider'
    budget = BUDGET.model_copy(update={'model':'arbitrary-provider'})
    with pytest.raises((ValueError, ValidationError)):
        GovernedCollectorInput(packet=serialize_packet(packet), fence=FENCE, budget=budget,
            prompt_version='lifetime-v1')


def test_actual_schema_prompt_and_framing_are_in_budget(tmp_path):
    governed, context = fixture()
    overhead = governed_request_overhead(context, BUDGET)
    assert overhead > BUDGET.framing_headroom + len(GOVERNED_TURN_PROMPT)
    total = governed_request_tokens(governed.packet, context, BUDGET)
    assert total == BUDGET.count(governed.packet) + overhead
    tight_budget = BUDGET.model_copy(update={'input_budget':total-1})
    tight = governed.model_copy(update={'budget':tight_budget})
    with pytest.raises(ValueError, match='budget'):
        run(tmp_path, tight, context)
    assert not FakeConnection.instances


def test_side_context_never_adds_unbudgeted_or_foreign_evidence(tmp_path):
    governed, context = fixture()
    context['events'] = [{'id':'foreign', 'status':'active'}]
    with pytest.raises(ValueError, match='context'):
        run(tmp_path, governed, context)
    assert not FakeConnection.instances


@pytest.mark.parametrize('error', [PermissionError('auth'), TimeoutError('timeout'), RuntimeError('provider')])
def test_provider_errors_never_become_missing_state_or_trigger_retry(tmp_path, error):
    FakeConnection.failure = error
    with pytest.raises(type(error)):
        run(tmp_path, thread_id='old')
    assert len(FakeConnection.instances) == 1
    assert len(FakeConnection.instances[0].requests) == 1


def test_invalid_structured_response_is_not_retried_on_unbounded_transcript(tmp_path):
    FakeConnection.reply = '{"acknowledgement":"bad"}'
    with pytest.raises(RuntimeError, match='validated'):
        run(tmp_path)
    assert len(FakeConnection.instances[0].turns) == 1


def test_worker_uses_same_governed_engine_and_no_artifact_export(tmp_path, monkeypatch):
    import apps.api.codex_worker_service as worker_module
    monkeypatch.setenv('MEMORY_SPARK_DISABLE_PRIVDROP','1')
    monkeypatch.setattr(worker_module, 'CodexConnection', FakeConnection)
    import apps.api.lifetime_memory_engine as engine_module
    def publication_factory(dsn, *, authenticated_owner):
        # Replace only the server's connector constructor; no secret/config read.
        assert dsn is None and authenticated_owner == IDENTITY.owner_id
        return FakePublisher()
    monkeypatch.setattr(engine_module, 'TransactionalPublication', publication_factory)
    monkeypatch.setattr(worker_module, 'iter_artifacts', lambda home: pytest.fail('governed artifact export'))
    governed, context = fixture()
    worker = CodexWorker(home_root=tmp_path, model=BUDGET.model, api_key='transient-test-secret')
    payload = WorkerTurnInput(user_id=IDENTITY.owner_id, project_id='p', model=BUDGET.model,
        thread_id='legacy-thread', governed=governed, interview_context=context)
    result = asyncio.run(worker.turn(payload))
    assert result['reply'] == valid_reply()
    connection = FakeConnection.instances[-1]
    assert connection.requests[0][1]['baseInstructions'] == governed.packet
    assert connection.turns[0][1] == GOVERNED_TURN_PROMPT
    assert result['artifacts'] == []
    assert not (tmp_path / str(IDENTITY.owner_id)).exists()


def test_governed_config_excludes_inherited_project_docs():
    governed = tomllib.loads(provider_config('http://provider.invalid/v1', BUDGET.model, governed=True))
    legacy = tomllib.loads(provider_config('http://provider.invalid/v1', BUDGET.model))
    assert governed['project_doc_max_bytes'] == 0
    assert 'project_doc_max_bytes' not in legacy


def test_worker_rechecks_mutated_payload_before_dispatch(tmp_path, monkeypatch):
    import apps.api.codex_worker_service as worker_module
    monkeypatch.setenv('MEMORY_SPARK_DISABLE_PRIVDROP','1')
    monkeypatch.setattr(worker_module, 'CodexConnection', FakeConnection)
    governed, context = fixture()
    payload = WorkerTurnInput(user_id=IDENTITY.owner_id, governed=governed,
        interview_context=context, model=BUDGET.model)
    payload = payload.model_copy(update={'user_id':UUID(int=999)})
    with pytest.raises(ValueError):
        asyncio.run(CodexWorker(home_root=tmp_path, model=BUDGET.model).turn(payload))
    assert not FakeConnection.instances


def test_worker_rejects_unknown_prior_context_in_governed_request():
    governed, context = fixture()
    with pytest.raises(ValueError):
        WorkerTurnInput(user_id=IDENTITY.owner_id, governed=governed,
            interview_context=context, model=BUDGET.model, prior=['secret older exchange'])


def test_side_context_cannot_override_pinned_language_or_phase(tmp_path):
    governed, context = fixture()
    raw = json.loads(governed.packet)
    context['interview_language'] = 'zh-CN'
    raw['interview_context']['interview_language'] = 'zh-CN'
    changed = encode(raw)
    with pytest.raises(ValueError, match='language'):
        run(tmp_path, changed, context)
    assert not FakeConnection.instances


def test_unknown_model_fails_before_creating_any_home(tmp_path):
    governed, context = fixture()
    with pytest.raises(ValueError, match='model'):
        asyncio.run(run_governed_collector(command=['fake'], home_root=tmp_path,
            base_url='http://provider.invalid', api_key='secret', model='different-model',
            governed=governed, interview_context=context, connection_factory=FakeConnection))
    assert not list(tmp_path.iterdir()) and not FakeConnection.instances


def test_duplicate_json_keys_cannot_hide_extra_narrator_context():
    governed,_ = fixture()
    raw = governed.packet[:-1] + ',"instructions":"hidden prior material"}'
    with pytest.raises(ValueError):
        GovernedCollectorInput(packet=raw, fence=FENCE, budget=BUDGET, prompt_version='lifetime-v1')


def test_corrupt_fresh_start_is_explicit_and_never_retried(tmp_path, monkeypatch):
    from apps.api.lifetime_memory_execution import ExecutionStateUnavailable
    async def corrupt(self, method, params):
        self.requests.append((method, params))
        return {'thread':{}}
    monkeypatch.setattr(FakeConnection,'request',corrupt)
    with pytest.raises(ExecutionStateUnavailable) as error:
        run(tmp_path, thread_id='old-state')
    assert error.value.reason == 'corrupt'
    assert len(FakeConnection.instances[0].requests) == 1
    assert FakeConnection.instances[0].turns == []


def test_output_schema_context_is_used_but_not_serialized_twice(tmp_path):
    governed, context = fixture()
    packet = json.loads(governed.packet)
    context['historical_news'] = {'enabled':True, 'clues':[{'id':'public'}]}
    packet['interview_context']['historical_news'] = context['historical_news']
    governed = encode(packet)
    FakeConnection.reply = valid_reply().replace('You remember that blue umbrella.',
        'We can keep following your memories at your pace.')
    run(tmp_path, governed, context)
    connection = FakeConnection.instances[0]
    assert connection.turns[0][2]['output_schema']['properties']['acknowledgement']['enum'] == [
        'We can keep following your memories at your pace.']
    assert 'historical_news' not in connection.turns[0][1]


class FakePublisher:
    def __init__(self, *, current_fence=None, timeout=1):
        self.current_fence = deepcopy(current_fence or FENCE.model_dump(mode='json'))
        self.lock = asyncio.Lock()
        self.snapshots = []
        self.active = False
        self.timeout = timeout

    def guard(self, fence):
        from contextlib import asynccontextmanager
        @asynccontextmanager
        async def guarded():
            async with self.lock:
                if fence != self.current_fence:
                    raise RuntimeError('stale admission fence')
                self.snapshots.append(deepcopy(fence))
                self.active = True
                try:
                    async with asyncio.timeout(self.timeout):
                        yield
                finally:
                    self.active = False
        return guarded()


def protocol_connection(tmp_path, publisher, *, block_drain=False, block_response=False):
    from types import SimpleNamespace
    from apps.api.codex_agent import CodexConnection
    fence = deepcopy(FENCE.model_dump(mode='json'))
    connection = CodexConnection(['fake'],tmp_path,request_admission=lambda:publisher.guard(fence))
    writes = []
    draining, release_drain, receiving, release_response = (asyncio.Event() for _ in range(4))
    if not block_drain:
        release_drain.set()
    if not block_response:
        release_response.set()
    def write(data):
        writes.append((json.loads(data),publisher.active))
    async def drain():
        draining.set()
        await release_drain.wait()
    async def receive():
        receiving.set()
        await release_response.wait()
        assert not publisher.active, 'admission lock must not cover response/generation'
        return {'id':connection.sequence, 'result':{'thread':{'id':'fresh'}}}
    connection.process = SimpleNamespace(stdin=SimpleNamespace(write=write,drain=drain))
    connection.receive = receive
    return connection,writes,draining,release_drain,receiving,release_response


@pytest.mark.parametrize('method',['thread/start','turn/start'])
def test_stale_correction_before_protocol_write_rejects_all_bytes(tmp_path,method):
    async def scenario():
        publisher = FakePublisher()
        publisher.current_fence['policy_epoch'] += 1
        connection,writes,*_ = protocol_connection(tmp_path,publisher)
        with pytest.raises(RuntimeError,match='stale admission'):
            await connection.request(method,{'baseInstructions':'private canonical packet'})
        assert writes == [] and not publisher.active
    asyncio.run(scenario())


def test_admission_covers_drain_but_releases_before_waiting_for_response(tmp_path):
    async def scenario():
        publisher = FakePublisher()
        connection,writes,draining,release_drain,receiving,release_response = protocol_connection(
            tmp_path,publisher,block_drain=True,block_response=True)
        request = asyncio.create_task(connection.request('thread/start',{'baseInstructions':'packet'}))
        await draining.wait()
        assert publisher.active and writes[0][1] is True
        correction_waiting,corrected = asyncio.Event(),asyncio.Event()
        async def correct():
            correction_waiting.set()
            async with publisher.lock:
                publisher.current_fence['policy_epoch'] += 1
                corrected.set()
        correction = asyncio.create_task(correct())
        await correction_waiting.wait()
        assert not corrected.is_set()
        release_drain.set()
        await receiving.wait()
        await corrected.wait()
        assert not request.done() and not publisher.active
        release_response.set()
        await request
        await correction
        with pytest.raises(RuntimeError,match='stale admission'):
            await connection.request('turn/start',{'threadId':'fresh','input':[]})
        assert len(writes) == 1
    asyncio.run(scenario())


def test_admission_timeout_releases_guard_without_awaiting_response(tmp_path):
    async def scenario():
        publisher = FakePublisher(timeout=.01)
        connection,writes,_,_,receiving,_ = protocol_connection(tmp_path,publisher,block_drain=True)
        with pytest.raises(TimeoutError):
            await connection.request('turn/start',{'threadId':'fresh','input':[]})
        assert len(writes) == 1 and not publisher.active and not publisher.lock.locked()
        assert not receiving.is_set()
    asyncio.run(scenario())


def test_protocol_control_messages_do_not_acquire_personal_admission(tmp_path):
    async def scenario():
        publisher = FakePublisher()
        connection,writes,*_ = protocol_connection(tmp_path,publisher)
        await connection.send({'method':'initialized','params':{}})
        await connection.send({'id':999,'error':{'code':-32601,'message':'disabled'}})
        assert publisher.snapshots == []
        assert all(active is False for _,active in writes)
    asyncio.run(scenario())


def test_governed_worker_fails_closed_without_server_publication_database(tmp_path,monkeypatch):
    import apps.api.codex_worker_service as worker_module
    from apps.api.lifetime_memory_publication import PublicationUnavailable
    monkeypatch.delenv('MEMOIR_PUBLICATION_DATABASE_URL',raising=False)
    monkeypatch.setenv('MEMORY_SPARK_DISABLE_PRIVDROP','1')
    monkeypatch.setattr(worker_module,'CodexConnection',FakeConnection)
    governed,context = fixture()
    payload = WorkerTurnInput(user_id=IDENTITY.owner_id,governed=governed,model=BUDGET.model,
        interview_context=context)
    with pytest.raises(PublicationUnavailable):
        asyncio.run(CodexWorker(home_root=tmp_path,model=BUDGET.model).turn(payload))
    assert not FakeConnection.instances
    assert not list(tmp_path.glob('governed-*'))


def test_engine_passes_exact_fence_snapshot_to_actual_request_admission(tmp_path):
    async def scenario():
        publisher = FakePublisher()
        governed,context = fixture()
        await run_governed_collector(command=['fake'],home_root=tmp_path,
            base_url='http://provider.invalid',api_key='transient-secret',model=BUDGET.model,
            governed=governed,interview_context=context,publisher=publisher,
            connection_factory=FakeConnection)
        admission = FakeConnection.instances[0].options['request_admission']
        async with admission():
            assert publisher.active
        assert publisher.snapshots == [FENCE.model_dump(mode='json')]
        publisher.current_fence['source_revision'] += 1
        with pytest.raises(RuntimeError,match='stale admission'):
            async with admission():
                pytest.fail('a changed fence cannot be relabeled')
    asyncio.run(scenario())


def test_governed_continuity_schema_is_budgeted_and_current_proposal_is_validated(tmp_path):
    governed,context = fixture()
    reply = json.loads(valid_reply())
    start = TEXT.index('blue umbrella')
    reply['continuity_updates'] = [{
        'kind':'unresolved_reference', 'text':'blue umbrella', 'assertion':'asserted',
        'uncertainty':None, 'source_id':str(UUID(int=4)), 'source_version':1,
        'char_start':start, 'char_end':start+len('blue umbrella'), 'quote':'blue umbrella',
    }]
    FakeConnection.reply = json.dumps(reply)
    result = run(tmp_path,governed,context)
    assert json.loads(result['reply'])['continuity_updates'] == reply['continuity_updates']
    schema = FakeConnection.instances[0].turns[0][2]['output_schema']
    assert 'continuity_updates' in schema['properties']
    assert 'continuity_updates' in schema['required']
    assert governed_request_overhead(context,BUDGET) == (
        BUDGET.count(GOVERNED_TURN_PROMPT) + BUDGET.count(serialize_packet(schema))
        + BUDGET.framing_headroom)


@pytest.mark.parametrize('changes',[{'context_window':131073},{'input_budget':65537,'context_window':131072}])
def test_collector_transport_cannot_expand_reviewed_input_bound(changes):
    governed,_=fixture();raw=governed.model_dump(mode='json');raw['budget'].update(changes)
    with pytest.raises(ValueError,match='reviewed'):GovernedCollectorInput.model_validate(raw)


def test_production_collector_transport_cannot_shrink_protocol_framing():
    governed,_=fixture();raw=governed.model_dump(mode='json')
    raw['budget']['model']='gpt-5.6-luna-pooled';raw['budget']['framing_headroom']=2047
    packet=json.loads(raw['packet']);packet['model']=raw['budget']['model']
    for _ in range(8):
        count=len(serialize_packet(packet).encode())
        if count==packet['input_tokens_upper_bound']:break
        packet['input_tokens_upper_bound']=count
    raw['packet']=serialize_packet(packet)
    with pytest.raises(ValueError,match='reviewed'):GovernedCollectorInput.model_validate(raw)


def test_disabled_rollout_blocks_governed_collector_before_home(tmp_path,monkeypatch):
    from apps.api.lifetime_memory_lane_engine import LaneGenerationPaused
    monkeypatch.setenv('MEMOIR_LIFETIME_MEMORY','false')
    with pytest.raises(LaneGenerationPaused):run(tmp_path)
    assert not FakeConnection.instances and not list(tmp_path.iterdir())


def test_collector_rollout_rechecked_inside_actual_pipe_admission(tmp_path,monkeypatch):
    from contextlib import asynccontextmanager
    from apps.api.lifetime_memory_lane_engine import LaneGenerationPaused
    class PausingPublisher(FakePublisher):
        @asynccontextmanager
        async def guard(self,fence):
            async with super().guard(fence):
                monkeypatch.setenv('MEMOIR_LIFETIME_MEMORY','false')
                yield
    class AdmittedConnection(FakeConnection):
        async def request(self,method,params):
            async with self.options['request_admission']():
                return await super().request(method,params)
    with pytest.raises(LaneGenerationPaused):run(tmp_path,publisher=PausingPublisher(),connection_factory=AdmittedConnection)
    assert FakeConnection.instances[0].requests==[]
