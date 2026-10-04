"""Response grouping and source-version boundaries for incremental composition."""
import asyncio
import pytest
from apps.api.codex_runtime import CodexRuntime
from apps.api.memoir_preview import source_snapshot, stage_source_ids


def response(id, stage=None, sequence=0, **changes):
    return {'id':id,'kind':'agent','life_stage':stage,'source_sequence':sequence,
            'content':'Storyteller: Original memory\nMemory Spark: Generated suggestion',**changes}


def test_sources_are_tagged_and_sorted_by_stage_then_capture_order():
    rows=[response('mid','midlife',1),response('a','childhood',20),
          response('z','childhood',10),response('unknown'),
          response('greeting','baby',kind='agent_greeting')]
    sources=source_snapshot(rows,'project')
    assert [s['id'] for s in sources]==['z','a','mid','unknown']
    assert sources[-1]['life_stage']=='unplaced'
    assert all(s['text']=='Original memory' for s in sources)
    assert stage_source_ids(sources)=={'childhood':['z','a'],'midlife':['mid'],'unplaced':['unknown']}
    assert source_snapshot(list(reversed(rows)),'project')==sources


def test_reassignment_and_text_edits_change_only_the_affected_source_version():
    rows=[response('a','childhood',10),response('b','midlife',20)]
    before={s['id']:s['version'] for s in source_snapshot(rows,'project')}
    rows[0]['life_stage']='later_life'
    after={s['id']:s['version'] for s in source_snapshot(rows,'project')}
    assert before['a']!=after['a'] and before['b']==after['b']
    rows[0]['content']=rows[0]['content'].replace('Original','Corrected')
    edited=source_snapshot(rows,'project')
    assert next(s for s in edited if s['id']=='a')['version']!=after['a']
    # Deletion must not renumber or re-version surviving responses.
    assert source_snapshot(rows[1:],'project')[0]==edited[0]


def test_legacy_timestamps_and_nanosecond_sequences_preserve_safe_capture_order():
    rows=[response('later','childhood',1780000000000000000),
          response('earlier','childhood',created_at='2026-01-01T00:00:00Z')]
    sources=source_snapshot(rows,'project')
    assert [s['id'] for s in sources]==['earlier','later']
    assert all(0<=s['source_order']<=9007199254740991 for s in sources)


def test_latest_response_revision_wins_and_legacy_wrappers_are_removed():
    old=response('a','childhood')
    new=response('a','midlife',content='Storyteller: The storyteller said: My garden\n'
        'Acknowledge the storyteller naturally, then ask one gentle open-ended follow-up question.\n'
        'Memory Spark: Tell me more.')
    sources=source_snapshot([old,new],'project')
    assert len(sources)==1 and sources[0]['life_stage']=='midlife'
    assert sources[0]['text']=='My garden'


@pytest.mark.parametrize('stage', ['childhood', None])
def test_workspace_tags_responses_without_places_and_never_borrows_global_focus(monkeypatch, stage):
    from test_recall import RecallStorage
    class StageStorage(RecallStorage):
        def __init__(self):
            super().__init__()
            self._profile['story_focus']={'life_stage':'midlife'}
            self.assignments=[]
        def assign_memory_stage(self, id, value):
            self.assignments.append((id,value))
            return []
    storage=StageStorage()
    runtime=CodexRuntime(worker_url='http://unused')
    async def worker(**options):
        if options.get('agent_role')=='workspace':
            marker=('[[MEMORY_SPARK_PROFILE]]{"story_focus":{"life_stage":"'+stage+'"}}[[/MEMORY_SPARK_PROFILE]]') if stage else ''
            return {'thread_id':'workspace','reply':marker,'artifacts':[]}
        return {'thread_id':'conversation','reply':'What happened next?','artifacts':[], '_workspace_capable':True}
    monkeypatch.setattr(runtime,'_worker_turn',worker)
    asyncio.run(runtime.turn(storage,'We played together after school.',project_id='project'))
    assert storage.assignments==[('reply-1',stage or 'unplaced')]
