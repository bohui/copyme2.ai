"""Process-isolated synthetic application witnesses; never a configured database.

Only this explicit offline adapter imports the repository's disposable fixture
harness. Parent planning does not allocate a database, browser or subprocess.
Child authority is an allowlisted environment and a freshly allocated cluster.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import time
from uuid import uuid4

from scripts.memoir_skill_eval_suite import Budget, ROOT, digest
from scripts.run_memoir_live_skills import save

APPLICATION_CONTEXT_KEYS = ('run_id', 'source_revision', 'source_content_sha256', 'invocation_id')


def verify_witness(item, output, witnesses, directory, *, expected_context, dispatches):
    if not expected_context or any(not isinstance(expected_context.get(k), str) or not expected_context[k]
                                   for k in APPLICATION_CONTEXT_KEYS):
        raise ValueError('current_application_context_required')
    path = Path(directory) / witnesses['receipt_path']
    if path.is_symlink() or not path.resolve().is_relative_to(Path(directory).resolve()):
        raise ValueError('application_receipt_location')
    value = json.loads(path.read_text())
    if digest(value) != witnesses['receipt_sha256']:
        raise ValueError('application_receipt_changed')
    if witnesses.get('readback') != value:
        raise ValueError('application_supplied_evidence_changed')
    if (value['scope'] != 'controlled_disposable_application' or not value['database_removed']
        or value['item_id'] != item['id'] or value['task_sha256'] != digest(item['task'])
        or value['output_sha256'] != digest(output) or value['completed_turns'] < 1):
        raise ValueError('application_identity_mismatch')
    if (value['context']['dataset_snapshot'] != item['dataset_snapshot']
        or value['context']['dataset'] != item['dataset']
        or value['context']['item_sha256'] != item['content_sha256']):
        raise ValueError('application_version_binding_mismatch')
    if (any(value['context'].get(k) != expected_context[k] for k in APPLICATION_CONTEXT_KEYS)
        or witnesses.get('run_id') != expected_context['run_id']):
        raise ValueError('application_current_context_mismatch')
    if (not dispatches or value.get('dispatches') != dispatches
        or any(c.get('item_id') != item['id'] or c.get('status') not in {'completed', 'failed'}
               or any(c.get(k) != expected_context[k] for k in APPLICATION_CONTEXT_KEYS) for c in dispatches)):
        raise ValueError('application_current_dispatch_receipt_required')
    sources = value['source_readbacks']
    if not sources or any(s['user_id'] != value['owner_id'] or s['project_id'] != value['project_id'] for s in sources):
        raise ValueError('application_source_scope')
    expected = ([b['text'] for c in item['task']['chapters'] for b in c['blocks']]
                if item['skill'] == 'memoir-story-game' else [item['task']['source']['text']])
    if [s['text'] for s in sources] != expected or any(s['version'] != 1 for s in sources):
        raise ValueError('application_original_readback_mismatch')
    if output['canonical_result']['accepted_source_id'] not in {s['id'] for s in sources}:
        raise ValueError('canonical_source_identity_mismatch')
    if item['skill'] == 'memoir-story-game':
        phase = value['game']
        if phase['case'] != item['case'] or not phase['verified']:
            raise ValueError('game_phase_witness_missing')
        if item['case'] == 'play' and not (phase.get('browser') or {}).get('verified'):
            raise ValueError('browser_play_witness_missing')
    elif not value.get('events') and item['skill'] == 'memoir-author-timeline':
        raise ValueError('canonical_event_readback_missing')
    return dict(verified=True, canonical_delivery=value['canonical_delivery'], scope=value['scope'])


class ControlledApplication:
    def __init__(self, *, browser_url=None, browser_executable='/usr/bin/chromium'):
        self.browser_url, self.browser_executable = browser_url, browser_executable

    def supports(self, item):
        return item['skill'] == 'memoir-story-game' or (item['skill'], item['case']) in {
            ('memoir-author-timeline', 'exact-testimony'), ('memoir-interviewer', 'grounded-question')}

    async def execute(self, item, budget, directory, context):
        if item['case'] == 'play' and not self.browser_url: raise LookupError('browser_origin_required')
        if not self.supports(item): raise LookupError('canonical_scenario_adapter_unavailable')
        if len(budget.calls) >= budget.maximum or time.monotonic() >= budget.deadline:
            raise LookupError('skill_budget_exhausted')
        from scripts.run_isolated_check import offline_environment
        from scripts.controlled_lifecycle import ALLOCATION_ROOT_ENV, new_native_root
        from scripts.controlled_five_case import cleanup_case
        folder = Path(directory) / ('application-' + digest(item['id'])[:16])
        folder.mkdir(mode=0o700)
        allocation = new_native_root('memoir-case-')
        environment = offline_environment(ROOT)
        environment[ALLOCATION_ROOT_ENV] = str(allocation)
        # This directory contains public packages only, not connector/provider configuration.
        environment['PYTHONPATH'] = str(ROOT)
        environment['MEMORY_SPARK_TASK_DB'] = str(folder / 'tasks.sqlite3')
        environment['MEMORY_SPARK_DATABASE'] = str(folder / 'application.sqlite3')
        payload = dict(item=item, folder=str(folder), allocation=str(allocation),
            context={**context, 'dataset': item['dataset'], 'dataset_snapshot': item['dataset_snapshot'],
                     'item_sha256': item['content_sha256']},
            max_calls=budget.maximum-len(budget.calls), deadline=budget.deadline,
            timeout=budget.timeout, max_bytes=budget.max_bytes, browser_url=self.browser_url,
            browser_executable=self.browser_executable)
        creation, process = None, None
        dispatch_start = len(budget.calls)
        try:
            creation = asyncio.create_task(asyncio.create_subprocess_exec(sys.executable,
                '-m', 'scripts.memoir_skill_eval_application', cwd=ROOT, env=environment,
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE))
            process = await asyncio.shield(creation)
            async with asyncio.timeout(max(.01, budget.deadline-time.monotonic())):
                stdout, stderr = await process.communicate(json.dumps(payload).encode())
            (folder / 'application.log').write_bytes(stderr)
            if process.returncode: raise LookupError('application_child_failed')
            result = json.loads(stdout)
        finally:
            # The parent owns allocations even if its child fails during startup.
            cleanup = asyncio.create_task(cleanup_case(creation, allocation, environment))
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                await cleanup
                raise
            calls = folder / 'calls.json'
            if calls.exists():
                recorded = json.loads(calls.read_text())
                if len(recorded) > payload['max_calls']: raise ValueError('application_dispatch_overrun')
                budget.calls.extend(recorded)
                budget.on_change()
        if result.get('error'): raise LookupError(result['error'])
        receipt_path = folder / 'readback.json'
        independent = json.loads(receipt_path.read_text())
        independent['database_removed'] = not allocation.exists()
        save(receipt_path, independent)
        witness = dict(kind='controlled_application', receipt_path=str(receipt_path.relative_to(directory)),
            receipt_sha256=digest(independent), run_id=context['run_id'], persisted_canonical_state=True,
            browser_observed=bool((independent.get('game', {}).get('browser') or {}).get('verified')),
            readback=deepcopy(independent))
        verify_witness(item, result['output'], witness, directory, expected_context=context,
                       dispatches=budget.calls[dispatch_start:])
        return result['output'], witness


def _network_guard(event, args):
    if event not in {'socket.connect', 'socket.getaddrinfo'}: return
    address = args[1] if event == 'socket.connect' else args[0]
    if event == 'socket.connect' and isinstance(address, str): return
    host = address[0] if isinstance(address, tuple) else address
    if host not in {None, 'localhost', '127.0.0.1', '::1', b'127.0.0.1', b'localhost'}:
        raise RuntimeError('offline_application_external_socket_blocked')


async def _execute(value):
    # Imports remain inside the subprocess and optional controlled execution mode.
    tests = str(ROOT / 'tests')
    sys.path.insert(0, tests)
    import pytest
    from scripts.controlled_native_state import controlled_database
    from test_conversation_attribution import Conversation, empty, episode
    from test_agent_commit_postgres import OWNER
    from memoir_postgres_workflow import PostgresRest
    from test_shared_memory_events_postgres import literal, rpc
    from test_formal_memoir_postgres import completed, consent
    from test_story_game_runtime_postgres import begin_game, read, proposal_from_packet, compose_game_chapters
    from test_story_game_runtime import webpage, receipt
    from test_background_profile_workflow import Broker
    from apps.api.story_game_runtime import generate_story_game

    item, folder = value['item'], Path(value['folder'])
    budget = Budget(value['max_calls'], max(.01, value['deadline']-time.monotonic()), value['timeout'],
                    time.monotonic, max_bytes=value['max_bytes'])
    budget.deadline = value['deadline']
    def save_calls():
        for call in budget.calls:
            call.update(evidence_mode='controlled_fixture', live_model_dispatch=False)
            call.update({k: value['context'][k] for k in APPLICATION_CONTEXT_KEYS})
        save(folder / 'calls.json', budget.calls)
    budget.on_change = save_calls
    budget.on_change()

    async def external(request, respond):
        body = json.loads(request.content)
        class Fixture:
            async def call(self, packet):
                if body.get('bounded_lane'):
                    response = await respond(request)
                else:
                    from controlled_collector import extraction_proposal, worker_reply
                    if item['skill'] == 'memoir-story-game':
                        from test_interview_strategy import wire
                        output = wire(acknowledgement='谢谢您分享这段回忆。' if item['locale'] == 'zh-CN'
                                      else 'Thank you for sharing that memory.', used_strategy='shape',
                                      question='您还记得什么细节？' if item['locale'] == 'zh-CN' else 'What else do you remember?',
                                      selection_reason='latest_story')
                    else:
                        output = extraction_proposal(item['locale'])
                    response = worker_reply(request, dict(reply=json.dumps(output, ensure_ascii=False),
                                                          thread_id='controlled', artifacts=[]))
                self.response = response
                return dict(output=dict(http_status=response.status_code), response_id='fixture-worker-' + str(len(budget.calls)),
                            model='controlled-application-fixture', usage=None)
        fixture = Fixture()
        await budget.dispatch(fixture, dict(item_id=item['id'], kind='controlled_worker', input=body))
        return fixture.response

    with controlled_database(directory_root=value['allocation']) as sql, pytest.MonkeyPatch.context() as patch:
        from controlled_policy import install_policy_review_transport
        install_policy_review_transport(patch)
        game_case = item['skill'] == 'memoir-story-game'
        conversation = Conversation(sql, folder, patch, lambda packet: {
            **empty(packet), 'events': [episode(packet, packet['sources'][0]['text'], title=packet['sources'][0]['text'])]},
            strategy='shape' if game_case else None, external_boundary=external)
        with conversation.client:
            texts = ([b['text'] for c in item['task']['chapters'] for b in c['blocks']]
                     if game_case else [item['task']['source']['text']])
            for text in texts:
                result = conversation.say(text, language=item['locale'])
                await asyncio.to_thread(conversation.drain)
            project = conversation.project
            def sources():
                return json.loads(sql('select json_agg(r order by sequence) from '
                    f'(select id,user_id,project_id,version,sequence,status,text,client_turn_id from public.user_narrator_source '
                    f'where user_id={literal(OWNER)} and project_id={literal(project)}) r;').stdout)
            stored = sources()
            storage = PostgresRest(sql, OWNER).storage()
            try:
                events = storage.memory_events(project)['events']
            finally:
                storage.client.close()
            output = dict(canonical_result={k: result[k] for k in ('accepted_source_id', 'project_id', 'reply', 'conversation_saved')},
                          events=events)
            witness = dict(scope='controlled_disposable_application', owner_id=OWNER, project_id=project,
                item_id=item['id'], task_sha256=digest(item['task']), source_readbacks=stored, events=events,
                completed_turns=int(sql(f'select count(*) from public.user_completed_round where user_id={literal(OWNER)};').stdout),
                context=value['context'], canonical_delivery=True, database_removed=False)
            if game_case:
                await compose_game_chapters(conversation)
                edition = completed(sql, project, {'revision': 0})
                case = item['case']
                phase = dict(case=case, edition_id=edition['edition_id'], private_fixture_only=True, verified=False)
                if case != 'missing-consent': consent(sql, project, edition, 1)
                if case == 'stale-edition':
                    rpc(sql, 'change_user_narrator_source',
                        f"{literal(project)},'{stored[0]['id']}',1,'edit','Corrected synthetic testimony.'")
                if case in {'missing-consent', 'stale-edition'}:
                    rejected = begin_game(sql, project, check=False)
                    if not rejected.returncode: raise ValueError('missing_or_stale_authority_accepted')
                    phase.update(verified=True, admission_denied=True)
                    witness['canonical_delivery'] = False
                    output['game'] = dict(status='admission_denied')
                else:
                    game = begin_game(sql, project)
                    async def provider(packet):
                        class Fixture:
                            async def call(self, request):
                                proposal = proposal_from_packet(packet)
                                if case == 'timeline-coverage': proposal['scenes'].pop()
                                return dict(output=proposal, response_id='fixture-game-scenes',
                                            model='controlled-application-fixture', usage=None)
                        reply = await budget.dispatch(Fixture(), dict(item_id=item['id'], kind='game_scenes', input=packet))
                        return reply['output'], dict(status='completed', response_id=reply['response_id'], model=reply['model'])
                    async def builder(scenes):
                        class Fixture:
                            async def call(self, request):
                                document = webpage(item['locale'])
                                if case == 'unsafe-webpage':
                                    document['html'] = document['html'].replace('</head>', '<script>alert(1)</script></head>')
                                return dict(output=document, response_id='fixture-game-webpage',
                                            model='controlled-astra-boundary', usage=None)
                        reply = await budget.dispatch(Fixture(), dict(item_id=item['id'], kind='game_webpage', input=scenes))
                        return reply['output'], dict(status='completed', response_id=reply['response_id'], model=reply['model'])
                    try:
                        generated = await generate_story_game(Broker(sql), game['game_id'], provider=provider, builder=builder)
                    except ValueError as error:
                        expected = {'timeline-coverage': 'game_timeline_coverage_required',
                                    'unsafe-webpage': 'game_webpage_element_invalid'}
                        if str(error) != expected.get(case): raise
                        phase.update(generation_denied=True, denial_code=str(error))
                        witness['canonical_delivery'] = False
                        output['game'] = dict(status='generation_denied')
                    else:
                        if generated['status'] != 'published': raise ValueError('game_not_saved')
                        played = read(sql, project, game)
                        if 'game' not in played or not played['game'].get('webpage'):
                            raise ValueError('webpage_not_delivered')
                        phase.update(game_id=game['game_id'], staged_status=generated['status'],
                                     published_game=played['game'])
                        output['game'] = played
                        if case == 'revoked-consent':
                            consent(sql, project, edition, 2, 'revoke')
                            if not read(sql, project, game, check=False).returncode:
                                raise ValueError('revoked_game_delivered')
                            phase['access_denied'] = True
                            witness['canonical_delivery'] = False
                            output['game'] = dict(status='access_denied')
                        elif case == 'play':
                            from scripts.memoir_skill_eval_browser import exercise_game
                            phase['browser'] = await asyncio.to_thread(exercise_game, conversation, sql, item,
                                value['browser_url'], value['browser_executable'], folder, stored, result)
                    phase['verified'] = True
                phase['final_state'] = json.loads(sql('select coalesce(json_agg(r),\'[]\') from '
                    f'(select id,state,candidate_digest from public.user_story_game where user_id={literal(OWNER)}) r;').stdout)
                witness['game'] = phase
                witness['final_source_readbacks'] = sources()
            witness['output_sha256'] = digest(output)
            witness['dispatches'] = deepcopy(budget.calls)
            save(folder / 'readback.json', witness)
            return dict(output=output)


async def _main():
    sys.addaudithook(_network_guard)
    value = json.load(sys.stdin)
    try:
        result = await _execute(value)
    except Exception as error:
        # Child logs may contain synthetic debugging detail; public receipts use fixed classes only.
        import traceback
        traceback.print_exc(file=sys.stderr)
        result = dict(error='application_' + type(error).__name__)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    asyncio.run(_main())
