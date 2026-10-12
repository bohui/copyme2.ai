from uuid import uuid4
from apps.api.lifetime_memory_contracts import IdentityEnvelope,ContextBudget
from apps.api.lifetime_memory_context import ContextSource,TailCoverage
from apps.api.lifetime_memory_service import LifetimeMemoryService,MaintenancePending
from test_lifetime_memory_postgres import sql,event_database,private_database,attachment_database,database
from test_agent_commit_postgres import OWNER,OLD,as_user
from test_shared_memory_events_postgres import rpc,literal


def test_real_10000_turn_admission_early_edit_pagination_and_cold_context(sql):
    sql.env['PGOPTIONS']='-c statement_timeout=90s'
    identity=rpc(sql,'resolve_lifetime_conversation','null');project=identity['project_id']
    # Real owner-scoped admission RPC for all 10k inputs. No service bypass rows.
    # Separate bounded transactions model ordinary accepted turns; one giant
    # 10k-write transaction creates artificial MVCC row-version chains.
    import time
    started=time.monotonic()
    for first in range(1,10001,500):
      sql(as_user(f"""set statement_timeout='90s';do $do$ declare recalled jsonb; begin for n in {first}..{first+499} loop
      perform public.accept_user_narrator_source('{project}',gen_random_uuid(),
        case when n=3 then 'At school I carried a rare blue umbrella.' when n%2=0 then '我小时候住在北京，周末跟家人一起去公园。回忆编号 '||n else 'Synthetic recollection number '||n||'. I lived in Sydney and visited the garden.' end);
      if n=9900 then
        recalled:=public.read_lifetime_source_page('{identity['conversation_id']}',1,null,8,'rare blue umbrella');
        if recalled->'records'->0->>'text' is distinct from 'At school I carried a rare blue umbrella.'
          or (recalled->'records'->0->>'sequence')::bigint<>3
          or (recalled->'records'->0->>'version')::bigint<>1
          or (recalled->'records'->0->>'char_start')::integer<>0 then
          raise exception 'turn 9900 must recover exact authorized turn3 evidence'; end if;
      end if;
    end loop; end $do$;"""))
      print(f"Accepted {first+499}/10000 in {time.monotonic()-started:.2f}s",flush=True)
    assert sql('select count(*) from public.user_narrator_source;').stdout.strip()=='10000'
    assert int(sql('select sum(length(text)) from public.user_narrator_source;').stdout.strip())>120000
    # Exhaust every stable page, checking each returned byte and source identity
    # without loading a lifetime collection into the application or a model.
    cursor=None;expected=1
    while True:
        page=rpc(sql,'read_lifetime_source_page',f"'{identity['conversation_id']}',1,{literal(cursor) if cursor else 'null'},32,''")
        records=page['records']
        assert len(records)<=32
        assert [item['sequence'] for item in records]==list(range(expected,expected+len(records)))
        assert all(item['char_start']==0 for item in records)
        valid=sql(as_user(f"""select count(*) from jsonb_array_elements({literal(records)}::jsonb) item
          join public.user_narrator_source s on s.user_id=auth.uid() and s.id=(item->>'source_id')::uuid
          where s.version=(item->>'version')::bigint and s.text=item->>'text'
            and length(s.text)=(item->>'char_end')::integer;"""))
        assert int(valid.stdout.strip())==len(records)
        expected+=len(records)
        if page['complete']:break
        assert page['next_cursor'] and page['next_cursor']!=cursor
        cursor=page['next_cursor']
    assert expected==10001
    print(f"Paginated all10000 exact originals in {time.monotonic()-started:.2f}s",flush=True)
    early=rpc(sql,'read_lifetime_source_page',f"'{identity['conversation_id']}',1,null,8,'umbrella'")['records'][0]
    rpc(sql,'change_user_narrator_source',f"'{project}','{early['source_id']}',1,'edit','At school I carried a rare green umbrella.'")
    current=rpc(sql,'accept_user_narrator_source',f"'{project}','{uuid4()}','What color was the rare umbrella?'")
    sql(as_user(f"select public.acquire_user_agent_turn_lease('{OLD}',900);"))
    fence=rpc(sql,'capture_lifetime_fence',f"'{identity['conversation_id']}','{OLD}'")
    def call(name,**args):
        values=[]
        for key,value in args.items():
            encoded=literal(value)+'::jsonb' if isinstance(value,(dict,list)) else 'null' if value is None else str(value) if isinstance(value,int) else literal(value)
            values.append(key+'=>'+encoded)
        return rpc(sql,name,','.join(values))
    owner=IdentityEnvelope.model_validate({k:v for k,v in identity.items() if k!='outcome'})
    budget=ContextBudget(model='synthetic-byte-bpe',context_window=32768,input_budget=24000,output_headroom=4096)
    service=LifetimeMemoryService(call,budget=budget)
    source=ContextSource(identity=owner,policy_epoch=2,source_id=current['id'],version=1,sequence=current['sequence'],original=current['text'],language='en-AU')
    proof_calls=0
    while True:
        try:
            packet=service.assemble(fence=fence,current=source,instructions='Use canonical evidence only.',tail=[],
                tail_coverage=TailCoverage(identity=owner,policy_epoch=2,after_sequence=0,through_sequence=current['sequence']-1,complete=False))
            break
        except MaintenancePending:
            proof_calls+=1
            print(f'Compaction maintenance batch {proof_calls}',flush=True)
            assert proof_calls<50
    assert 1<proof_calls<50
    assert packet['checkpoint']['coverage_end']==10001
    assert packet['input_tokens_upper_bound']<=budget.input_budget
    fact=next(row for row in packet['retrieved'] if row['source_id']==early['source_id'])
    assert fact['original']=='At school I carried a rare green umbrella.' and fact['version']==2
    assert sql('select count(*) from public.user_lifetime_covered_evidence;').stdout.strip()=='10001'
