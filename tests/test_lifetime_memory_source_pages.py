import json
from uuid import uuid4

from test_lifetime_memory_postgres import sql,event_database,private_database,attachment_database,database
from test_agent_commit_postgres import OWNER,OTHER
from test_shared_memory_events_postgres import rpc,literal


def page(sql,identity,cursor=None,query='',owner=OWNER,check=True):
    return rpc(sql,'read_lifetime_source_page',f"'{identity['conversation_id']}', 1, "+('null' if cursor is None else f"'{cursor}'")+f", 2, {literal(query)}",owner=owner,check=check)


def test_original_source_chunks_have_stable_complete_readback_and_scoped_cursors(sql):
    identity=rpc(sql,'resolve_lifetime_conversation','null')
    original='English 中文 '*700
    first=rpc(sql,'accept_user_narrator_source',f"{literal(identity['project_id'])},'{uuid4()}',{literal(original)}")
    rpc(sql,'accept_user_narrator_source',f"{literal(identity['project_id'])},'{uuid4()}','Later memory'")
    result=page(sql,identity);initial=result
    assert result['complete'] is False
    assert page(sql,identity)==result
    chunks=[]
    while True:
        assert len(result['records'])<=2
        chunks.extend(result['records'])
        if result['complete']:break
        result=page(sql,identity,result['next_cursor'])
    assert ''.join(c['text'] for c in chunks if c['source_id']==first['id'])==original
    assert len({(c['sequence'],c['char_start']) for c in chunks})==len(chunks)
    assert page(sql,identity,initial['next_cursor'],owner=OTHER,check=False).returncode!=0
    assert page(sql,identity,str(uuid4()),check=False).returncode!=0
    assert page(sql,identity,initial['next_cursor'],query='changed',check=False).returncode!=0
    rpc(sql,'change_user_narrator_source',f"{literal(identity['project_id'])},'{first['id']}',1,'withdraw',null")
    assert page(sql,identity,initial['next_cursor'],check=False).returncode!=0


def test_lexical_early_fact_retrieval_returns_canonical_original_span(sql):
    identity=rpc(sql,'resolve_lifetime_conversation','null')
    for n in range(1,5):
        text='rare blue umbrella in Chengde' if n==3 else f'Unrelated memory {n}'
        rpc(sql,'accept_user_narrator_source',f"{literal(identity['project_id'])},'{uuid4()}',{literal(text)}")
    result=page(sql,identity,query='blue umbrella')
    assert result['complete'] and len(result['records'])==1
    record=result['records'][0]
    assert record['sequence']==3 and record['version']==1
    assert record['char_start']==0 and record['char_end']==len(record['text'])


def test_early_edit_retains_explicit_superseded_position_for_coverage(sql):
    identity=rpc(sql,'resolve_lifetime_conversation','null')
    first=rpc(sql,'accept_user_narrator_source',f"{literal(identity['project_id'])},'{uuid4()}','An early memory'")
    rpc(sql,'accept_user_narrator_source',f"{literal(identity['project_id'])},'{uuid4()}','Another memory'")
    changed=rpc(sql,'change_user_narrator_source',f"{literal(identity['project_id'])},'{first['id']}',1,'edit','A corrected early memory'")
    result=rpc(sql,'read_lifetime_source_page',f"'{identity['conversation_id']}',2,null,32,''")
    assert [row['sequence'] for row in result['records']]==[1,2,3]
    assert result['records'][0]['status']=='superseded' and result['records'][0]['text'] is None
    assert result['records'][-1]['source_id']==first['id'] and result['records'][-1]['version']==2
    assert result['records'][-1]['text']==changed['text']
