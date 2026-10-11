"""Bounded, matched backend-stream comparison with synthetic storage only.

Uses CodexRuntime -> private-worker NDJSON -> CodexWorker -> real app-server.
Only optional workspace responses and storage are controlled external adapters.
Each candidate gets a copy of the baseline's PRE-turn history and saved plan.
No service configuration, customer data, or shared provider policy is changed.
"""
import asyncio
from copy import deepcopy
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from uuid import NAMESPACE_URL, uuid4, uuid5

import httpx
from apps.api.agent_storage import UserStorage
from apps.api.codex_runtime import CodexRuntime
from apps.api.codex_worker_service import CodexWorker, WorkerTurnInput
from apps.api.evaluation_cases import SyntheticStorage
from apps.api.turn_stream import turn_events


CASES = {
    'zh-CN': [
        ('first', '我叫韩凤江。'),
        ('later', '小时候住在开封，父亲在铁路工作，母亲照顾我们。我和姐姐放学后去河边捉小鱼。有一次我掉进浅水里，姐姐把我拉上来。回家后我们不敢告诉父母。我记不清是哪一年。'),
        ('resumed_correction', '刚才说错了，把我拉上来的是母亲，不是姐姐。我记得她没有责备我，只是握着我的手。我一直记得这件事。'),
        ('photo', '这张照片里是我姐姐，不是我。是她后来在河边拍的，我不记得拍摄年份。'),
        ('language_change', 'Please continue in English. I do not remember what my sister said that day.'),
        ('pause', 'I would like to pause here. Please do not ask another question.'),
    ],
    'en-AU': [
        ('first', 'My name is Avery.'),
        ('later', 'I grew up in Hobart. My father worked on the railway and my mother looked after us. My sister and I caught little fish by the river after school. Once I fell in the shallow water and my sister pulled me out. We did not tell our parents. I cannot remember the year.'),
        ('resumed_correction', 'I got that wrong: my mother pulled me out, not my sister. She did not scold me; she held my hand. That has stayed with me.'),
        ('photo', 'This photo shows my sister, not me. It was taken later by the river. I do not remember when.'),
        ('language_change', '请接下来用中文。我不记得姐姐那天说了什么。'),
        ('pause', '我想先停一停，请不要再问问题了。'),
    ],
}
PHOTO = {'photo_id': 'synthetic-family-photo', 'kind': 'personal', 'caption': 'Family photograph',
    'capture_date': None, 'url': 'https://synthetic.invalid/photo.jpg'}
REFERENCE_PHOTO = {'photo_id': 'reference:synthetic-public-reference', 'kind': 'public_reference',
    'title': 'Public reference: a river in 1972; not a personal photograph',
    'capture_date': '1972', 'image_url': 'https://synthetic.invalid/reference.jpg'}
EXTRA_CASES = {
    'zh-CN': [
        ('short', '父亲下班后常常修东西。'),
        ('long', ('那条河让我想起很多家里的事。母亲很少责备我们，姐姐常陪我放学后慢慢走回家。'
            '有时我们捡石头，有时只是听水声。我不记得年份，也不确定这些事发生的先后。'
            '父亲修东西时我会坐在旁边看，并不是我自己会修。想到这些，我既怀念也难过。\n' * 35)
            + '最后一个细节：母亲把那张字条放进蓝色信封。'),
        ('family', '我的母亲叫美，姐姐叫诺拉。诺拉是姐姐，不是我的女儿。救我的是母亲，我仍记不起是哪一年。'),
        ('public_reference', '这只是找到的公共参考照片，不是我家的照片。我不知道照片里的人是谁，也不能确定我去过那个地方或在1972年住在那里。'),
    ],
    'en-AU': [
        ('short', 'Dad often repaired things after work.'),
        ('long', ('The river brings back many memories of home. Mum rarely scolded us, and my sister often walked slowly home with me after school. '
            'Sometimes we picked up stones; sometimes we just listened to the water. I cannot remember the year or be sure of the order of these memories. '
            'When Dad repaired things, I sat beside him and watched; I was not the one who knew how to repair them. These memories make me feel both fondness and sadness.\n' * 12)
            + 'One final detail: Mum put the note in a blue envelope.'),
        ('family', 'My mother is Mei and my sister is Nora. Nora is my sister, not my daughter. Mum rescued me; I still cannot remember the year.'),
        ('public_reference', 'This is only a public reference photograph, not our family photograph. I do not know the people in it. It does not mean I visited that place or lived there in 1972.'),
    ],
}
ROLLBACK_TEXT = {'zh-CN': '我们继续吧。我还记得母亲握着我的手，但不记得那年的年份。',
    'en-AU': 'Let us continue. I still remember Mum holding my hand, but not the year.'}


class ProfileStorage(SyntheticStorage, UserStorage):
    """Per-run in-memory external adapter; not SQL/RLS or durable-save evidence."""
    def __init__(self, language):
        super().__init__({'profile': {'preferred_language': language}}, {})
        self.user_id, self.project_id = str(uuid4()), 'project_latency_' + uuid4().hex[:12]
        self.turns, self.sources, self.plan, self.rounds = {}, [], None, 0

    def agent_turn_by_id(self, project, turn):
        return next((deepcopy(m) for m in self._memories if m['client_turn_id'] == turn), None)

    def accept_interview_turn(self, project, turn, text, **options):
        if turn not in self.turns:
            source = {'id': str(uuid5(NAMESPACE_URL, project + ':' + turn)), 'version': 1, 'status': 'active', 'text': text,
                'sequence': len(self.sources) + 1, 'language': options['language']}
            self.sources.append(source)
            self.turns[turn] = {'source': source, 'sequence': source['sequence'],
                'client_turn_id': turn, 'photo_context': [deepcopy(PHOTO)] if options.get('uploaded_photo_ids')
                    else [deepcopy(REFERENCE_PHOTO)] if options.get('photo_selection') else []}
        return deepcopy(self.turns[turn])

    def interview_turn_by_id(self, project, turn): return deepcopy(self.turns.get(turn))
    def narrator_source_by_turn(self, project, turn): return deepcopy(self.turns[turn]['source'])
    def interview_context(self, project):
        return {'plan': deepcopy(self.plan), 'photos': [deepcopy(photo)
            for turn in self.turns.values() for photo in turn['photo_context']]}
    def memory_events(self, project): return {'sources': deepcopy(self.sources), 'events': []}
    def recall_rounds_completed(self): return self.rounds
    def first_narrator_reply(self):
        return {'text': self.sources[0]['text'], 'id': self.sources[0]['id']} if self.sources else None

    def save_interview_plan(self, project, turn, plan, associations, token, **options):
        if token != self._lease_token: raise RuntimeError('Synthetic write outside lease')
        self.plan = deepcopy(plan)
        self.turns[turn].update(plan=deepcopy(plan), associations=deepcopy(associations), **options)
        return deepcopy(self.turns[turn])

    def commit_agent_turn(self, token, thread, text, paths, *, source_sequence=None, **options):
        result = super().commit_agent_turn(token, thread, text, paths, source_sequence=source_sequence)
        self._memories[0]['client_turn_id'] = options['client_turn_id']
        self.rounds += int(options['user_response'])
        return result


class WorkerStream(httpx.AsyncByteStream):
    def __init__(self, events): self.events = events
    async def __aiter__(self):
        async for event in self.events: yield event.encode()
    async def aclose(self): await self.events.aclose()


async def measure(storage, worker, text, case, timeout, *, review=False, client_turn_id=None):
    started, timings, receipt = time.perf_counter(), {}, {'appserver_turns': None, 'request_id': None}

    async def handle(request):
        payload = WorkerTurnInput.model_validate_json(request.content)
        if payload.agent_role != 'collector' and request.headers.get('accept') != 'application/x-ndjson':
            return httpx.Response(200, json={'thread_id': 'controlled-workspace', 'reply': '', 'artifacts': []})
        async def run(emit):
            if payload.agent_role != 'collector':
                return {'thread_id': 'controlled-workspace', 'reply': '', 'artifacts': []}
            receipt['request_id'] = payload.diagnostic_request_id
            async def raw_delta(value):
                if value: timings.setdefault('first_raw_delta_s', time.perf_counter() - started)
                await emit(value)
            result = await worker.turn(payload, on_delta=raw_delta, on_event=emit.event)
            trajectory = result.get('trajectory') or {}
            receipt['appserver_turns'] = sum(s['action'] == 'request.turn/start' for s in trajectory.get('steps', []))
            # Artifacts are optional workspace enrichment, not public quality evidence.
            return {**result, 'artifacts': []}
        return httpx.Response(200, stream=WorkerStream(turn_events(run)),
            headers={'content-type': 'application/x-ndjson'})

    runtime = CodexRuntime(worker_url='http://isolated-worker.invalid', worker_secret='synthetic',
        worker_transport=httpx.MockTransport(handle), model=worker.model, timeout=timeout)
    turn_id = client_turn_id or str(uuid4())
    async def run(emit):
        return await runtime.turn(storage, text, project_id=storage.project_id,
            language=storage.profile()['preferred_language'], client_turn_id=turn_id,
            on_delta=emit, on_event=emit.event, evaluation={'run_id': 'issue53-quality-first', 'case_id': case},
            **({'uploaded_photo_ids': [str(uuid4())]} if case == 'photo' else
                {'photo_selection': {'key': REFERENCE_PHOTO['image_url'], 'revision': 'synthetic-reference-1'}}
                if case == 'public_reference' else {}))
    visible, terminal, errors = '', None, 0
    async with asyncio.timeout(timeout + 15):
        async for line in turn_events(run):
            event = json.loads(line)
            elapsed = time.perf_counter() - started
            if event['type'] == 'text_delta' and event.get('text'):
                timings.setdefault('first_visible_text_s', elapsed)
                visible += event['text']
            if event['type'] == 'reply_complete': timings['validated_question_s'] = elapsed
            if event['type'] == 'conversation_saved': timings['conversation_saved_s'] = elapsed
            if event['type'] == 'error': errors += 1
            if event['type'] == 'result': terminal = event['data']
    saved = storage.interview_turn_by_id(storage.project_id, turn_id) or {}
    result = {'case': case, 'timings': {k: round(v, 3) for k, v in timings.items()}, **receipt,
        'status': 'saved' if terminal and terminal.get('conversation_saved') and not errors else 'failed',
        'errors': errors, 'language': storage.profile()['preferred_language'],
        'work_mode': (saved.get('plan') or {}).get('work', {}).get('mode'),
        'question_count': visible.count('?') + visible.count('？'),
        'candidate_count': len((saved.get('plan') or {}).get('candidates', [])),
        'provider_request_count': None, 'effective_effort': None}
    if review: result['synthetic_visible_reply'] = visible
    return result


@contextmanager
def isolated_settings():
    keys = ['MEMORY_SPARK_COLLECTOR_' + name for name in ('MODEL', 'REASONING_EFFORT', 'PROMPT_VERSION')]
    keys += ['MEMORY_SPARK_TASK_DB', 'MEMORY_SPARK_LEGACY_CODEX_HOME']
    previous = {key: os.environ.get(key) for key in keys}
    try:
        os.environ.pop('MEMORY_SPARK_TASK_DB', None)
        os.environ.pop('MEMORY_SPARK_LEGACY_CODEX_HOME', None)
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


async def campaign(timeout=120, deadline=1200, review=False, *, candidate_model=None,
        candidate_effort='max', candidate_prompt_version='compact-v1', extended=False):
    """24 (extended: 42) foreground generations; no live workspace calls.

    Extended adds matched short/long-stress/Family/reference cases and one
    unpaired, actual candidate-history rollback per language. It is not a
    representative quality-equivalence or production-tail evaluation.
    """
    source_root = Path(__file__).resolve().parents[1]
    source_files = ['apps/api/codex_runtime.py', 'apps/api/codex_worker_service.py',
        'apps/api/collector_configuration.py', 'apps/api/collector_prompt.py',
        'apps/api/interview_plan.py', 'apps/api/conversation_locale.py',
        'apps/api/agent_lock.py', 'apps/api/task_queue.py',
        'apps/api/codex_agent.py', 'apps/api/trajectory_evaluation.py',
        'apps/api/evaluation_cases.py', 'apps/api/turn_stream.py',
        'scripts/profile_first_reply.py', 'scripts/profile_conversation_latency.py']
    model = os.getenv('MEMORY_SPARK_LLM_MODEL', 'gpt-5.6-luna-pooled')
    try:
        version = subprocess.check_output([os.getenv('MEMORY_SPARK_CODEX_BIN', 'codex'), '--version'],
            text=True, stderr=subprocess.DEVNULL, timeout=5).strip()
        version = version if version.startswith('codex-cli ') and len(version) < 80 else None
    except (OSError, subprocess.SubprocessError):
        version = None
    try:
        revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'],
            text=True, stderr=subprocess.DEVNULL, timeout=5).strip()
    except (OSError, subprocess.SubprocessError):
        # Deployed worker images have no Git metadata; retain the source hash
        # and record the verified deployment revision in the operator receipt.
        revision = None
    variants = {'baseline': {'model': model, 'requested_effort': 'max', 'prompt_version': 'legacy'},
        'candidate': {'model': candidate_model or model, 'requested_effort': candidate_effort,
            'prompt_version': candidate_prompt_version}}
    case_count = 10 if extended else 6
    budget = case_count * 4 + (2 if extended else 0)
    frozen = {'dataset': 'issue53-quality-first/3' if extended else 'issue53-quality-first/2',
        'revision': revision, 'cases_per_language': case_count,
        'rollback_generations': 2 if extended else 0,
        'appserver_version': version,
        'source_sha256': hashlib.sha256(b''.join((source_root / p).read_bytes() for p in source_files)).hexdigest(),
        'foreground_generation_budget': budget, 'appserver_turn_budget': budget * 2,
        'per_generation_timeout_s': timeout, 'campaign_deadline_s': deadline,
        'variants': variants,
        'acceptance': 'Exploratory only: review grounding, identity, uncertainty, language, photo attribution, '
            'pause and useful follow-up alongside first text, validated reply, save and failures. '
            'One pair per case cannot establish semantic equivalence or a production latency distribution.',
        'measurement': 'backend stream receipt with in-memory storage; not browser or SQL save latency'}
    print(json.dumps({'kind': 'frozen_campaign', **frozen}), flush=True)
    results = []
    # Restore process settings as well as removing temporary homes on every exit.
    async with asyncio.timeout(deadline):
        with isolated_settings(), tempfile.TemporaryDirectory(prefix='memoir-latency-') as directory:
            root = Path(directory)
            root.chmod(0o711)
            for language, cases in CASES.items():
                if extended:
                    cases = cases[:-2] + EXTRA_CASES[language] + cases[-2:]
                storage = ProfileStorage(language)
                baseline = CodexWorker(home_root=root / language / 'baseline', model=model,
                    timeout=timeout, reasoning_effort='max')
                for index, (case, text) in enumerate(cases):
                    if case == 'family':
                        storage._entitlement = {'status': 'paid', 'plan_key': 'family_memoir_v1',
                            'family_tree': True, 'timeline': True,
                            'stripe_price_id': os.getenv('STRIPE_PRICE_FAMILY', '').strip() or 'synthetic-family-price'}
                        storage._family = {'project_id': storage.project_id, 'revision': 1,
                            'people': [{'id': 'person-mother', 'name': '美' if language == 'zh-CN' else 'Mei', 'family_title': 'mother'},
                                {'id': 'person-sister', 'name': '诺拉' if language == 'zh-CN' else 'Nora', 'family_title': 'sister'}],
                            'relationships': [], 'timeline': []}
                    # Exact pre-turn copies: no independently generated history confound.
                    candidate_storage = deepcopy(storage)
                    candidate_root = root / language / f'candidate-{index}'
                    # The Linux supervisor must preserve tenant file ownership
                    # as well as mode; copytree makes saved histories root-owned.
                    subprocess.run(['cp', '-a', str(baseline.home_root), str(candidate_root)], check=True)
                    # Change only collector overrides, not other role defaults.
                    candidate = CodexWorker(home_root=candidate_root, model=model,
                        timeout=timeout, reasoning_effort='max')
                    # Alternate dispatch order to reduce route/provider-load confounds.
                    pairs = [('baseline', storage, baseline), ('candidate', candidate_storage, candidate)]
                    turn_id = str(uuid4())
                    for variant, current, worker in pairs[::1 if index % 2 == 0 else -1]:
                        settings = variants[variant]
                        os.environ['MEMORY_SPARK_COLLECTOR_MODEL'] = settings['model']
                        os.environ['MEMORY_SPARK_COLLECTOR_REASONING_EFFORT'] = settings['requested_effort']
                        os.environ['MEMORY_SPARK_COLLECTOR_PROMPT_VERSION'] = settings['prompt_version']
                        print(json.dumps({'kind': 'generation_start', 'language': language,
                            'case': case, 'variant': variant, **settings}), flush=True)
                        result = await measure(current, worker, text, case, timeout, review=review, client_turn_id=turn_id)
                        result.update(input_language=language, variant=variant, **settings)
                        results.append(result)
                        print(json.dumps({'kind': 'generation_result', **result}, ensure_ascii=False), flush=True)
                        if result['status'] != 'saved':
                            print(json.dumps({'kind': 'campaign_stopped', 'reason': 'generation_failed'}), flush=True)
                            return frozen, results
                if extended:
                    # Resume the just-generated candidate, not the baseline's
                    # thread copy. Roll back the operator overrides only.
                    for key in ('MODEL', 'REASONING_EFFORT', 'PROMPT_VERSION'):
                        os.environ.pop('MEMORY_SPARK_COLLECTOR_' + key, None)
                    settings = variants['baseline']
                    print(json.dumps({'kind': 'generation_start', 'language': language,
                        'case': 'rollback', 'variant': 'rollback', **settings}), flush=True)
                    result = await measure(candidate_storage, candidate, ROLLBACK_TEXT[language],
                        'rollback', timeout, review=review)
                    result.update(input_language=language, variant='rollback', **settings)
                    results.append(result)
                    print(json.dumps({'kind': 'generation_result', **result}, ensure_ascii=False), flush=True)
                    if result['status'] != 'saved':
                        print(json.dumps({'kind': 'campaign_stopped', 'reason': 'generation_failed'}), flush=True)
                        return frozen, results
    return frozen, results


