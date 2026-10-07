"""Synthetic ledger tests: no application, native service or provider is loaded."""
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading

import pytest

from scripts.fifty_round_budget_contract import build_budget_proposal


def api():
    return importlib.import_module('scripts.fifty_round_dispatch_budget')


def scope():
    proposal = build_budget_proposal(family_enabled=True)
    return {
        'run_id': '00000000-0000-4000-8000-000000000014',
        'case_id': 'synthetic-case', 'owner_id': '00000000-0000-4000-8000-000000000015',
        'project_id': 'synthetic-project', 'source_revision': 'a' * 40,
        'source_tree': 'b' * 40, 'source_sha256': {'fixture.py': 'c' * 64},
        'account_binding': proposal['routing']['account']['proposed_binding_sha256'],
        'roles': {stage: {'model_alias': role['configuration_alias'],
            'wire_model': 'synthetic-model', 'reasoning': role['configuration_reasoning']}
            for stage, role in proposal['routing']['stages'].items()},
    }


class Clock:
    now = 100.0
    def __call__(self): return self.now


@pytest.fixture
def clock(monkeypatch):
    value = Clock()
    monkeypatch.setattr(api(), 'monotonic', value)
    return value


def create(tmp_path, **limits):
    return api().CampaignDispatchBudget.create(reservation_root=tmp_path,
        proposal=build_budget_proposal(family_enabled=True, **limits), scope=scope())


def worker(ledger, **kwargs):
    return ledger.begin_worker(api().WorkerKey(**{'stage': 'collector', 'round_number': 1, **kwargs}))


def reserve(ledger, ticket, ordinal=1):
    return ledger.reserve_send(ticket, continuation_ordinal=ordinal,
        observed_scope=ledger.declared_send_scope(ticket))


def completion(ordinal=1, **kwargs):
    return {'response_id': f'synthetic-response-{ordinal}', 'wire_model': 'synthetic-model',
        'input_tokens': 10, 'output_tokens': 2, **kwargs}


def complete(ledger, ticket, ordinal=1):
    send = reserve(ledger, ticket, ordinal)
    ledger.mark_started(send)
    ledger.settle(send, completion(send.ordinal))
    return send


def test_reservations_and_continuations_share_one_cap_but_not_worker_count(tmp_path, clock):
    ledger = create(tmp_path, max_actual_requests=2)
    ticket = worker(ledger)
    complete(ledger, ticket)
    complete(ledger, ticket, 2)
    with pytest.raises(api().BudgetStopped, match='send_limit'):
        reserve(ledger, ticket, 3)
    receipt = ledger.receipt()
    assert receipt['worker_requests'] == 1
    assert receipt['send_reservations'] == receipt['synthetic_contacts_started'] == 2
    assert receipt['actual_provider_requests'] is None
    assert receipt['live_execution_authorized'] is False
    assert receipt['remaining_send_reservations'] == 0
    assert receipt['evidence_mode'] == 'synthetic'
    ledger.close()


def test_worker_completion_and_declared_scope_are_copied(tmp_path, clock):
    ledger = create(tmp_path)
    ticket = worker(ledger)
    declared = ledger.declared_send_scope(ticket)
    declared['wire_model'] = 'changed'
    assert ledger.declared_send_scope(ticket)['wire_model'] == 'synthetic-model'
    complete(ledger, ticket)
    ledger.finish_worker(ticket)
    ledger.close()
    receipt = ledger.receipt()
    assert receipt['cleanup'] == {'closed': True, 'active_finished': True, 'journal_durable': True}
    assert receipt['completed_sends'] == 1
    assert receipt['synthetic_input_tokens_reported'] == 10
    receipt['workers'][0]['key']['stage'] = 'changed'
    assert ledger.receipt()['workers'][0]['key']['stage'] == 'collector'


def test_live_flags_and_wrongly_typed_scope_cannot_create_ledger(tmp_path):
    proposal = build_budget_proposal(family_enabled=True)
    proposal['live_execution_authorized'] = True
    with pytest.raises(ValueError):
        api().CampaignDispatchBudget.create(reservation_root=tmp_path, proposal=proposal, scope=scope())
    invalid = scope(); invalid['source_sha256']['fixture.py'] = True
    with pytest.raises(ValueError):
        api().CampaignDispatchBudget.create(reservation_root=tmp_path,
            proposal=build_budget_proposal(family_enabled=True), scope=invalid)
    assert list(tmp_path.iterdir()) == []


def test_duplicate_creation_refused_in_another_process_and_after_close(tmp_path):
    ledger = create(tmp_path)
    code = '''import json, sys
from scripts.fifty_round_dispatch_budget import CampaignDispatchBudget, BudgetStopped
try:
    CampaignDispatchBudget.create(reservation_root=sys.argv[1], proposal=json.loads(sys.argv[2]), scope=json.loads(sys.argv[3]))
except BudgetStopped:
    sys.exit(0)
sys.exit(9)
'''
    result = subprocess.run([sys.executable, '-B', '-c', code, str(tmp_path),
        json.dumps(build_budget_proposal(family_enabled=True)), json.dumps(scope())],
        env={'PATH': os.defpath, 'PYTHONPATH': str(Path(__file__).resolve().parents[1])},
        capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr.decode()
    ledger.close()
    with pytest.raises(api().BudgetStopped, match='reservation_exists'):
        create(tmp_path)
    path = tmp_path / (scope()['run_id'] + '.jsonl')
    assert path.stat().st_mode & 0o777 == 0o600
    events = [json.loads(line) for line in path.read_text().splitlines()]
    assert events[0]['event'] == 'created' and events[-1]['event'] == 'closed'


@pytest.mark.skipif(not hasattr(os, 'fork'), reason='POSIX ownership regression')
def test_forked_process_cannot_use_inherited_ledger(tmp_path):
    ledger = create(tmp_path)
    pid = os.fork()
    if pid == 0:
        try:
            worker(ledger)
        except api().BudgetStopped:
            os._exit(0)
        os._exit(9)
    _, status = os.waitpid(pid, 0)
    assert os.waitstatus_to_exitcode(status) == 0
    assert ledger.receipt()['worker_requests'] == 0
    ledger.close()


@pytest.mark.parametrize(('stage', 'fields'), [
    ('collector', {'round_number': True}),
    ('collector', {'round_number': 51}),
    ('collector', {'attempt': 2}),
    ('initial_locale', {'round_number': 2}),
    ('focused_family', {'attempt': 4}),
    ('composer_draft', {'round_number': 5}),
    ('composer_review', {'round_number': 6, 'checkpoint_round': 5}),
    ('event_preparation', {'round_number': 5, 'checkpoint_round': 5}),
    ('collector', {'preparation_id': 'd' * 64}),
    ('judge', {}),
])
def test_invalid_worker_keys_fence_the_run(tmp_path, clock, stage, fields):
    ledger = create(tmp_path)
    with pytest.raises(api().BudgetStopped):
        worker(ledger, **{'stage': stage, **fields})
    with pytest.raises(api().BudgetStopped): worker(ledger)
    assert ledger.receipt()['worker_requests'] == 0
    ledger.close()


def test_worker_replay_cannot_change_correlation_to_reset(tmp_path, clock):
    ledger = create(tmp_path)
    ticket = worker(ledger)
    complete(ledger, ticket); ledger.finish_worker(ticket)
    with pytest.raises(api().BudgetStopped, match='worker_replay'):
        ledger.begin_worker(api().WorkerKey('collector', 1), correlation={'job_id': 'different-job'})
    assert ledger.receipt()['worker_requests'] == 1
    ledger.close()


def test_preparation_replay_is_campaign_wide_and_cap_is_independent(tmp_path, clock):
    ledger = create(tmp_path, max_preparation_requests=1)
    ticket = worker(ledger, stage='event_preparation', round_number=5,
        checkpoint_round=5, preparation_id='d' * 64)
    complete(ledger, ticket); ledger.finish_worker(ticket)
    with pytest.raises(api().BudgetStopped, match='preparation_replay'):
        worker(ledger, stage='event_preparation', round_number=10,
            checkpoint_round=10, preparation_id='d' * 64)
    ledger.close()


def test_new_preparation_fingerprint_consumes_preparation_cap(tmp_path, clock):
    ledger = create(tmp_path, max_preparation_requests=1)
    ticket = worker(ledger, stage='event_preparation', round_number=5,
        checkpoint_round=5, preparation_id='d' * 64)
    complete(ledger, ticket); ledger.finish_worker(ticket)
    with pytest.raises(api().BudgetStopped, match='stage_limit'):
        worker(ledger, stage='event_preparation', round_number=5,
            checkpoint_round=5, preparation_id='e' * 64)
    assert ledger.receipt()['worker_requests_by_stage']['event_preparation'] == 1
    ledger.close()


def test_semantic_repairs_are_sequential_and_count_as_workers(tmp_path, clock):
    ledger = create(tmp_path)
    for attempt in range(1, 4):
        ticket = worker(ledger, stage='focused_family', attempt=attempt)
        complete(ledger, ticket, 1); ledger.finish_worker(ticket)
    assert ledger.receipt()['worker_requests_by_stage']['focused_family'] == 3
    with pytest.raises(api().BudgetStopped): worker(ledger, stage='focused_family', attempt=4)
    ledger.close()


@pytest.mark.parametrize('field', ['run_id', 'case_id', 'owner_id', 'project_id',
    'source_revision', 'source_tree', 'source_sha256', 'account_binding',
    'stage', 'model_alias', 'wire_model', 'reasoning'])
def test_send_scope_mismatch_stops_before_reservation(tmp_path, clock, field):
    ledger = create(tmp_path); ticket = worker(ledger)
    observed = ledger.declared_send_scope(ticket); observed[field] = 'wrong'
    with pytest.raises(api().BudgetStopped, match='send_scope_mismatch'):
        ledger.reserve_send(ticket, continuation_ordinal=1, observed_scope=observed)
    assert ledger.receipt()['send_reservations'] == 0
    ledger.close()


@pytest.mark.parametrize('ordinal', [0, 2, True, 1.0])
def test_continuations_cannot_skip_or_coerce_ordinals(tmp_path, clock, ordinal):
    ledger = create(tmp_path); ticket = worker(ledger)
    with pytest.raises(api().BudgetStopped): reserve(ledger, ticket, ordinal)
    ledger.close()


def test_concurrent_reservations_never_create_two_active_sends(tmp_path):
    ledger = create(tmp_path); ticket = worker(ledger)
    barrier = threading.Barrier(2); accepted = []
    def attempt():
        barrier.wait()
        try: accepted.append(reserve(ledger, ticket))
        except api().BudgetStopped: pass
    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for thread in threads: thread.start()
    for thread in threads: thread.join(5); assert not thread.is_alive()
    assert len(accepted) == 1
    assert ledger.receipt()['send_reservations'] == 1
    assert ledger.receipt()['stop_reason'] is not None
    ledger.close()


@pytest.mark.parametrize('change', [
    {'input_tokens': None}, {'output_tokens': True}, {'output_tokens': -1},
    {'wire_model': 'other'}, {'response_id': ''}, {'extra': 'not-allowed'},
])
def test_invalid_or_unknown_completion_keeps_reservation_and_stops(tmp_path, clock, change):
    ledger = create(tmp_path); ticket = worker(ledger)
    send = reserve(ledger, ticket); ledger.mark_started(send)
    with pytest.raises(api().BudgetStopped): ledger.settle(send, completion(**change))
    receipt = ledger.receipt()
    assert receipt['send_reservations'] == receipt['unsettled_requests'] == 1
    assert receipt['remaining_send_reservations'] == 599
    with pytest.raises(api().BudgetStopped): reserve(ledger, ticket, 2)
    ledger.close()


@pytest.mark.parametrize('reason', ['quota', 'provider_error', 'cancelled', 'usage_unknown'])
def test_failures_and_cancellation_fence_every_later_stage(tmp_path, clock, reason):
    ledger = create(tmp_path); ticket = worker(ledger)
    send = reserve(ledger, ticket); ledger.mark_started(send)
    ledger.fail(send, reason)
    with pytest.raises(api().BudgetStopped): worker(ledger, stage='broad_workspace')
    assert ledger.receipt()['send_reservations'] == 1
    assert ledger.receipt()['actual_provider_requests'] is None
    ledger.close()


def test_request_deadline_and_late_settlement_cannot_reopen(tmp_path, clock):
    ledger = create(tmp_path); ticket = worker(ledger)
    send = reserve(ledger, ticket); ledger.mark_started(send)
    clock.now += 60
    with pytest.raises(api().BudgetStopped, match='request_deadline'): ledger.settle(send, completion())
    assert ledger.receipt()['unsettled_requests'] == 1
    assert ledger.receipt()['completed_sends'] == 0
    with pytest.raises(api().BudgetStopped): reserve(ledger, ticket, 2)
    ledger.close()


@pytest.mark.parametrize('elapsed', [7200, float('nan'), -1])
def test_wall_deadline_or_invalid_clock_fences_before_send(tmp_path, clock, elapsed):
    ledger = create(tmp_path); ticket = worker(ledger)
    clock.now += elapsed
    with pytest.raises(api().BudgetStopped): reserve(ledger, ticket)
    assert ledger.receipt()['send_reservations'] == 0
    ledger.close()


def test_duplicate_settlement_foreign_and_forged_tickets_fail_closed(tmp_path, clock):
    ledger = create(tmp_path); ticket = worker(ledger)
    send = complete(ledger, ticket)
    with pytest.raises(api().BudgetStopped, match='send_replay'): ledger.settle(send, completion())
    assert ledger.receipt()['completed_sends'] == 1
    ledger.close()
    other = tmp_path / 'other'; other.mkdir()
    foreign = create(other)
    with pytest.raises(api().BudgetStopped): foreign.mark_started(send)
    assert foreign.receipt()['send_reservations'] == 0
    foreign.close()


def test_close_is_immediate_and_preserves_active_uncertainty(tmp_path, clock):
    ledger = create(tmp_path); ticket = worker(ledger)
    send = reserve(ledger, ticket); ledger.mark_started(send)
    ledger.close(); ledger.close()
    receipt = ledger.receipt()
    assert receipt['cleanup']['closed'] is True
    assert receipt['cleanup']['active_finished'] is False
    assert receipt['unsettled_requests'] == 1
    assert receipt['remaining_send_reservations'] == 599
    with pytest.raises(api().BudgetStopped): ledger.settle(send, completion())
    events = [json.loads(line) for line in next(tmp_path.glob('*.jsonl')).read_text().splitlines()]
    assert events[-1]['active_finished'] is False


def test_journal_failure_before_returning_send_ticket_fences_run(tmp_path, clock, monkeypatch):
    ledger = create(tmp_path); ticket = worker(ledger)
    real_fsync = os.fsync
    def broken_fsync(fd): raise OSError('synthetic journal failure')
    monkeypatch.setattr(api().os, 'fsync', broken_fsync)
    with pytest.raises(api().BudgetStopped, match='journal_unavailable'): reserve(ledger, ticket)
    receipt = ledger.receipt()
    assert receipt['send_reservations'] == 1
    assert receipt['cleanup']['journal_durable'] is False
    assert receipt['synthetic_contacts_started'] == 0
    monkeypatch.setattr(api().os, 'fsync', real_fsync)
    with pytest.raises(api().BudgetStopped): reserve(ledger, ticket)
    ledger.close()


def test_no_transport_or_live_authority_api_exists():
    module = api()
    import ast
    tree = ast.parse(Path(module.__file__).read_text())
    forbidden = {'httpx', 'aiohttp', 'socket', 'subprocess', 'requests', 'apps', 'urllib'}
    imports = {node.module.split('.')[0] for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module}
    imports |= {alias.name.split('.')[0] for node in ast.walk(tree)
        if isinstance(node, ast.Import) for alias in node.names}
    assert not imports & forbidden
    assert not hasattr(module.CampaignDispatchBudget, 'send')
    assert not hasattr(module.CampaignDispatchBudget, 'resume')


def test_tickets_expose_bounded_deadlines_without_dispatch_authority(tmp_path, clock):
    ledger = create(tmp_path, wall_seconds=75)
    assert ledger.deadline == 175
    ticket = worker(ledger)
    clock.now += 30
    send = reserve(ledger, ticket)
    assert send.deadline == 175
    assert ticket.live_execution_authorized is send.live_execution_authorized is False
    ledger.close()


def test_family_off_cannot_spend_any_family_worker_slots(tmp_path, clock):
    ledger = api().CampaignDispatchBudget.create(reservation_root=tmp_path,
        proposal=build_budget_proposal(family_enabled=False), scope=scope())
    with pytest.raises(api().BudgetStopped, match='stage_limit'):
        worker(ledger, stage='focused_family')
    assert ledger.receipt()['worker_requests'] == 0
    ledger.close()


def test_partial_journal_writes_are_completed_and_zero_write_fails_closed(tmp_path, clock, monkeypatch):
    ledger = create(tmp_path)
    write = os.write
    def short_write(fd, data): return write(fd, data[:7])
    monkeypatch.setattr(api().os, 'write', short_write)
    ticket = worker(ledger)
    assert ticket.ordinal == 1
    for line in next(tmp_path.glob('*.jsonl')).read_text().splitlines(): json.loads(line)
    monkeypatch.setattr(api().os, 'write', lambda fd, data: 0)
    with pytest.raises(api().BudgetStopped, match='journal_unavailable'): reserve(ledger, ticket)
    assert ledger.receipt()['send_reservations'] == 1
    monkeypatch.setattr(api().os, 'write', write)
    ledger.close()
    assert ledger.receipt()['cleanup']['journal_durable'] is False


def test_journal_failure_during_close_still_closes_descriptor_and_fences(tmp_path, clock, monkeypatch):
    ledger = create(tmp_path)
    fd = ledger._fd
    def broken_fsync(fd): raise OSError('synthetic')
    monkeypatch.setattr(api().os, 'fsync', broken_fsync)
    with pytest.raises(api().BudgetStopped): ledger.close()
    assert ledger.receipt()['cleanup'] == {'closed': True, 'active_finished': True, 'journal_durable': False}
    with pytest.raises(OSError): os.fstat(fd)
    with pytest.raises(api().BudgetStopped): worker(ledger)
