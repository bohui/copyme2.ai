"""Controlled Codex protocol replay; no live model or provider access."""
import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
import sys
from uuid import UUID

import pytest

from apps.api.codex_agent import CodexConnection
from apps.api.memoir_skill_agent import SkillTools, run_skill_agent
from apps.api.prompt_artifact import load_prompt_artifact, prompt_path


class Publication:
    def __init__(self):
        self.calls = 0
        self.stale = False
    @asynccontextmanager
    async def guard(self, fence):
        from apps.api.lifetime_memory_publication import PublicationUnavailable
        if self.stale:
            raise PublicationUnavailable('stale fixture')
        self.calls += 1
        yield


def params(tool, **arguments):
    return {'threadId':'thread','turnId':'turn','callId':'call', 'namespace':None,
        'tool':tool,'arguments':arguments}


def decoded(response):
    return json.loads(response['contentItems'][0]['text'])


def test_skill_selection_reads_the_actual_file_before_executor_runs():
    async def scenario():
        executed = []
        async def execute(name):
            executed.append(name)
            return {'status':'saved'}
        tools = SkillTools(['memoir-author-timeline', 'memoir-interview-guidance'], execute=execute)
        refused = await tools.call(params('memoir_execute_skill', skill='memoir-interview-guidance'))
        assert not refused['success'] and executed == []
        read = await tools.call(params('memoir_read_skill', skill='memoir-interview-guidance'))
        assert decoded(read)['instructions'] == load_prompt_artifact(prompt_path(
            'memoir/skills/memoir-interview-guidance/instructions'))
        assert tools.reads == [prompt_path('memoir/skills/memoir-interview-guidance/instructions')]
        result = await tools.call(params('memoir_execute_skill', skill='memoir-interview-guidance'))
        assert decoded(result) == {'status':'saved'}
        assert executed == ['memoir-interview-guidance']
        assert all('timeline' not in row['skill'] for row in tools.executions)
    asyncio.run(scenario())


@pytest.mark.parametrize('arguments', [
    {'skill':'memoir-story-game'},
    {'skill':'memoir-author-timeline','file':'../../README.md'},
    {'skill':'memoir-author-timeline','file':'/etc/passwd'},
    {'skill':'memoir-author-timeline','file':'references/../../../.env'},
])
def test_agent_cannot_read_skills_or_files_outside_its_catalog(arguments):
    tools = SkillTools(['memoir-author-timeline'])
    result = asyncio.run(tools.call(params('memoir_read_skill', **arguments)))
    assert not result['success'] and not tools.reads


def test_agent_can_read_a_versioned_reference_and_call_limits_are_enforced():
    tools = SkillTools(['memoir-author-timeline'], max_calls=1)
    result = asyncio.run(tools.call(params('memoir_read_skill',
        skill='memoir-author-timeline', file='references/contract.md')))
    assert result['success']
    with pytest.raises(ValueError, match='budget'):
        asyncio.run(tools.call(params('memoir_read_skill', skill='memoir-author-timeline')))


def test_real_stdio_client_handles_skill_read_and_sends_its_body_back_to_harness(tmp_path):
    server = tmp_path / 'controlled_app_server.py'
    journal = tmp_path / 'journal.json'
    server.write_text('''import json,sys
thread='thread';turn='turn'
for line in sys.stdin:
 m=json.loads(line)
 if m.get('method')=='initialize':
  print(json.dumps({'id':m['id'],'result':{}}),flush=True)
 elif m.get('method')=='thread/start':
  assert any(t['name']=='memoir_read_skill' for t in m['params']['dynamicTools'])
  print(json.dumps({'id':m['id'],'result':{'thread':{'id':thread}}}),flush=True)
 elif m.get('method')=='turn/start':
  task=json.loads(m['params']['input'][0]['text'])
  assert len(task['available_skills'])==2
  print(json.dumps({'id':m['id'],'result':{'turn':{'id':turn}}}),flush=True)
  print(json.dumps({'id':'choose-guidance','method':'item/tool/call','params':{'threadId':thread,'turnId':turn,'callId':'call','tool':'memoir_read_skill','arguments':{'skill':'memoir-interview-guidance'}}}),flush=True)
 elif m.get('id')=='choose-guidance':
  assert m['result']['success']
  content=json.loads(m['result']['contentItems'][0]['text'])
  assert '# Memoir Interview Guidance' in content['instructions']
  json.dump(content,open(sys.argv[1],'w'))
  print(json.dumps({'method':'item/completed','params':{'threadId':thread,'turnId':turn,'item':{'id':'message','type':'agentMessage','phase':'final_answer','text':'{"events":[]}'}}}),flush=True)
  print(json.dumps({'method':'turn/completed','params':{'threadId':thread,'turn':{'id':turn,'status':'completed'}}}),flush=True)
''')
    publication = Publication()
    result = asyncio.run(run_skill_agent(command=[sys.executable,str(server),str(journal)],
        home_root=tmp_path / 'homes', base_url='http://provider.invalid', api_key='synthetic',
        model='synthetic-byte-bpe', instructions=load_prompt_artifact(prompt_path('memoir/shared/background-agent')),
        packet={'work':[]}, skills=['memoir-author-timeline','memoir-interview-guidance'],
        publisher=publication, fence={}, timeout=5))
    assert json.loads(result['reply']) == {'events':[]}
    assert result['skill_receipt']['skills_read'] == ['memoir-interview-guidance']
    assert json.loads(journal.read_text())['instructions'] == load_prompt_artifact(prompt_path(
        'memoir/skills/memoir-interview-guidance/instructions'))
    assert publication.calls >= 3
    assert not list((tmp_path / 'homes').iterdir())


def test_foreign_turn_cannot_execute_a_dynamic_tool(tmp_path):
    async def scenario():
        called, sent = [], []
        async def handler(arguments):
            called.append(arguments)
        connection = CodexConnection(['unused'], tmp_path, tool_handler=handler)
        connection.active_thread, connection.active_turn = 'owned', 'current'
        async def send(message):
            sent.append(message)
        connection.send = send
        await connection.handle_event({'id':1,'method':'item/tool/call',
            'params':{'threadId':'foreign','turnId':'current'}})
        assert not called and sent[0]['error']['code'] == -32602
    asyncio.run(scenario())
