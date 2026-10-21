"""Explicit provider-free sequence adapter using existing SQL clone/HTTP seams.

Used only by isolated tests. There is deliberately no live transport or CLI
execution switch. Model output is a fixture and cannot establish model quality.
"""
from __future__ import annotations

from copy import deepcopy
import asyncio
from contextlib import nullcontext
import json
import re
import sys
from pathlib import Path
import time
from unittest.mock import patch
from uuid import uuid4

from scripts import issue53_profile_sequences as profile
from scripts.memoir_skill_eval_suite import Budget
from scripts.run_memoir_live_skills import save


class StreamObservation:
    """Measure only public events; missing milestone observations stay unknown."""
    def __init__(self, meaningful_excerpt, *, client_turn_id, project_id=None, accepted_source_id=None,
                 replay=False, expected_reply=None, clock=time.monotonic):
        if not isinstance(client_turn_id,str) or not client_turn_id.strip():
            raise ValueError('expected_client_turn_required')
        if replay and not all(isinstance(v,str) and v.strip() for v in (project_id,accepted_source_id,expected_reply)):
            raise ValueError('expected_saved_replay_required')
        self.clock, self.started = clock, clock()
        self.excerpt, self.public = meaningful_excerpt, ''
        self.events, self.timings = [], {key:None for key in profile.MILESTONES}
        self.identity=dict(client_turn_id=client_turn_id,project_id=project_id,accepted_source_id=accepted_source_id)
        self.replay,self.expected_reply=replay,expected_reply
        self.active,self.finished=False,False
        self.completion_reply,self.saved_reply=None,None

    def bound(self, data):
        return all(isinstance(value,str) and value.strip() and data.get(key)==value for key,value in self.identity.items())

    def reply_matches(self, data):
        reply=data.get('reply')
        return (isinstance(reply,str) and bool(reply.strip())
                and (self.expected_reply is None or reply==self.expected_reply)
                and (self.replay or reply==self.public))

    def observe(self, event):
        elapsed = self.clock() - self.started
        self.events.append({**deepcopy(event), 'elapsed_s':elapsed})
        kind = event.get('type')
        data=event.get('data') if isinstance(event.get('data'),dict) else {}
        if self.finished:return
        def mark(key):
            if self.timings[key] is None:self.timings[key]=elapsed
        if kind=='source_accepted' and not self.replay:
            if all(isinstance(data.get(k),str) and data[k].strip() and (v is None or data[k]==v) for k,v in self.identity.items()):
                self.identity={k:data[k] for k in self.identity}
                self.active=True
        if kind=='text_delta' and self.active and isinstance(event.get('text'),str) and event['text']:
            # More public text invalidates a premature completion/save assertion.
            if self.completion_reply is not None or self.saved_reply is not None:
                self.timings['reply_complete_s']=self.timings['durable_save_s']=None
                self.completion_reply=self.saved_reply=None
            self.public += event['text']
            if self.excerpt and self.excerpt in self.public and self.timings['first_meaningful_text_s'] is None:
                self.timings['first_meaningful_text_s'] = elapsed
        pool = data.get('question_pool')
        legacy_pool=(kind=='progress' and event.get('project_id')==self.identity['project_id']
            and event.get('turn_id')==self.identity['client_turn_id'] and data.get('id')=='question-pool'
            and data.get('status')=='completed' and isinstance(pool,dict)
            and isinstance(pool.get('chosen_id'),str) and bool(pool['chosen_id']))
        if (self.active and self.completion_reply is None and self.saved_reply is None
            and (kind=='question_validated' and self.bound(data) and data.get('has_question') is True or legacy_pool)):
            mark('validated_question_s')
        if (kind=='reply_complete' and self.active and self.bound(data) and self.saved_reply is None
            and data.get('cached') is False and type(data.get('has_question')) is bool and self.reply_matches(data)):
            mark('reply_complete_s')
            self.completion_reply=data['reply']
        if (kind=='conversation_saved' and self.active and self.bound(data) and self.reply_matches(data)
            and data.get('cached') is not True and data.get('conversation_saved') is True):
            mark('durable_save_s')
            self.saved_reply=data['reply']
        if (kind=='result' and self.bound(data) and self.reply_matches(data) and data.get('conversation_saved') is True
            and (data.get('cached') is True if self.replay else self.active and data.get('cached') is not True)):
            if self.replay:mark('reply_complete_s')
            self.finished=True
        if kind=='error':self.finished=True

    def receipt(self):
        return dict(timings=self.timings, meaningful_excerpt=self.excerpt,
                    public_text=self.public, events=self.events,identity=self.identity,replay=self.replay,
                    measurement='backend_HTTP_receipt_not_browser_paint')


def focused_state(snapshot):
    state = snapshot['canonical_state']
    sources = sorted(state['user_narrator_source'], key=lambda s:s['sequence'])
    turns = sorted((t for t in state['user_interview_turn'] if t.get('collector')), key=lambda s:s['sequence'])
    return dict(sources=[{k:s[k] for k in ('id','version','sequence','text','user_id','project_id','client_turn_id','language')} for s in sources],
        replies=[dict(source_id=t['source_id'], client_turn_id=t['client_turn_id'], reply=t['collector']['reply'],
                      plan=t['collector']['plan']) for t in turns],
        session=state['user_lifetime_conversation'])


def fixture_question(family, step_id, language):
    """Curated synthetic worker examples, never a production response shortcut."""
    examples = {
        'name-clue': [('What would you enjoy talking about?', '您想先聊些什么？'),
                      ('What do you remember about growing up there?', '在那里长大，您还记得什么？'),
                      ('What do you remember about tending the beans?', '您还记得怎样照料豆子吗？')],
        'correction': [('What do you remember about the bicycle work?', '您还记得修自行车时的什么事？'),
                       ('What do you remember about how your mother worked?', '您还记得母亲怎样干活吗？'),
                       ('What tools did you bring her?', '您给她递了什么工具？')],
        'emotional': [('What would feel comfortable to talk about next?', '接下来聊什么会让您觉得自在些？'),
                      ('What do you remember about her careful work?', '您还记得她仔细干活时的什么事？'), (None,None)],
        'switch-skip': [('What do you remember about planting the beans?', '您还记得种豆子时的什么事？'),
                        ('What would you prefer to discuss?', '您更想聊些什么？'),
                        ('What do you remember about school?', '您还记得上学时的什么事？'),
                        ('What do you remember about walking with your sister?', '您还记得和姐姐一起走路上学时的什么事？')],
        'photo-reference': [('Who supplied that caption?', '这段说明是谁写的？'),
                            ('What personal memory would you like to discuss?', '您想聊自己的哪段回忆？')],
        'resume-replay-rollback': [('What do you remember about growing beans together?', '您还记得一起种豆子时的什么事？'),
                                  ('What do you remember about the labels?', '您还记得那些标签的什么事？'),
                                  ('What do the blue labels bring to mind?', '蓝色标签让您想起什么？'),
                                  ('What do you remember about that tin?', '您还记得那个铁盒的什么事？')],
    }
    ordinal = int(step_id.removeprefix('turn-'))-1
    return examples[family][ordinal][language=='zh-CN']


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
    journal = dict(run_id=planned['run_id'], plan_sha256=planned['plan_sha256'], rows={}, seeds={}, failures={})
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
        import pytest
        with offline_settings(), pytest.MonkeyPatch.context() as policy_fixture:
            # Helper imports add tests to sys.path, without creating provider clients.
            from scripts.controlled_native_state import _test_adapter
            _test_adapter()
            from controlled_policy import install_policy_review_transport
            install_policy_review_transport(policy_fixture)
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
                                            # Explicit test-only policy changes live only inside
                                            # offline_settings and the mocked worker transport.
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
                                            if rolled_back and not planned.get('controlled', {}).get('rollback'):
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
                                            packet_readbacks, request_envelopes, policy_readbacks, transport_observations = [], [], [], []
                                            fault = planned.get('controlled', {}).get('faults', {}).get(row['row_id'])
                                            fixture_policy = planned.get('controlled', {}).get('rollback')
                                            requested_model = 'gpt-5.6-luna-pooled' if row['arm']=='baseline' or rolled_back else 'synthetic-byte-bpe'
                                            async def provider(request):
                                                class Fixture:
                                                    async def call(self, packet):
                                                        if fault=='timeout': raise TimeoutError('Controlled worker timeout')
                                                        if fault=='malformed':
                                                            return dict(output='{',response_id='fixture-'+str(uuid4()),model='controlled-application-fixture',usage=None)
                                                        proposal = extraction_proposal(language)
                                                        proposal['acknowledgement'] = ('您说：' if language=='zh-CN' else 'You said: ') + excerpt
                                                        proposal['plan']['work']['mode'] = original['work']
                                                        if original['work']=='reply_only' and original['phase']=='first':
                                                            proposal['plan']['work']['name'] = '韩凤江' if case['locale']=='zh-CN' else 'Joan'
                                                        question = fixture_question(case['family'],original['id'],language)
                                                        if question is None:
                                                            proposal['stopped']=True
                                                            proposal['plan'].update(candidates=[],chosen_id=None)
                                                        else:
                                                            proposal['plan']['candidates'][0]['question']=question
                                                        return dict(output=proposal, response_id='fixture-' + str(uuid4()), model='controlled-application-fixture', usage=None)
                                                request_body = json.loads(request.content)
                                                governed = json.loads(request_body['governed']['packet'])
                                                # Independently query current SQL eligibility: a new
                                                # privacy preference can withhold an older assistant
                                                # reply without deleting it or the narrator's source.
                                                session = focused_state(snapshot_case(sql,storage,places))['session'][0]
                                                tail_readback = storage.lifetime_rpc('read_lifetime_tail',
                                                    p_conversation_id=session['conversation_id'],
                                                    p_policy_epoch=governed['current']['narrator']['policy_epoch'],
                                                    p_after_sequence=0,p_through_sequence=governed['current']['sequence']-1)
                                                packet_readbacks.append(dict(**profile.packet_projection(request_body),tail_readback=tail_readback))
                                                policy_readbacks.append(dict(observed_request_model=request_body['model'],governed_model=governed['model']))
                                                # Current source and previous replies travel through the real governed packet.
                                                envelope = dict(item_id=row['item']['id'], input=request_body)
                                                request_envelopes.append(deepcopy(envelope))
                                                reply = await budget.dispatch(Fixture(), envelope)
                                                for call in budget.calls[start:]: call.update(ctx, live_model_dispatch=False)
                                                encoded = reply['output'] if isinstance(reply['output'],str) else json.dumps(reply['output'],ensure_ascii=False)
                                                if fault=='disconnect':
                                                    class Disconnected(httpx.AsyncByteStream):
                                                        async def __aiter__(self):
                                                            prefix=encoded.split('"plan"',1)[0]
                                                            transport_observations.append('upstream_fragment_sent_then_disconnect')
                                                            yield (json.dumps(dict(type='text_delta',text=prefix))+'\n').encode()
                                                            raise httpx.ReadError('Controlled worker disconnect',request=request)
                                                    return httpx.Response(200,headers={'Content-Type':'application/x-ndjson'},stream=Disconnected())
                                                return worker_reply(request,dict(reply=encoded,thread_id='fixture-thread',artifacts=[]))
                                            # Keep the runtime instance until the explicit reopen action.
                                            transport = httpx.MockTransport(provider)
                                            if row['arm'] not in runtimes:
                                                runtimes[row['arm']] = CodexRuntime(home_root=directory/row['arm'],model='synthetic-byte-bpe',
                                                    worker_url='http://controlled.invalid',worker_secret='synthetic',worker_transport=transport)
                                            runtime = runtimes[row['arm']]
                                            runtime.worker_transport = transport
                                            turn_id=profile.client_turn_id(planned,row)
                                            replay_source=next((s for s in before['sources'] if s['client_turn_id']==turn_id),None)
                                            replay_reply=next((r['reply'] for r in before['replies'] if replay_source and r['source_id']==replay_source['id']),None)
                                            if row['action']=='replay' and not replay_reply:
                                                value['reason']='saved_replay_prerequisite_unavailable'
                                                persist()
                                                continue
                                            observation = StreamObservation(excerpt,client_turn_id=turn_id,project_id=spec['project_id'],
                                                replay=row['action']=='replay',accepted_source_id=replay_source['id'] if replay_source else None,
                                                expected_reply=replay_reply)
                                            real_rpc = storage.lifetime_rpc
                                            def guarded_rpc(name,**arguments):
                                                if name in {'commit_lifetime_turn','commit_lifetime_strategy_turn'}:
                                                    raise RuntimeError('Controlled commit failure')
                                                return real_rpc(name,**arguments)
                                            try:
                                                environment = {'MEMOIR_PUBLICATION_DATABASE_URL':sql.publication_dsn}
                                                if fixture_policy: environment['MEMORY_SPARK_COLLECTOR_MODEL']=requested_model
                                                with patch.dict('os.environ', environment), (patch.object(storage,'lifetime_rpc',guarded_rpc) if fault=='save_failure' else nullcontext()):
                                                    async with asyncio.timeout(min(budget.timeout,budget.deadline-time.monotonic())):
                                                        delivered = await canonical_turn(runtime,storage,text,options=dict(project_id=spec['project_id'],
                                                            language=language,client_turn_id=turn_id),
                                                            evaluation=dict(case_id=row['item']['id'],run_id=planned['run_id']), on_event=observation.observe)
                                                after = focused_state(snapshot_case(sql,storage,places))
                                                output = dict(canonical_result={k:delivered[k] for k in ('accepted_source_id','project_id','reply','conversation_saved')},
                                                              cached=bool(delivered.get('cached')))
                                                capture = dict(row_id=row['row_id'],context=ctx,plan_sha256=planned['plan_sha256'],
                                                    owner_id=storage.user_id,project_id=spec['project_id'],before=before,after=after,
                                                    output=output,dispatches=deepcopy(budget.calls[start:]),configuration=planned['variants'][row['arm']],
                                                    contracts={k:'pass' for k in profile.CONTRACTS},stream_observation=observation.receipt(),
                                                    matched_seed_sha256=seed_hash,pre_state_sha256=profile.digest(before),packet_readbacks=packet_readbacks,
                                                    request_envelopes=request_envelopes,
                                                    resume=resume.pop(row['arm'],None))
                                                if fixture_policy and row['action']!='replay':
                                                    capture['controlled_policy']=dict(scope='isolated_mock_transport',requested_model=requested_model,
                                                        **policy_readbacks[-1],saved_model=after['session'][0]['thread_model'],effective_provider_policy=None)
                                                if rolled_back: capture['future_configuration']=deepcopy(planned['variants']['baseline'])
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
                                                timed_out=isinstance(error,TimeoutError) or any(c.get('error_class')=='TimeoutError' for c in budget.calls[start:])
                                                journal['failures'][row['row_id']]=dict(context=ctx,reason=type(error).__name__,
                                                    before=before,after=focused_state(snapshot_case(sql,storage,places)),
                                                    dispatches=deepcopy(budget.calls[start:]),stream_observation=observation.receipt(),
                                                    transport_observations=transport_observations,request_envelopes=request_envelopes)
                                                value.update(execution='timed_out' if timed_out else 'failed',reason=type(error).__name__,
                                                    timings=observation.timings,stream_observation_sha256=profile.digest(observation.receipt()))
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
