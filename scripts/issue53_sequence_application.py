"""Explicit provider-free sequence adapter using existing SQL clone/HTTP seams.

Used only by isolated tests. There is deliberately no live transport or CLI
execution switch. Model output is a fixture and cannot establish model quality.
"""
from __future__ import annotations

from copy import deepcopy
import asyncio
import json
import re
import sys
from pathlib import Path
import time
from unittest.mock import patch
from uuid import uuid4, uuid5, NAMESPACE_URL

from scripts import issue53_profile_sequences as profile
from scripts.memoir_skill_eval_suite import Budget
from scripts.run_memoir_live_skills import save


class StreamObservation:
    """Measure only public events; missing milestone observations stay unknown."""
    def __init__(self, meaningful_excerpt, *, clock=time.monotonic):
        self.clock, self.started = clock, clock()
        self.excerpt, self.public = meaningful_excerpt, ''
        self.events, self.timings = [], {key:None for key in profile.MILESTONES}

    def observe(self, event):
        elapsed = self.clock() - self.started
        self.events.append({**deepcopy(event), 'elapsed_s':elapsed})
        kind = event.get('type')
        if kind == 'text_delta':
            self.public += event.get('text', '')
            if self.excerpt and self.excerpt in self.public and self.timings['first_meaningful_text_s'] is None:
                self.timings['first_meaningful_text_s'] = elapsed
        pool = (event.get('data') or {}).get('question_pool')
        if kind == 'progress' and isinstance(pool, dict) and pool.get('chosen_id'):
            self.timings['validated_question_s'] = elapsed
        if kind == 'reply_complete': self.timings['reply_complete_s'] = elapsed
        if kind == 'conversation_saved' and (event.get('data') or {}).get('conversation_saved'):
            self.timings['durable_save_s'] = elapsed

    def receipt(self):
        return dict(timings=self.timings, meaningful_excerpt=self.excerpt,
                    public_text=self.public, events=self.events, measurement='backend_HTTP_receipt_not_browser_paint')


def focused_state(snapshot):
    state = snapshot['canonical_state']
    sources = sorted(state['user_narrator_source'], key=lambda s:s['sequence'])
    turns = sorted((t for t in state['user_interview_turn'] if t.get('collector')), key=lambda s:s['sequence'])
    return dict(sources=[{k:s[k] for k in ('id','version','sequence','text','user_id','project_id','client_turn_id','language')} for s in sources],
        replies=[dict(source_id=t['source_id'], client_turn_id=t['client_turn_id'], reply=t['collector']['reply']) for t in turns],
        session=state['user_lifetime_conversation'])


async def controlled_sequences(planned, directory):
    """Connected variant branches share a cloned seed, then retain their own state.

    Per-turn histories may diverge after model outputs differ; reports retain
    those context hashes as a comparison confound rather than claiming identical
    later prestates. This adapter always uses synthetic external completions.
    """
    import httpx
    from apps.api.codex_runtime import CodexRuntime
    from scripts.canonical_turn import canonical_turn
    from scripts.controlled_native_state import controlled_database, open_case, snapshot_case
    from scripts.profile_canonical_controlled import offline_settings
    from scripts.memoir_skill_eval_application import _network_guard

    profile.check_plan(planned)
    if any(any(v is not None for v in variant.values()) for variant in planned['variants'].values()):
        raise ValueError('controlled_fixture_cannot_attest_provider_configuration')
    directory = Path(directory)
    if directory.exists() and any(directory.iterdir()): raise ValueError('existing_run_must_be_preserved')
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    save(directory / 'plan.json', planned)
    results = {r['row_id']:dict(row_id=r['row_id'], execution='unavailable', reason='not_run', evidence_mode='mock_only')
               for r in planned['rows']}
    journal = dict(run_id=planned['run_id'], plan_sha256=planned['plan_sha256'], rows={}, seeds={})
    budget = Budget(planned['budgets']['max_skill_calls'], planned['budgets']['seconds'],
                    planned['budgets']['timeout'], time.monotonic)
    active_row = None
    def persist():
        journal['budget'] = budget.receipt()
        save(directory / 'results.json', list(results.values()))
        save(directory / 'receipts.json', journal)
    def record_dispatch():
        for call in budget.calls:
            if 'dispatch_id' not in call:
                call.update(profile.context(planned,active_row), row_id=active_row['row_id'],
                            dispatch_id=str(uuid4()), live_model_dispatch=False)
        persist()
    budget.on_change = record_dispatch
    persist()
    if budget.maximum == 0: return list(results.values()), journal
    sys.addaudithook(_network_guard)
    native_cleanup_confirmed = False
    try:
        with offline_settings():
            # Helper imports add tests to sys.path, without creating provider clients.
            from scripts.controlled_native_state import _test_adapter
            _test_adapter()
            from controlled_collector import extraction_proposal, worker_reply
            for case in planned['scenarios']:
                samples = sorted({r['sample'] for r in planned['rows'] if r['scenario_id'] == case['id']})
                for sample in samples:
                    with controlled_database() as baseline_sql:
                        spec = dict(id=case['id'], project_id='issue53-' + profile.digest([case['id'],sample])[:20])
                        baseline, adapter, legacy = open_case(baseline_sql, spec)
                        try:
                            seed = snapshot_case(baseline_sql, baseline, legacy)
                            with controlled_database() as candidate_sql:
                                candidate, candidate_adapter, candidate_legacy = open_case(candidate_sql, spec, seed)
                                try:
                                    candidate_hash = profile.digest(snapshot_case(candidate_sql,candidate,candidate_legacy)['canonical_state'])
                                    if candidate_hash != profile.digest(seed['canonical_state']):
                                        raise ValueError('matched_seed_clone_failed')
                                    journal['seeds'][profile.digest([case['id'],sample])] = dict(canonical_state=seed['canonical_state'],
                                        baseline_sha256=profile.digest(seed['canonical_state']),candidate_sha256=candidate_hash)
                                    arms = dict(baseline=[baseline_sql,baseline,adapter,legacy], candidate=[candidate_sql,candidate,candidate_adapter,candidate_legacy])
                                    seed_hash = profile.digest(seed['canonical_state'])
                                    runtimes, resume, rolled_back = {}, {}, False
                                    for step in case['steps']:
                                        if step['action'] == 'rollback':
                                            # Production configuration changes are outside this offline adapter.
                                            rolled_back = True
                                            continue
                                        if step['action'] == 'reopen':
                                            for arm,(sql,storage,db_adapter,places) in arms.items():
                                                before = focused_state(snapshot_case(sql,storage,places))
                                                storage.client.close()
                                                fresh = db_adapter.storage(); fresh.project_id = spec['project_id']
                                                arms[arm][1] = fresh
                                                runtimes.pop(arm, None)
                                                resume[arm] = dict(before_close=before,
                                                    after_reopen=focused_state(snapshot_case(sql,fresh,places)), new_runtime=True)
                                            continue
                                        measured = [r for r in planned['rows'] if r['scenario_id'] == case['id'] and r['sample'] == sample and r['step_id'] == step['id']]
                                        # Alternate order without changing the connected state within each arm.
                                        measured.sort(key=lambda r:r['arm'], reverse=sample % 2 == 1)
                                        for row in measured:
                                            active_row = row
                                            value = results[row['row_id']]
                                            if rolled_back:
                                                value['reason'] = 'future_rollback_configuration_adapter_unavailable'; persist(); continue
                                            if len(budget.calls) >= budget.maximum or time.monotonic() >= budget.deadline:
                                                value['reason'] = 'skill_budget_or_deadline_exhausted'; persist(); continue
                                            sql,storage,db_adapter,places = arms[row['arm']]
                                            before = focused_state(snapshot_case(sql,storage,places))
                                            start = len(budget.calls)
                                            ctx = profile.context(planned,row)
                                            original = step if step['action']=='turn' else next(s for s in case['steps'] if s['id']==step['target'])
                                            text, language = original['text'], original['reply_language']
                                            excerpt = re.split(r'[?？]', text)[-1].strip() or text
                                            packet_readbacks = []
                                            async def provider(request):
                                                class Fixture:
                                                    async def call(self, packet):
                                                        proposal = extraction_proposal(language)
                                                        proposal['acknowledgement'] = ('您说：' if language=='zh-CN' else 'You said: ') + excerpt
                                                        proposal['plan']['work']['mode'] = original['work']
                                                        return dict(output=proposal, response_id='fixture-' + str(uuid4()), model='controlled-application-fixture', usage=None)
                                                request_body = json.loads(request.content)
                                                governed = json.loads(request_body['governed']['packet'])
                                                packet_readbacks.append(dict(current=governed['current'],tail=governed['tail'],
                                                    pinned=governed['pinned'],interview_context=request_body['interview_context'],
                                                    actual_prompt_version=governed['prompt_version']))
                                                # Current source and previous replies travel through the real governed packet.
                                                reply = await budget.dispatch(Fixture(), dict(item_id=row['item']['id'], input=request_body))
                                                for call in budget.calls[start:]: call.update(ctx, live_model_dispatch=False)
                                                return worker_reply(request,dict(reply=json.dumps(reply['output'],ensure_ascii=False),thread_id='fixture-thread',artifacts=[]))
                                            # Keep the runtime instance until the explicit reopen action.
                                            transport = httpx.MockTransport(provider)
                                            if row['arm'] not in runtimes:
                                                runtimes[row['arm']] = CodexRuntime(home_root=directory/row['arm'],model='synthetic-byte-bpe',
                                                    worker_url='http://controlled.invalid',worker_secret='synthetic',worker_transport=transport)
                                            runtime = runtimes[row['arm']]
                                            runtime.worker_transport = transport
                                            observation = StreamObservation(excerpt)
                                            try:
                                                with patch.dict('os.environ', {'MEMOIR_PUBLICATION_DATABASE_URL':sql.publication_dsn}):
                                                    async with asyncio.timeout(min(budget.timeout,budget.deadline-time.monotonic())):
                                                        delivered = await canonical_turn(runtime,storage,text,options=dict(project_id=spec['project_id'],
                                                            language=language,client_turn_id=str(uuid5(NAMESPACE_URL,
                                                                planned['run_id']+case['id']+str(sample)+step['client_turn_key']))),
                                                            evaluation=dict(case_id=row['item']['id'],run_id=planned['run_id']), on_event=observation.observe)
                                                after = focused_state(snapshot_case(sql,storage,places))
                                                output = dict(canonical_result={k:delivered[k] for k in ('accepted_source_id','project_id','reply','conversation_saved')},
                                                              cached=bool(delivered.get('cached')))
                                                capture = dict(row_id=row['row_id'],context=ctx,plan_sha256=planned['plan_sha256'],
                                                    owner_id=storage.user_id,project_id=spec['project_id'],before=before,after=after,
                                                    output=output,dispatches=deepcopy(budget.calls[start:]),configuration=planned['variants'][row['arm']],
                                                    contracts={k:'pass' for k in profile.CONTRACTS},stream_observation=observation.receipt(),
                                                    matched_seed_sha256=seed_hash,pre_state_sha256=profile.digest(before),packet_readbacks=packet_readbacks,
                                                    resume=resume.pop(row['arm'],None))
                                                current = next(s for s in after['sources'] if s['id']==delivered['accepted_source_id'])
                                                independent = dict(scope='controlled_disposable_application',database_removed=False,
                                                    item_id=row['item']['id'],task_sha256=profile.digest(row['item']['task']),output_sha256=profile.digest(output),
                                                    completed_turns=len(after['replies']),context={**ctx,'dataset':row['item']['dataset'],
                                                        'dataset_snapshot':row['item']['dataset_snapshot'],'item_sha256':row['item']['content_sha256']},
                                                    source_readbacks=[current],owner_id=storage.user_id,project_id=spec['project_id'],
                                                    canonical_delivery=True,dispatches=capture['dispatches'])
                                                capture['native_readback'] = independent
                                                journal['rows'][row['row_id']] = capture
                                                value.update(execution='completed',reason='',output=output,timings=observation.timings,
                                                    stream_observation_sha256=profile.digest(observation.receipt()),provider_metrics={k:None for k in profile.PROVIDER_FIELDS})
                                            except Exception as error:
                                                for call in budget.calls[start:]: call.update(ctx,live_model_dispatch=False)
                                                value.update(execution='timed_out' if isinstance(error,TimeoutError) else 'failed',reason=type(error).__name__)
                                            persist()
                                finally:
                                    candidate.client.close()
                                    if 'arms' in locals(): arms['candidate'][1].client.close()
                        finally:
                            baseline.client.close()
                            if 'arms' in locals(): arms['baseline'][1].client.close()
        native_cleanup_confirmed = True
    finally:
        # Only normally exited database contexts establish cleanup. Interrupted
        # or failed cleanup retains evidence without granting canonical delivery.
        for row_id,capture in journal['rows'].items():
            native = capture.pop('native_readback')
            native['database_removed'] = native_cleanup_confirmed
            path = directory / ('native-' + profile.digest(row_id)[:20] + '.json')
            save(path,native)
            capture['witness'] = dict(receipt_path=path.name, receipt_sha256=profile.digest(native),
                readback=native,run_id=planned['run_id'])
            sequence_path = directory / ('sequence-' + profile.digest(row_id)[:20] + '.json')
            save(sequence_path,capture)
            capture['sequence_receipt_path'] = sequence_path.name
            capture['sequence_receipt_sha256'] = profile.digest(json.loads(sequence_path.read_text()))
        journal['budget'] = budget.receipt()
        persist()
    return list(results.values()),journal
