"""Provider-free recorder/readback regressions; all content is synthetic."""
import json
import pytest
import asyncio
import httpx
import sys

from apps.api.codex_agent import CodexConnection

from test_memoir_postgres_runtime_readback import (
    DeterministicWorker, OfflineStorage, assert_workspace_persisted,
    round_environment, run_round,
)

from apps.api.trajectory_evaluation import TrajectoryRecorder
from scripts.issue14_subscription_runner import SubscriptionRunnerError, _runtime_readback


def result_for(recorder):
    return {'reply': 'Synthetic reply', 'accepted_source_id': 'synthetic-source',
            'tasks': [], 'task_errors': [], 'trace': [], 'trajectory': recorder.payload()}


def test_noisy_protocol_keeps_tool_persistence_and_terminal_evidence_complete():
    recorder = TrajectoryRecorder({'run_id': 'synthetic-run', 'case_id': 'synthetic-case'})
    recorder.record('application', 'turn.received')
    recorder.record_protocol({'method': 'item/started', 'params': {'item': {
        'id': 'synthetic-tool', 'type': 'mcpToolCall', 'name': 'memory.search',
        'arguments': {'query': 'synthetic'}, 'status': 'inProgress'}}})
    for _ in range(994):
        recorder.record_protocol({'method': 'item/agentMessage/delta', 'params': {
            'threadId': 'synthetic-thread', 'turnId': 'synthetic-turn',
            'itemId': 'synthetic-message', 'delta': 'synthetic text'}})
    recorder.record_protocol({'method': 'item/completed', 'params': {'item': {
        'id': 'synthetic-tool', 'type': 'mcpToolCall', 'name': 'memory.search',
        'status': 'completed', 'result': {'count': 1}}}})
    recorder.record('application', 'memory.persist', output={'count': 1})
    recorder.record_protocol({'method': 'turn/completed', 'params': {
        'turn': {'id': 'synthetic-turn', 'status': 'completed'}}})
    recorder.finish('Synthetic reply', state={'task_statuses': ['completed']})

    _runtime_readback(result_for(recorder), recorder.correlation)
    payload = recorder.payload()
    assert [step['action'] for step in payload['steps']] == [
        'turn.received', 'item/started', 'item/completed', 'memory.persist', 'turn/completed']
    assert payload['limits']['dropped_steps'] == 0
    assert payload['telemetry']['compacted_events'] == 994
    assert payload['telemetry']['omitted_payloads'] == 994
    assert len(json.dumps(payload)) < 10000


def test_worker_import_preserves_telemetry_and_rejects_worker_audit_overflow():
    worker = TrajectoryRecorder(max_steps=1)
    for _ in range(994):
        worker.record_protocol({'method': 'item/reasoning/textDelta',
                                'params': {'delta': 'private synthetic reasoning'}})
    worker.record('codex', 'tool.call', input={'name': 'memory.search'})
    worker.record('codex', 'tool.result', output={'status': 'completed'})
    worker.finish('Synthetic reply')
    outer = TrajectoryRecorder({'run_id': 'synthetic-run'})
    outer.append_trajectory(worker.payload(), source='codex-worker')
    outer.record('application', 'memory.persist', output={'count': 1})
    outer.finish('Synthetic reply')

    payload = outer.payload()
    assert payload['telemetry']['compacted_events'] == 994
    assert 'private synthetic reasoning' not in json.dumps(payload)
    assert payload['limits']['dropped_steps'] == 1
    assert payload['limits']['overflowed'] is True
    assert payload['overflow']['dropped_by_category'] == {'external': 1}
    assert any(step['action'] == 'memory.persist' for step in payload['steps'])
    with pytest.raises(SubscriptionRunnerError) as caught:
        _runtime_readback(result_for(outer), outer.correlation)
    assert caught.value.readback_diagnostic['predicate'] == 'trajectory_overflow'


class NoisyWorker(DeterministicWorker):
    """Synthetic model evidence injected solely at the worker HTTP boundary."""
    def __init__(self, *, audit_overflow=False, accounting_fault=None):
        super().__init__()
        self.audit_overflow = audit_overflow
        self.accounting_fault = accounting_fault

    def handle(self, request):
        response = super().handle(request)
        body = json.loads(request.content)
        if not body.get('evaluation'):
            return response  # The canonical extractor has no turn recorder.
        recorder = TrajectoryRecorder(body['evaluation'], max_steps=1 if self.audit_overflow else 512)
        recorder.record_protocol({'method': 'item/started', 'params': {'item': {
            'id': 'synthetic-tool', 'type': 'mcpToolCall', 'tool': 'memory.search',
            'status': 'inProgress'}}})
        for _ in range(994):
            recorder.record_protocol({'method': 'item/agentMessage/delta',
                                      'params': {'delta': 'synthetic chunk'}})
        if self.audit_overflow:
            for _ in range(2):
                recorder.record('codex', 'tool.call', input={'name': 'memory.search'})
        recorder.record_protocol({'method': 'item/completed', 'params': {'item': {
            'id': 'synthetic-tool', 'type': 'mcpToolCall', 'tool': 'memory.search',
            'status': 'completed'}}})
        recorder.record_protocol({'method': 'turn/completed', 'params': {
            'turn': {'id': 'synthetic-turn', 'status': 'completed'}}})
        recorder.finish('Synthetic reply')
        evidence = recorder.payload()
        if self.accounting_fault:
            evidence[self.accounting_fault] = None
        if request.headers.get('accept') != 'application/x-ndjson':
            return httpx.Response(200, json={**response.json(), 'trajectory': evidence})
        events = [json.loads(line) for line in response.text.splitlines()]
        for event in events:
            if event['type'] in ('provider_complete', 'result'):
                event['data']['trajectory'] = evidence
        return httpx.Response(200, content=''.join(json.dumps(event) + '\n' for event in events),
                              headers={'content-type': 'application/x-ndjson'})


@pytest.mark.parametrize('streaming', [False, True])
def test_full_runtime_preserves_noisy_worker_accounting_and_verified_persistence(
        round_environment, tmp_path, streaming):
    storage, worker = OfflineStorage(), NoisyWorker()
    result, correlation = asyncio.run(run_round(storage, worker, streaming=streaming, tmp_path=tmp_path))
    assert_workspace_persisted(result, storage, round_environment, family=True)
    _runtime_readback(result, correlation)
    assert result['trajectory']['telemetry']['compacted_events'] == 1988
    assert result['trajectory']['limits']['overflowed'] is False
    actions = [step['action'] for step in result['trajectory']['steps']]
    assert actions.count('item/completed') == 2
    assert 'memory.persist' in actions and 'place_journey.persist' in actions


@pytest.mark.parametrize('streaming', [False, True])
def test_full_runtime_cannot_hide_worker_audit_overflow(round_environment, tmp_path, streaming):
    result, correlation = asyncio.run(run_round(OfflineStorage(), NoisyWorker(audit_overflow=True),
                                                streaming=streaming, tmp_path=tmp_path))
    assert result['trajectory']['limits']['dropped_steps'] > 0
    with pytest.raises(SubscriptionRunnerError, match='background_incomplete'):
        _runtime_readback(result, correlation)


@pytest.mark.parametrize('message', [
    {'method': ['item/agentMessage/delta'], 'params': {'delta': 'synthetic'}},
    {'method': 'item/agentMessage/delta', 'id': 1, 'params': {'delta': 'synthetic'}},
    {'method': 'item/agentMessage/delta', 'error': {'code': 1}, 'params': {'delta': 'synthetic'}},
    {'method': 'item/agentMessage/delta', 'params': {'delta': 'synthetic', 'status': 'failed'}},
    {'method': 'item/agentMessage/delta', 'params': {'delta': 'synthetic', 'retryable': True}},
    {'method': 'item/agentMessage/delta', 'params': {'delta': 'synthetic', 'pending': True}},
    {'method': 'item/agentMessage/delta', 'params': {'delta': 'synthetic', 'item': {'status': 'failed'}}},
    {'method': 'item/agentMessage/delta', 'params': {'delta': {'text': 'synthetic'}}},
    {'method': 'item/agentMessage/delta', 'params': {'delta': 'synthetic', 'itemId': []}},
    {'method': 'item/agentMessage/delta', 'params': {'delta': 'synthetic', 'itemId': 1}},
    {'method': 'item/reasoning/textDelta', 'params': {'delta': 'synthetic', 'contentIndex': -1}},
    {'method': 'item/reasoning/textDelta', 'params': {'delta': 'synthetic', 'contentIndex': 'failed'}},
    {'method': 'item/unknown/delta', 'params': {'delta': 'synthetic'}},
    {'method': 'item/agentMessage/delta', 'jsonrpc': 'unknown', 'params': {'delta': 'synthetic'}},
])
def test_unrecognized_or_suspicious_delta_evidence_never_bypasses_audit_budget(message):
    recorder = TrajectoryRecorder(max_steps=1)
    recorder.record_protocol(message)
    recorder.record_protocol(message)
    recorder.finish('Synthetic reply')
    payload = recorder.payload()
    assert len(payload['steps']) == 1
    assert payload['limits']['dropped_steps'] == 1
    assert 'telemetry' not in payload
    with pytest.raises(SubscriptionRunnerError):
        _runtime_readback(result_for(recorder), {})


def test_malformed_worker_trajectory_fails_closed():
    recorder = TrajectoryRecorder()
    recorder.append_trajectory(['synthetic'], source='worker')
    recorder.finish('Synthetic reply')
    with pytest.raises(SubscriptionRunnerError):
        _runtime_readback(result_for(recorder), {})


@pytest.mark.parametrize('method', [
    'item/agentMessage/delta', 'item/commandExecution/outputDelta',
    'item/reasoning/summaryTextDelta', 'item/reasoning/textDelta',
])
def test_transport_flood_uses_fixed_counts_without_text_identifiers_or_reasoning(method):
    recorder = TrajectoryRecorder(max_steps=2)
    recorder.record('application', 'turn.received')
    for index in range(25000):
        recorder.record_protocol({'method': method, 'params': {
            'itemId': f'private-synthetic-item-{index}', 'delta': 'private-synthetic-text'}})
    recorder.record('application', 'memory.persist', output={'count': 1})
    recorder.finish('Synthetic reply')
    payload = recorder.payload()
    assert payload['telemetry']['by_method'] == {method: 25000}
    assert payload['telemetry']['omitted_payloads'] == 25000
    assert payload['limits']['dropped_steps'] == 0
    assert 'private-synthetic' not in json.dumps(payload)
    assert len(json.dumps(payload)) < 4000
    _runtime_readback(result_for(recorder), {})


@pytest.mark.parametrize('queued', [False, True])
@pytest.mark.parametrize('failed', [False, True])
def test_protocol_records_each_notification_once_without_deduplicating_real_tool_calls(tmp_path, queued, failed):
    # A fake stdio server controls arrival timing at the actual protocol seam.
    # Identical lifecycle notifications are distinct observations, not retries
    # to discard by matching their payload or item ID.
    script = tmp_path / 'synthetic_appserver.py'
    script.write_text('''import json,sys
def send(value):
    print(json.dumps(value), flush=True)
for line in sys.stdin:
    message = json.loads(line)
    if message['method'] == 'initialize':
        send({'id': message['id'], 'result': {}})
    elif message['method'] == 'turn/start':
        notification = {'method': 'item/completed', 'params': {
            'threadId': 'synthetic-thread', 'turnId': 'synthetic-turn',
            'item': {'id': 'synthetic-command', 'type': 'commandExecution',
                     'status': 'failed' if sys.argv[2] == 'failed' else 'completed',
                     'exitCode': 1 if sys.argv[2] == 'failed' else 0}}}
        if sys.argv[1] == 'queued':
            send(notification)
            send(notification)
            send({'method': 'item/agentMessage/delta', 'params': {
                'threadId': 'synthetic-thread', 'turnId': 'synthetic-turn',
                'itemId': 'synthetic-message', 'delta': 'Synthetic reply'}})
        send({'id': message['id'], 'result': {'turn': {'id': 'synthetic-turn'}}})
        if sys.argv[1] != 'queued':
            send(notification)
            send(notification)
            send({'method': 'item/agentMessage/delta', 'params': {
                'threadId': 'synthetic-thread', 'turnId': 'synthetic-turn',
                'itemId': 'synthetic-message', 'delta': 'Synthetic reply'}})
        send({'method': 'item/completed', 'params': {
            'threadId': 'synthetic-thread', 'turnId': 'synthetic-turn',
            'item': {'id': 'synthetic-message', 'type': 'agentMessage', 'text': 'Synthetic reply'}}})
        send({'method': 'turn/completed', 'params': {'threadId': 'synthetic-thread',
            'turn': {'id': 'synthetic-turn', 'status': 'completed'}}})
''')
    recorder = TrajectoryRecorder()
    async def scenario():
        async with CodexConnection([sys.executable, str(script), 'queued' if queued else 'direct',
                                   'failed' if failed else 'success'],
                                   tmp_path / 'owned-home', trajectory=recorder) as connection:
            return await connection.turn('synthetic-thread', 'Synthetic prompt')
    assert asyncio.run(scenario()) == 'Synthetic reply'
    payload = recorder.payload()
    tools = [step for step in payload['steps'] if step.get('protocol_item_id') == 'synthetic-command']
    assert len(tools) == 2
    assert payload['telemetry']['compacted_events'] == 1
    assert [step['action'] for step in payload['steps']].count('turn/completed') == 1
    recorder.finish('Synthetic reply')
    if failed:
        assert all(step['protocol_failed'] is True for step in tools)
        with pytest.raises(SubscriptionRunnerError):
            _runtime_readback(result_for(recorder), {})
    else:
        _runtime_readback(result_for(recorder), {})


def test_five_worker_aggregate_counts_noise_but_never_hides_audit_loss():
    outer = TrajectoryRecorder(max_steps=10)
    for index in range(5):
        worker = TrajectoryRecorder()
        for _ in range(994):
            worker.record_protocol({'method': 'item/reasoning/textDelta',
                                    'params': {'delta': 'private synthetic reasoning'}})
        worker.record('codex', 'tool.call', input={'name': 'memory.search'})
        worker.record('codex', 'tool.result', output={'status': 'completed'})
        worker.finish('Synthetic reply')
        outer.append_trajectory(worker.payload(), source=f'synthetic-worker-{index}')
    outer.finish('Synthetic reply')
    assert outer.payload()['telemetry']['compacted_events'] == 4970
    _runtime_readback(result_for(outer), {})
    outer.record('application', 'memory.persist', output={'count': 1})
    assert outer.payload()['limits']['dropped_steps'] == 1
    assert outer.payload()['overflow']['dropped_by_category'] == {'application': 1}
    with pytest.raises(SubscriptionRunnerError) as caught:
        _runtime_readback(result_for(outer), {})
    assert caught.value.readback_diagnostic['predicate'] == 'trajectory_overflow'


@pytest.mark.parametrize('mutate', [
    lambda value: value['limits'].update(dropped_steps=1, overflowed=False),
    lambda value: value['limits'].update(observed_steps=10),
    lambda value: value['limits'].update(dropped_steps=True),
    lambda value: value.update(steps=['malformed']),
    lambda value: value.update(telemetry={'by_method': {'unknown-secret-key': 1}}),
    lambda value: value['telemetry'].update(compacted_events=2),
    lambda value: value['telemetry']['by_method'].update({'item/agentMessage/delta': True}),
    lambda value: value['final'].update(status='failed'),
])
def test_malformed_worker_accounting_and_failed_final_remain_rejected(mutate):
    worker = TrajectoryRecorder()
    worker.record('codex', 'tool.call', input={'name': 'memory.search'})
    worker.record_protocol({'method': 'item/agentMessage/delta', 'params': {'delta': 'synthetic'}})
    worker.finish('Synthetic reply')
    payload = worker.payload()
    mutate(payload)
    outer = TrajectoryRecorder()
    outer.append_trajectory(payload, source='worker')
    outer.finish('Synthetic reply')
    with pytest.raises(SubscriptionRunnerError):
        _runtime_readback(result_for(outer), {})
    assert 'unknown-secret-key' not in json.dumps(outer.payload())


@pytest.mark.parametrize('streaming', [False, True])
def test_full_runtime_failure_receipt_preserves_worker_omission_accounting(
        round_environment, tmp_path, streaming):
    class FailingWorker(DeterministicWorker):
        def handle(self, request):
            worker = TrajectoryRecorder(json.loads(request.content)['evaluation'], max_steps=1)
            for _ in range(994):
                worker.record_protocol({'method': 'item/reasoning/textDelta',
                                        'params': {'delta': 'private synthetic reasoning'}})
            worker.record('codex', 'tool.call', input={'name': 'memory.search'})
            worker.record('codex', 'tool.failed', error={'code': 'synthetic'})
            worker.finish(status='failed', error={'error_type': 'SyntheticError'})
            if request.headers.get('accept') != 'application/x-ndjson':
                return httpx.Response(500, json={'error': 'synthetic', 'trajectory': worker.payload()})
            return httpx.Response(200, content=json.dumps({'type': 'error', 'trajectory': worker.payload()}) + '\n',
                                  headers={'content-type': 'application/x-ndjson'})
    with pytest.raises(Exception) as caught:
        asyncio.run(run_round(OfflineStorage(), FailingWorker(), streaming=streaming, tmp_path=tmp_path))
    payload = caught.value.trajectory
    assert payload['final']['status'] == 'failed'
    assert payload['limits']['overflowed'] is True
    assert payload['limits']['dropped_steps'] == 1
    assert payload['telemetry']['compacted_events'] == 994
    assert 'private synthetic reasoning' not in json.dumps(payload)


def test_explicit_null_worker_limits_cannot_erase_dropped_failure_evidence():
    worker = TrajectoryRecorder(max_steps=1)
    worker.record('application', 'memory.persist', output={'count': 1})
    worker.record('codex', 'tool.failed', error={'code': 'synthetic'})
    worker.finish('Synthetic reply')
    payload = worker.payload()
    assert payload['overflow']['dropped_by_category'] == {'tool': 1}
    payload['limits'] = None
    outer = TrajectoryRecorder()
    outer.append_trajectory(payload, source='worker')
    outer.finish('Synthetic reply')
    with pytest.raises(SubscriptionRunnerError):
        _runtime_readback(result_for(outer), {})
    invalid = next(step for step in outer.payload()['steps'] if step['action'] == 'worker.evidence.invalid')
    assert invalid['error'] == {'reason': 'limits_shape'}


@pytest.mark.parametrize('mutate', [
    lambda value: value.update(telemetry=None),
    lambda value: value.update(overflow=None),
    lambda value: value.update(overflow=[]),
    lambda value: value.update(overflow={'dropped_by_category': {'tool': 1}}),
    lambda value: value.update(overflow={'dropped_by_category': {'tool': True}}),
    lambda value: value.update(overflow={'dropped_by_category': {'tool': -1}}),
    lambda value: value.update(overflow={'dropped_by_category': {'private-unknown': 1}}),
    lambda value: value.pop('limits'),
])
def test_present_malformed_accounting_or_missing_limits_with_telemetry_cannot_pass_as_legacy(mutate):
    worker = TrajectoryRecorder()
    worker.record('application', 'memory.persist', output={'count': 1})
    worker.record_protocol({'method': 'item/agentMessage/delta', 'params': {'delta': 'synthetic'}})
    worker.finish('Synthetic reply')
    payload = worker.payload()
    mutate(payload)
    outer = TrajectoryRecorder()
    outer.append_trajectory(payload, source='worker')
    outer.finish('Synthetic reply')
    with pytest.raises(SubscriptionRunnerError):
        _runtime_readback(result_for(outer), {})
    assert any(step['action'] == 'worker.evidence.invalid' for step in outer.payload()['steps'])
    assert 'private-unknown' not in json.dumps(outer.payload())


def test_missing_worker_limits_with_explicit_overflow_witness_is_rejected():
    worker = TrajectoryRecorder(max_steps=1)
    worker.record('application', 'memory.persist', output={'count': 1})
    worker.record('codex', 'tool.failed', error={'code': 'synthetic'})
    worker.finish('Synthetic reply')
    payload = worker.payload()
    payload.pop('limits')
    outer = TrajectoryRecorder()
    outer.append_trajectory(payload, source='worker')
    outer.finish('Synthetic reply')
    with pytest.raises(SubscriptionRunnerError):
        _runtime_readback(result_for(outer), {})
    assert any(step['action'] == 'worker.evidence.invalid' for step in outer.payload()['steps'])


def test_genuine_legacy_step_only_worker_keeps_supported_readback():
    outer = TrajectoryRecorder()
    outer.append_trajectory({'steps': [{'phase': 'application', 'action': 'memory.persist',
                                       'output': {'count': 1}}]}, source='legacy-worker')
    outer.finish('Synthetic reply')
    _runtime_readback(result_for(outer), {})
    assert len(outer.payload()['steps']) == 1


@pytest.mark.parametrize('field', ['limits', 'telemetry', 'overflow'])
@pytest.mark.parametrize('streaming', [False, True])
def test_full_runtime_rejects_explicit_null_worker_accounting(round_environment, tmp_path, field, streaming):
    result, correlation = asyncio.run(run_round(OfflineStorage(), NoisyWorker(accounting_fault=field),
                                                streaming=streaming, tmp_path=tmp_path))
    with pytest.raises(SubscriptionRunnerError):
        _runtime_readback(result, correlation)
    invalid = [step for step in result['trajectory']['steps'] if step['action'] == 'worker.evidence.invalid']
    assert len(invalid) == 2
    assert all(step['error'] == {'reason': field + '_shape'} for step in invalid)


@pytest.mark.parametrize('mutate', [
    lambda value: value.update(limits=None),
    lambda value: value.update(telemetry=None),
])
def test_invalid_worker_accounting_remains_rejected_when_outer_audit_budget_is_full(mutate):
    worker = TrajectoryRecorder()
    worker.record('application', 'memory.persist', output={'count': 1})
    worker.record_protocol({'method': 'item/agentMessage/delta', 'params': {'delta': 'synthetic'}})
    worker.finish('Synthetic reply')
    payload = worker.payload()
    mutate(payload)
    outer = TrajectoryRecorder(max_steps=1)
    outer.append_trajectory(payload, source='worker')
    outer.finish('Synthetic reply')
    assert outer.payload()['limits']['overflowed'] is True
    assert outer.payload()['limits']['dropped_steps'] == 1
    with pytest.raises(SubscriptionRunnerError):
        _runtime_readback(result_for(outer), {})


def test_overflow_histogram_must_match_the_dropped_step_total():
    worker = TrajectoryRecorder(max_steps=1)
    worker.record('application', 'memory.persist', output={'count': 1})
    worker.record('codex', 'tool.failed', error={'code': 'synthetic'})
    worker.finish('Synthetic reply')
    payload = worker.payload()
    payload['overflow']['dropped_by_category'] = {'tool': 2}
    outer = TrajectoryRecorder()
    outer.append_trajectory(payload, source='worker')
    outer.finish('Synthetic reply')
    assert any(step.get('error') == {'reason': 'overflow_shape'} for step in outer.payload()['steps'])
    assert outer.payload()['limits']['dropped_steps'] == 1
    with pytest.raises(SubscriptionRunnerError):
        _runtime_readback(result_for(outer), {})
