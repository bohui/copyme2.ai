import asyncio
from contextlib import asynccontextmanager
import base64
import json
import sys
import pytest
from pathlib import Path

from apps.api.codex_agent import CodexConnection
from apps.api.codex_runtime import (
    CodexRuntime,
    build_conversation_system_prompt,
    build_loop_trace,
    build_system_prompt,
    build_workspace_extraction_prompt,
)
from apps.api.trajectory_evaluation import TrajectoryRecorder


def test_loop_trace_exposes_actions_without_private_model_reasoning():
    trace = build_loop_trace(memory_count=2, resumed=True, saved_paths=3)

    assert trace[0]["label"] == "Analyze"
    assert any(step["label"] == "memory.search" for step in trace)
    assert any(step["label"] == "codex.thread.resume" for step in trace)
    assert any(step["label"] == "memory.save" for step in trace)
    assert trace[-1]["label"] == "Respond"
    assert all("chain-of-thought" not in step["detail"].lower() for step in trace)


def test_system_prompt_requires_simplified_chinese_responses():
    prompt = build_system_prompt("(none)", language="zh-CN")

    assert "简体中文" in prompt
    assert "不要用英语回答" in prompt


def test_visible_collector_prompt_is_separate_from_workspace_markers():
    conversation = build_conversation_system_prompt('(none)', language='en-AU')
    workspace = build_workspace_extraction_prompt('(none)', language='en-AU')

    assert '[[MEMORY_SPARK_PROFILE]]' not in conversation
    assert '[[MEMORY_SPARK_PLACE_JOURNEY]]' not in conversation
    assert '[[MEMORY_SPARK_PROFILE]]' in workspace
    assert 'Workspace extraction contract' in workspace


def test_collector_prompt_reviews_breadth_after_twenty_focused_turns():
    before_checkpoint = build_conversation_system_prompt(
        '(none)', language='en-AU', conversation_rounds_completed=19
    )
    checkpoint = build_conversation_system_prompt(
        '(none)', language='en-AU', conversation_rounds_completed=20
    )

    assert 'A breadth review is due after 1 more focused turn' in before_checkpoint
    assert 'This is a breadth-review checkpoint' in checkpoint
    assert 'one promising, evidence-grounded area' in checkpoint
    assert 'do not force a topic change' in checkpoint.lower()


def test_workspace_extraction_retries_only_missing_family_domains_without_synthesizing(monkeypatch):
    runtime = CodexRuntime(worker_url='http://worker', worker_secret='secret')
    calls = []

    async def worker_turn(**kwargs):
        focus = kwargs.get('extraction_focus')
        calls.append(focus)
        if focus is None:
            return {'reply': '[[MEMORY_SPARK_PROFILE]]{}[[/MEMORY_SPARK_PROFILE]]'}
        if focus == 'family_tree':
            return {
                'reply': (
                    '[[MEMORY_SPARK_FAMILY_TREE]]'
                    '{"people":[{"id":"p-nora","name":"Nora","family_title":"sister"}],"relationships":[]}'
                    '[[/MEMORY_SPARK_FAMILY_TREE]]'
                )
            }
        return {
            'reply': (
                '[[MEMORY_SPARK_AUTHOR_TIMELINE]]'
                '{"timeline":[{"id":"e-1","kind":"event","title":"Was born in Hobart",'
                '"date_expression":"unknown","precision":"unknown","place":"Hobart"}]}'
                '[[/MEMORY_SPARK_AUTHOR_TIMELINE]]'
            )
        }

    monkeypatch.setattr(runtime, '_worker_turn', worker_turn)
    reply = asyncio.run(runtime._workspace_extraction(
        user_id='synthetic-user', memories=[], profile={}, place_journey=None,
        family_enabled=True, family_context=None, project_id=None,
        text='I was born in Hobart. My sister Nora remembers it.', language='en-AU',
    ))

    assert calls == [None, 'family_tree', 'author_timeline']
    assert 'MEMORY_SPARK_FAMILY_TREE' in reply
    assert 'MEMORY_SPARK_AUTHOR_TIMELINE' in reply


def test_workspace_extraction_appends_worker_and_family_recovery_trajectory(monkeypatch):
    runtime = CodexRuntime(worker_url='http://worker', worker_secret='secret')
    outer = TrajectoryRecorder({'run_id': 'run-1', 'case_id': 'case-1'})
    calls = []

    async def worker_turn(**kwargs):
        focus = kwargs.get('extraction_focus')
        calls.append(focus)
        worker = TrajectoryRecorder({'run_id': 'run-1', 'case_id': 'case-1'})
        worker_step = worker.record(
            'codex',
            'tool.call',
            input={'name': 'memory.search', 'arguments': {'query': focus or 'broad'}},
            metadata={'parent_observation_id': 'worker-root'},
        )
        worker_step['observation_id'] = f'worker-observation-{focus or "broad"}'
        worker_step['parent_observation_id'] = 'worker-root'
        worker.finish('')
        return {'reply': '[[MEMORY_SPARK_PROFILE]]{}[[/MEMORY_SPARK_PROFILE]]', 'trajectory': worker.payload()}

    monkeypatch.setattr(runtime, '_worker_turn', worker_turn)
    asyncio.run(runtime._workspace_extraction(
        user_id='synthetic-user', memories=[], profile={}, place_journey=None,
        family_enabled=True, family_context=None, project_id=None,
        text='I was born in Hobart. My sister Nora remembers it.', language='en-AU',
        trajectory=outer,
    ))

    actions = [step['action'] for step in outer.payload()['steps']]
    assert calls == [None, 'family_tree', 'author_timeline']
    assert actions == [
        'tool.call',
        'workspace.worker.completed',
        'workspace.family_recovery.requested',
        'tool.call',
        'workspace.worker.completed',
        'workspace.family_recovery.requested',
        'tool.call',
        'workspace.worker.completed',
    ]
    assert [step['observation_id'] for step in outer.payload()['steps'] if step.get('observation_id')] == [
        'worker-observation-broad',
        'worker-observation-family_tree',
        'worker-observation-author_timeline',
    ]


def test_workspace_extraction_records_focused_recovery_failure(monkeypatch):
    runtime = CodexRuntime(worker_url='http://worker', worker_secret='secret')
    outer = TrajectoryRecorder({'run_id': 'run-1', 'case_id': 'case-1'})

    async def worker_turn(**kwargs):
        if kwargs.get('extraction_focus') == 'family_tree':
            raise RuntimeError('synthetic recovery failure')
        return {'reply': '[[MEMORY_SPARK_PROFILE]]{}[[/MEMORY_SPARK_PROFILE]]'}

    monkeypatch.setattr(runtime, '_worker_turn', worker_turn)
    asyncio.run(runtime._workspace_extraction(
        user_id='synthetic-user', memories=[], profile={}, place_journey=None,
        family_enabled=True, family_context=None, project_id=None,
        text='I was born in Hobart. My sister Nora remembers it.', language='en-AU',
        trajectory=outer,
    ))

    failure = next(step for step in outer.payload()['steps'] if step['action'] == 'workspace.family_recovery.failed')
    assert failure['output'] == {'error_type': 'RuntimeError', 'skill': 'memoir-family-tree'}


def test_workspace_extraction_does_not_invent_missing_domain_markers(monkeypatch):
    runtime = CodexRuntime(worker_url='http://worker', worker_secret='secret')

    async def worker_turn(**kwargs):
        return {'reply': ''}

    monkeypatch.setattr(runtime, '_worker_turn', worker_turn)
    reply = asyncio.run(runtime._workspace_extraction(
        user_id='synthetic-user', memories=[], profile={}, place_journey=None,
        family_enabled=True, family_context=None, project_id=None,
        text='Please keep the uncertainty clear and ask me one question.', language='en-AU',
    ))

    assert 'MEMORY_SPARK_FAMILY_TREE' not in reply
    assert 'MEMORY_SPARK_AUTHOR_TIMELINE' not in reply


@pytest.mark.parametrize('text', [
    'I bought my first house.',
    'I retired after years at the workshop.',
    'I often remember the day I moved to Hobart in 1980.',
    'I moved in 1980, not 1981; please correct my timeline.',
])
def test_grounded_timeline_marker_survives_when_recovery_router_has_no_focus_cue(text, monkeypatch):
    runtime = CodexRuntime(worker_url='http://worker', worker_secret='secret')

    async def worker_turn(**kwargs):
        return {
            'reply': (
                '[[MEMORY_SPARK_AUTHOR_TIMELINE]]'
                '{"timeline":[{"id":"event","kind":"event","title":"Grounded event",'
                '"date_expression":"unknown","precision":"unknown"}]}'
                '[[/MEMORY_SPARK_AUTHOR_TIMELINE]]'
            )
        }

    monkeypatch.setattr(runtime, '_worker_turn', worker_turn)
    reply = asyncio.run(runtime._workspace_extraction(
        user_id='synthetic-user', memories=[], profile={}, place_journey=None,
        family_enabled=True, family_context=None, project_id=None,
        text=text, language='en-AU',
    ))

    assert 'MEMORY_SPARK_AUTHOR_TIMELINE' in reply


def test_workspace_extraction_skips_unrelated_focused_recovery_passes(monkeypatch):
    runtime = CodexRuntime(worker_url='http://worker', worker_secret='secret')
    calls = []

    async def worker_turn(**kwargs):
        calls.append(kwargs.get('extraction_focus'))
        return {'reply': '[[MEMORY_SPARK_PROFILE]]{}[[/MEMORY_SPARK_PROFILE]]'}

    monkeypatch.setattr(runtime, '_worker_turn', worker_turn)
    asyncio.run(runtime._workspace_extraction(
        user_id='synthetic-user', memories=[], profile={}, place_journey=None,
        family_enabled=True, family_context=None, project_id=None,
        text='Please keep the uncertainty clear and ask me one question.', language='en-AU',
    ))

    assert calls == [None]


@pytest.mark.parametrize('text', [
    '晚年我有时只记得泡茶时的声音，这些反思不一定应该成为有日期的事件。',
    'I am unsure whether Ben left the neighbourhood before or after my final school year.',
])
def test_workspace_extraction_does_not_recover_timeline_for_reflection_or_other_person(text, monkeypatch):
    runtime = CodexRuntime(worker_url='http://worker', worker_secret='secret')
    calls = []

    async def worker_turn(**kwargs):
        calls.append(kwargs.get('extraction_focus'))
        return {'reply': '[[MEMORY_SPARK_PROFILE]]{}[[/MEMORY_SPARK_PROFILE]]'}

    monkeypatch.setattr(runtime, '_worker_turn', worker_turn)
    asyncio.run(runtime._workspace_extraction(
        user_id='synthetic-user', memories=[], profile={}, place_journey=None,
        family_enabled=True, family_context=None, project_id=None,
        text=text, language='en-AU',
    ))

    assert calls == [None]


@pytest.mark.parametrize('text', [
    '晚年我有时只记得泡茶时的声音，这些反思不一定应该成为有日期的事件。',
    'Please do not put this reflection on my timeline.',
])
def test_workspace_extraction_drops_model_timeline_marker_for_explicit_negative_text(monkeypatch, text):
    runtime = CodexRuntime(worker_url='http://worker', worker_secret='secret')

    async def worker_turn(**kwargs):
        return {
            'reply': (
                '[[MEMORY_SPARK_PROFILE]]{}[[/MEMORY_SPARK_PROFILE]]'
                '[[MEMORY_SPARK_AUTHOR_TIMELINE]]'
                '{"timeline":[{"id":"e-reflection","title":"Reflection",'
                '"date_expression":"later life"}]}'
                '[[/MEMORY_SPARK_AUTHOR_TIMELINE]]'
            )
        }

    monkeypatch.setattr(runtime, '_worker_turn', worker_turn)
    reply = asyncio.run(runtime._workspace_extraction(
        user_id='synthetic-user', memories=[], profile={}, place_journey=None,
        family_enabled=True, family_context=None, project_id=None,
        text=text,
        language='zh-CN',
    ))

    assert 'MEMORY_SPARK_AUTHOR_TIMELINE' not in reply


@pytest.mark.parametrize('text', [
    'Please preserve the difference between what June remembers and what I directly remember from toddlerhood.',
    'In later life I sometimes repair a small object just to remember the patience of the old bench.',
    '晚年我有时只记录一片叶子的颜色，这种回望没有可靠日期。',
    'I am unsure whether Ben left the neighbourhood before or after my final school year.',
])
def test_workspace_extraction_keeps_model_timeline_marker_for_advisory_context(monkeypatch, text):
    runtime = CodexRuntime(worker_url='http://worker', worker_secret='secret')

    async def worker_turn(**kwargs):
        return {
            'reply': (
                '[[MEMORY_SPARK_PROFILE]]{}[[/MEMORY_SPARK_PROFILE]]'
                '[[MEMORY_SPARK_AUTHOR_TIMELINE]]'
                '{"timeline":[{"id":"e-reflection","title":"Reflection",'
                '"date_expression":"later life"}]}'
                '[[/MEMORY_SPARK_AUTHOR_TIMELINE]]'
            )
        }

    monkeypatch.setattr(runtime, '_worker_turn', worker_turn)
    reply = asyncio.run(runtime._workspace_extraction(
        user_id='synthetic-user', memories=[], profile={}, place_journey=None,
        family_enabled=True, family_context=None, project_id=None,
        text=text,
        language='zh-CN',
    ))

    assert 'MEMORY_SPARK_AUTHOR_TIMELINE' in reply


@pytest.mark.parametrize('text', [
    'I am unsure whether Ben left the neighbourhood before or after my final school year. I moved to Hobart in 1985.',
    'In later life I sometimes repair a small object just to remember the patience of the old bench. I moved to Hobart in 1985.',
    'I am unsure whether Ben left the neighbourhood before or after my final school year. I had moved to Hobart in 1985.',
    'In later life I sometimes repair a small object just to remember the patience of the old bench. I retired in 2012.',
    '晚年我有时只记录一片叶子的颜色，这种回望没有可靠日期。我在2012年退休。',
    'Please preserve the difference between what June remembers and what I directly remember from toddlerhood. I moved to Hobart during childhood.',
    'I retired in 2012, but in later life I sometimes repair a small object just to remember the patience of the old bench.',
])
def test_workspace_extraction_preserves_independent_event_in_mixed_negative_turn(monkeypatch, text):
    runtime = CodexRuntime(worker_url='http://worker', worker_secret='secret')

    async def worker_turn(**kwargs):
        return {
            'reply': (
                '[[MEMORY_SPARK_PROFILE]]{}[[/MEMORY_SPARK_PROFILE]]'
                '[[MEMORY_SPARK_AUTHOR_TIMELINE]]'
                '{"timeline":[{"id":"e-hobart-1985","title":"Moved to Hobart",'
                '"date_expression":"1985","precision":"year"}]}'
                '[[/MEMORY_SPARK_AUTHOR_TIMELINE]]'
            )
        }

    monkeypatch.setattr(runtime, '_worker_turn', worker_turn)
    reply = asyncio.run(runtime._workspace_extraction(
        user_id='synthetic-user', memories=[], profile={}, place_journey=None,
        family_enabled=True, family_context=None, project_id=None,
        text=text, language='en-AU',
    ))

    assert 'MEMORY_SPARK_AUTHOR_TIMELINE' in reply


def test_workspace_extraction_recovers_known_person_without_repeated_kinship_title(monkeypatch):
    runtime = CodexRuntime(worker_url='http://worker', worker_secret='secret')
    calls = []

    async def worker_turn(**kwargs):
        calls.append(kwargs.get('extraction_focus'))
        if kwargs.get('extraction_focus') == 'family_tree':
            return {'reply': '[[MEMORY_SPARK_FAMILY_TREE]]{"people":[{"id":"june","name":"June","family_title":"aunt"}],"relationships":[]}[[/MEMORY_SPARK_FAMILY_TREE]]'}
        return {'reply': '[[MEMORY_SPARK_PROFILE]]{}[[/MEMORY_SPARK_PROFILE]]'}

    monkeypatch.setattr(runtime, '_worker_turn', worker_turn)

    asyncio.run(runtime._workspace_extraction(
        user_id='synthetic-user', memories=[], profile={}, place_journey=None,
        family_enabled=True,
        family_context={'people': [{'name': 'June', 'family_title': 'aunt'}]},
        project_id=None,
        text='Please preserve the difference between what June remembers and what I directly remember.',
        language='en-AU',
    ))

    assert calls == [None, 'family_tree']


def test_workspace_recovery_routes_chinese_social_person_cues(monkeypatch):
    runtime = CodexRuntime(worker_url='http://worker', worker_secret='secret')
    calls = []

    async def worker_turn(**kwargs):
        focus = kwargs.get('extraction_focus')
        calls.append(focus)
        if focus == 'family_tree':
            return {'reply': '[[MEMORY_SPARK_FAMILY_TREE]]{"people":[{"id":"friend","name":"山里的朋友","family_title":"朋友"}],"relationships":[]}[[/MEMORY_SPARK_FAMILY_TREE]]'}
        return {'reply': '[[MEMORY_SPARK_AUTHOR_TIMELINE]]{"timeline":[{"id":"later","kind":"event","title":"Teaching tea identification","date_expression":"后来","precision":"unknown"}]}[[/MEMORY_SPARK_AUTHOR_TIMELINE]]'}

    monkeypatch.setattr(runtime, '_worker_turn', worker_turn)
    reply = asyncio.run(runtime._workspace_extraction(
        user_id='synthetic-user', memories=[], profile={}, place_journey=None,
        family_enabled=True, family_context=None, project_id=None,
        text='后来我在成都教年轻人辨茶，也常回大理看山里的朋友。', language='zh-CN',
    ))

    assert calls == [None, 'family_tree']
    assert 'MEMORY_SPARK_FAMILY_TREE' in reply


def test_workspace_recovery_routes_chinese_family_photo_permission_cue(monkeypatch):
    runtime = CodexRuntime(worker_url='http://worker', worker_secret='secret')
    calls = []

    async def worker_turn(**kwargs):
        focus = kwargs.get('extraction_focus')
        calls.append(focus)
        return {'reply': '[[MEMORY_SPARK_PROFILE]]{}[[/MEMORY_SPARK_PROFILE]]'}

    monkeypatch.setattr(runtime, '_worker_turn', worker_turn)
    asyncio.run(runtime._workspace_extraction(
        user_id='synthetic-user', memories=[], profile={}, place_journey=None,
        family_enabled=True, family_context=None, project_id=None,
        text='旧相册里有家人的脸，我没有取得每个人的发表许可。', language='zh-CN',
    ))

    assert calls == [None, 'family_tree']


def test_private_extraction_omits_the_interview_prompt_but_retains_marker_contracts():
    from apps.api.codex_runtime import MEMOIR_SYSTEM_PROMPT
    workspace = build_workspace_extraction_prompt('(none)', family_enabled=True)
    assert MEMOIR_SYSTEM_PROMPT not in workspace
    for marker in ('PROFILE', 'PLACE_JOURNEY', 'FAMILY_TREE', 'AUTHOR_TIMELINE'):
        assert f'[[MEMORY_SPARK_{marker}]]' in workspace


def test_workspace_prompt_has_independent_domain_audit_and_focused_recovery():
    workspace = build_workspace_extraction_prompt('(none)', family_enabled=True)
    focused = build_workspace_extraction_prompt(
        '(none)', family_enabled=True, focus='author_timeline'
    )

    assert 'A profile or place marker never substitutes' in workspace
    assert 'never let birth_place or story_focus replace the timeline event' in workspace
    assert 'Focused author-timeline recovery pass' in focused
    family_focused = build_workspace_extraction_prompt(
        '(none)', family_enabled=True, focus='family_tree'
    )
    assert 'Kinship titles and explicit shorthand such as `my father`' in family_focused
    assert 'At about three, I followed my father to the docks' in family_focused
    assert 'Mum grew mint beside the laundry' in family_focused


def test_memory_context_prompt_disambiguates_chinese_midlife_cue():
    workspace = build_workspace_extraction_prompt('(none)', language='zh-CN')

    assert '三十岁以后' in workspace
    assert '`midlife`' in workspace
    assert '`young_adulthood`' in workspace


def test_loop_trace_is_localized_for_simplified_chinese():
    trace = build_loop_trace(memory_count=2, resumed=False, saved_paths=1, language="zh-CN")

    assert trace[0]["label"] == "分析"
    assert trace[-1]["label"] == "回复"
    assert all("memory" not in step["detail"].lower() for step in trace)


def test_same_explicit_place_is_marked_for_new_project_activation():
    journey = {
        "schema_version": 1,
        "status": "active",
        "revision": 4,
        "place": "Geelong",
        "hierarchy": ["Earth", "Australia", "Victoria", "Geelong"],
        "granularity": "city",
        "latitude": -38.1499,
        "longitude": 144.3617,
        "duration_ms": 5200,
        "updated_at": "2026-09-26T00:00:00Z",
    }
    candidate = {key: journey[key] for key in (
        "schema_version", "place", "hierarchy", "granularity", "latitude", "longitude", "duration_ms"
    )}

    _persisted, change = asyncio.run(CodexRuntime._persist_place_journey(
        object(), object(), journey, candidate
    ))

    assert change == {"changed": False, "kind": "unchanged", "revision": 4, "mentioned": True}


def test_repeated_place_advances_its_source_sequence():
    from unittest.mock import AsyncMock, Mock

    current = {
        'schema_version': 1, 'status': 'active', 'revision': 4,
        'source_sequence': 1, 'place': 'Sydney',
        'updated_at': '2026-09-28T00:00:00Z',
        'hierarchy': ['Earth', 'Australia', 'Sydney'],
        'granularity': 'city', 'duration_ms': 5200,
    }
    storage = Mock()
    lease = Mock()
    lease.io = AsyncMock(return_value={**current, 'source_sequence': 3, 'revision': 5})
    persisted, change = asyncio.run(CodexRuntime._persist_place_journey(
        storage, lease, current, current, source_sequence=3,
    ))
    assert persisted['source_sequence'] == 3
    assert change['mentioned'] is True


def test_app_server_initialization_and_errors(tmp_path):
    server = tmp_path / 'server.py'
    server.write_text('''import sys,json
for line in sys.stdin:
 m=json.loads(line)
 if 'id' not in m: continue
 if m['method']=='initialize':
  print(json.dumps({'id':m['id'],'result':{'userAgent':'codex-test'}}),flush=True)
 else:
  print(json.dumps({'id':m['id'],'result':{'thread':{'id':'thread-123'}}}),flush=True)
''')

    async def run():
        async with CodexConnection([sys.executable, str(server)], tmp_path) as connection:
            result = await connection.request('thread/start', {'ephemeral': False})
            assert result['thread']['id'] == 'thread-123'
    asyncio.run(run())


def test_app_server_receives_absolute_home_for_relative_runtime_path(tmp_path, monkeypatch):
    server = tmp_path / 'server.py'
    server.write_text('''import json,os,sys
for line in sys.stdin:
 message=json.loads(line)
 if message.get('method') == 'initialize':
  print(json.dumps({'id':message['id'],'result':{'userAgent':'codex-test'}}),flush=True)
 elif message.get('id'):
  print(json.dumps({'id':message['id'],'result':{
   'home':os.environ['HOME'],'codex_home':os.environ['CODEX_HOME']
  }}),flush=True)
''')
    monkeypatch.chdir(tmp_path)
    relative_home = Path('var/codex-users/test-user')
    expected_home = relative_home.resolve()

    async def run():
        async with CodexConnection([sys.executable, str(server)], relative_home) as connection:
            result = await connection.request('debug/home', {})
            assert result == {
                'home': str(expected_home),
                'codex_home': str(expected_home),
            }

    asyncio.run(run())


def test_cancellation_during_spawn_still_reaps_the_child(tmp_path, monkeypatch):
    spawn = asyncio.create_subprocess_exec
    async def run():
        ready, finish = asyncio.Event(), asyncio.Event()
        async def delayed_spawn(*args, **kwargs):
            process = await spawn(*args, **kwargs)
            ready.set()
            await finish.wait()
            return process
        monkeypatch.setattr(asyncio, 'create_subprocess_exec', delayed_spawn)
        connection = CodexConnection(
            [sys.executable, '-c', 'import time; time.sleep(60)'], tmp_path)
        task = asyncio.create_task(connection.__aenter__())
        await ready.wait()
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        finish.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert connection.process.returncode is not None
    asyncio.run(run())


def test_runtime_dispatches_to_private_worker_and_syncs_allowlisted_artifacts(monkeypatch):
    class Storage:
        user_id = "11111111-1111-4111-8111-111111111111"

        def __init__(self):
            self.files = {}
            self.saved_session = None
            self.profile_data = {}
            self.place_data = None
            self.saved_place_journey = None

        def acquire_agent_turn_lease(self, token, lease_seconds):
            return True

        def renew_agent_turn_lease(self, token, lease_seconds):
            return True

        def release_agent_turn_lease(self, token):
            return True

        def agent_session(self):
            return {"codex_thread_id": "thread-old"}

        def memories(self):
            return [{"content": "A private memory"}]

        def profile(self):
            return self.profile_data

        def save_profile(self, profile):
            self.profile_data = profile

        def place_journey(self):
            return self.place_data

        def save_place_journey(self, lease_token, journey):
            self.saved_place_journey = journey
            self.place_data = {
                **journey,
                "status": "active",
                "revision": 1,
                "updated_at": "2026-09-26T00:00:00Z",
            }
            return self.place_data

        @staticmethod
        def agent_path(path):
            return path

        def commit_agent_turn(self, token, thread_id, text, source_paths):
            self.saved_session = thread_id
            return {"content": text, "kind": "agent", "source_paths": source_paths}

        def put_agent_turn_file(self, token, path, content):
            root, tail = path.split('/', 1)
            path = f'{root}/turns/{token}/{tail}'
            self.files[path] = content
            return path

    class Response:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "thread_id": "thread-new",
                "reply": (
                    "What detail stands out most?\n"
                    "[[MEMORY_SPARK_PROFILE]]"
                    '{"name":"Mina","avatar_style":"female","story_focus":{"who":"my grandmother","where":"Geelong",'
                    '"when":"the 1980s","what":"summer afternoons","life_stage":"childhood"}}'
                    "[[/MEMORY_SPARK_PROFILE]]\n"
                    "[[MEMORY_SPARK_PLACE_JOURNEY]]"
                    '{"schema_version":1,"place":"Geelong",'
                    '"hierarchy":["Earth","Australia","Victoria","Geelong"],'
                    '"granularity":"city","latitude":-38.1499,"longitude":144.3617,'
                    '"duration_ms":5200}'
                    "[[/MEMORY_SPARK_PLACE_JOURNEY]]"
                ),
                "artifacts": [{
                    "path": "sessions/thread-new.json",
                    "content": base64.b64encode(b"session state").decode("ascii"),
                }],
            }

    class Client:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.request = None

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        @asynccontextmanager
        async def stream(self, method, url, *, headers, json):
            response = await self.post(url, headers=headers, json=json)
            async def lines():
                import json as json_module
                yield json_module.dumps({'type': 'result', 'data': response.json()})
            response.aiter_lines = lines
            yield response

        async def post(self, url, *, headers, json):
            self.request = {"url": url, "headers": headers, "json": json}
            if json.get('agent_role') == 'memory_context':
                response = Response()
                response.json = lambda: {'thread_id': 'intake', 'reply': '{"preferred_language":"en-AU"}', 'artifacts': []}
                return response
            return Response()

    client = Client()
    monkeypatch.setattr("apps.api.codex_runtime.httpx.AsyncClient", lambda **kwargs: client)
    storage = Storage()

    events = []
    async def record_event(event):
        events.append(event)

    result = asyncio.run(CodexRuntime(
        worker_url="http://codex-worker:8766",
        worker_secret="worker-secret",
        model="test-model",
    ).turn(storage, "I was a child in Geelong. Please use the female timeline illustrations.", on_event=record_event))

    assert events[0]['type'] == 'progress'
    assert any(event.get('data', {}).get('id') == 'save'
               and event['data']['status'] == 'completed'
               and event['data']['detail'] == 'Conversation memory saved' for event in events)
    saved_index = next(i for i, event in enumerate(events) if event['type'] == 'conversation_saved')
    place_index = next(i for i, event in enumerate(events) if event.get('data', {}).get('skill') == 'memoir-place-journey')
    assert place_index > saved_index
    assert any(step.get('skill') == 'memoir-place-journey' for step in result['trace'])
    assert not any(step.get('skill') == 'memoir-family-tree' for step in result['trace'])
    assert events[saved_index]['data']['trace']
    assert result["trace_mode"] == "codex-worker"
    assert result["thread_id"] == "thread-new"
    path = result['source_paths'][0]
    assert path.startswith('sessions/turns/') and path.endswith('/thread-new.json')
    assert storage.saved_session == "thread-new"
    assert storage.profile_data["conversation_language"]["initialized"] is True
    assert {k:v for k,v in storage.profile_data.items() if k != "conversation_language"} == {
        "preferred_language": "en-AU",
        "name": "Mina",
        "avatar_style": "female",
        "story_focus": {
            "who": "my grandmother",
            "where": "Geelong",
            "when": "the 1980s",
            "what": "summer afternoons",
            "life_stage": "childhood",
        },
    }
    assert result["profile_updates"] == storage.profile_data
    assert storage.saved_place_journey == {
        "schema_version": 1,
        "place": "Geelong",
        "hierarchy": ["Earth", "Australia", "Victoria", "Geelong"],
        "granularity": "city",
        "latitude": -38.1499,
        "longitude": 144.3617,
        "duration_ms": 5200,
    }
    assert result["place_journey"] == {
        **storage.saved_place_journey,
        "period": "",
        "status": "active",
        "revision": 1,
        "updated_at": "2026-09-26T00:00:00Z",
    }
    assert result["place_journey_change"] == {
        "changed": True,
        "kind": "created",
        "revision": 1,
    }
    assert "MEMORY_SPARK_PLACE_JOURNEY" not in result["reply"]
    assert storage.files[path] == b"session state"
    assert client.request["url"] == "http://codex-worker:8766/internal/codex/turn"
    assert client.request["headers"]["X-Codex-Worker-Secret"] == "worker-secret"
    assert client.request["headers"]["Accept"] == "application/x-ndjson"
    assert client.request["headers"]["X-Memoir-Request-ID"] == client.request["json"]["diagnostic_request_id"]
    request_payload = dict(client.request["json"])
    diagnostic_request_id = request_payload.pop("diagnostic_request_id")
    assert diagnostic_request_id
    assert request_payload == {
        "user_id": storage.user_id,
        "thread_id": "thread-old",
        "memories": ["A private memory"],
        "profile": {"preferred_language": "en-AU", "conversation_language": storage.profile_data["conversation_language"]},
        "place_journey": {},
        "family_context": {},
        "family_enabled": False,
        "project_id": None,
        "text": "I was a child in Geelong. Please use the female timeline illustrations.",
        "model": "test-model",
        "language": "en-AU",
    }
