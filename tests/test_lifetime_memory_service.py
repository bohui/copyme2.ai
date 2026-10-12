from uuid import uuid4

from apps.api.lifetime_memory_contracts import ContextBudget,IdentityEnvelope
from apps.api.lifetime_memory_context import ContextSource,TailCoverage
from apps.api.lifetime_memory_service import LifetimeMemoryService
from test_lifetime_memory_postgres import sql,event_database,private_database,attachment_database,database
from test_agent_commit_postgres import OLD,as_user
from test_shared_memory_events_postgres import rpc,literal


def test_measured_tail_overflow_publishes_checkpoint_and_recalls_exact_early_fact(sql):
    identity_raw=rpc(sql,'resolve_lifetime_conversation','null')
    identity=IdentityEnvelope.model_validate({k:v for k,v in identity_raw.items() if k!='outcome'})
    sources=[]
    for n in range(1,41):
        text='At school I carried a rare blue umbrella.' if n==3 else '我在悉尼生活。 My memory in Sydney. '*20
        sources.append(rpc(sql,'accept_user_narrator_source',f"{literal(identity.project_id)},'{uuid4()}',{literal(text)}"))
    current_saved=rpc(sql,'accept_user_narrator_source',f"{literal(identity.project_id)},'{uuid4()}','What color was the rare umbrella?'")
    sql(as_user(f"select public.acquire_user_agent_turn_lease('{OLD}');"))
    fence=rpc(sql,'capture_lifetime_fence',f"'{identity.conversation_id}','{OLD}'")
    def call(name,**args):
        values=[]
        for key,value in args.items():
            if isinstance(value,dict) or isinstance(value,list):encoded=literal(value)+'::jsonb'
            elif isinstance(value,int):encoded=str(value)
            elif value is None:encoded='null'
            else:encoded=literal(value)
            values.append(key+'=>'+encoded)
        return rpc(sql,name,','.join(values))
    budget=ContextBudget(model='synthetic-byte-bpe',context_window=18000,input_budget=14000,output_headroom=2000)
    service=LifetimeMemoryService(call,budget=budget)
    def source(row):
        return ContextSource(identity=identity,policy_epoch=1,source_id=row['id'],version=row['version'],sequence=row['sequence'],original=row['text'],language=row['language'])
    packet=service.assemble(fence=fence,current=source(current_saved),instructions='Canonical evidence only.',
        tail=[source(row) for row in sources],tail_coverage=TailCoverage(identity=identity,policy_epoch=1,after_sequence=0,through_sequence=40,complete=True))
    assert packet['checkpoint']['coverage_end']==40
    fact=next(row for row in packet['retrieved'] if row['source_id']==sources[2]['id'])
    assert fact['original']==sources[2]['text'] and fact['version']==1
    assert packet['input_tokens_upper_bound']<=budget.input_budget
    assert packet['source_ids'].count(current_saved['id'])==1
