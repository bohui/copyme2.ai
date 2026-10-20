"""Approved direct stage attribution across real canonical dependency graphs.

Temporal, relation and other contextual dependencies remain available to the
event service but must not inflate a stage's directly assigned narrator volume.
"""
from apps.api.stage_readiness import readiness, word_equivalents
from stage_progress_fixture import save_stage_source
from test_lifetime_memory_postgres import sql, event_database, private_database, attachment_database, database, resolve
from test_shared_memory_events_postgres import rpc, literal
import pytest


def test_birth_and_relation_background_do_not_inflate_direct_childhood_evidence(sql):
    project = resolve(sql)['project_id']
    sources = [save_stage_source(sql, project, text) for text in [
        'I was born in 1950.', 'At age 6 I started school.',
        'School was in my childhood.', 'School preceded opening my bakery.',
        'At age 45 I opened a bakery.']]
    refs = [{'source_id':source['id'], 'version':source['version'], 'quote':source['text'],
             'char_start':0, 'char_end':len(source['text'])} for source in sources]
    manifest = [{'id':source['id'], 'version':source['version']} for source in sources]

    def persist(events, selected=manifest):
        rpc(sql, 'apply_user_memory_events',
            f"{literal(project)},{literal(selected)}::jsonb,{literal(events)}::jsonb")

    persist([{'kind':'event', 'title':'Birth', 'life_stage':'baby',
              'source_refs':[refs[0]], 'stage_evidence':[refs[0]]},
             {'kind':'event', 'title':'Bakery', 'life_stage':'midlife',
              'source_refs':[refs[4]], 'stage_evidence':[refs[4]]}], [manifest[0],manifest[4]])
    event = sql("select id from public.user_memory_event where data->>'title'='Bakery';").stdout.strip()
    persist([{'kind':'event', 'title':'School', 'life_stage':'childhood',
              'source_refs':[refs[1]], 'stage_evidence':[refs[2]],
              'temporal':{'expression':'age 6', 'precision':'age', 'year_start':1956,
                          'year_end':1956, 'basis':[refs[0],refs[1]]},
              'relations':[{'kind':'before', 'event_id':event, 'source_refs':[refs[3]]}]}])
    school = sql("select id from public.user_memory_event where data->>'title'='School';").stdout.strip()
    linked = sql(f"select count(*) from public.user_memory_event_source where event_id='{school}';")
    assert int(linked.stdout) == 4
    view = rpc(sql, 'read_lifetime_stage_readiness', literal(project))['stages']
    assert view['baby'] == readiness(word_equivalents(sources[0]['text']))
    expected = readiness(sum(word_equivalents(source['text']) for source in sources[1:3]))
    assert view['childhood'] == expected
    assert view['midlife'] == readiness(word_equivalents(sources[4]['text']))
    assert view['adolescence'] == readiness(0)
    # Removing background changes neither direct stage total.
    from test_agent_commit_postgres import OWNER
    sql(f"insert into public.user_memory_event_source_exclusion values('{OWNER}',{literal(project)},"
        f"'{school}','{sources[0]['id']}','{OWNER}','Synthetic exclusion',1);")
    fresh = rpc(sql, 'read_lifetime_stage_readiness', literal(project))['stages']
    assert fresh['baby'] == view['baby']
    assert fresh['childhood'] == expected


@pytest.mark.parametrize('shared', [False,True])
def test_direct_multi_stage_attribution_is_supported_without_counting_whole_source_context(sql, shared):
    project = resolve(sql)['project_id']
    if shared:
        text = 'Our family custom continued from childhood into midlife.'
        pieces = [text,text]
    else:
        pieces = ['During childhood I cycled to school.', 'During midlife I opened a bakery.']
        text = ' '.join(pieces)
    source = save_stage_source(sql, project, text)
    background = save_stage_source(sql, project, 'I was born in 1950.')
    def ref(item, quote):
        start = item['text'].index(quote)
        return {'source_id':item['id'], 'version':item['version'], 'quote':quote,
                'char_start':start, 'char_end':start+len(quote)}
    birth = ref(background,background['text'])
    proposals = [{'kind':'event','title':stage,'life_stage':stage,
                  'source_refs':[ref(source,piece)], 'stage_evidence':[ref(source,piece)],
                  'temporal':{'expression':'unknown','precision':'unknown','basis':[birth]}}
                 for stage,piece in zip(['childhood','midlife'],pieces)]
    manifest = [{'id':item['id'],'version':item['version']} for item in [source,background]]
    rpc(sql,'apply_user_memory_events',f"{literal(project)},{literal(manifest)}::jsonb,{literal(proposals)}::jsonb")
    stages = rpc(sql,'read_lifetime_stage_readiness',literal(project))['stages']
    assert stages['childhood'] == readiness(word_equivalents(pieces[0]))
    assert stages['midlife'] == readiness(word_equivalents(pieces[1]))
    assert stages['baby'] == readiness(0)


def test_duplicate_and_overlapping_direct_spans_count_once_per_stage(sql):
    from stage_progress_fixture import link_stage
    project = resolve(sql)['project_id']
    source = save_stage_source(sql,project,'童'*200)
    event = link_stage(sql,project,source,'childhood',0,150)
    link_stage(sql,project,source,'childhood',50,200,event)
    link_stage(sql,project,source,'childhood',0,150)
    stages = rpc(sql,'read_lifetime_stage_readiness',literal(project))['stages']
    assert stages['childhood'] == readiness(200)
    assert stages['midlife'] == readiness(0)


@pytest.mark.parametrize('size', [1000,5000])
def test_bounded_large_history_readiness_query_plan(sql, tmp_path, monkeypatch, size):
    """Bounded synthetic projection benchmark; no production SLA assertion."""
    import json
    import os
    from pathlib import Path
    from test_agent_commit_postgres import OWNER, as_user
    monkeypatch.setitem(sql.env, 'PGOPTIONS', '-c statement_timeout=20s')
    identity = resolve(sql)
    project = literal(identity['project_id'])
    # Bulk seed only the relational projection being measured. Ingestion,
    # extraction and publication are not claimed by this cost experiment.
    sql(f"""begin; set local statement_timeout='30s';
      insert into public.user_narrator_source(user_id,project_id,id,client_turn_id,sequence,text,kind,language,processing_status)
      select '{OWNER}',{project},md5('cost-source'||n)::uuid,md5('cost-turn'||n)::uuid,n,
        repeat('memory ',512),'narrator_chat','en-AU','succeeded' from generate_series(1,{size}) n;
      insert into public.user_narrator_source_version(user_id,project_id,source_id,version,text,language)
      select user_id,project_id,id,version,text,language from public.user_narrator_source;
      insert into public.user_memory(id,user_id,project_id,client_turn_id,kind,content,life_stage)
      select md5('cost-memory'||sequence)::uuid,user_id,project_id,client_turn_id,'agent',
        'Storyteller: '||text||E'\\nMemory Spark: synthetic reply','unplaced' from public.user_narrator_source;
      insert into public.user_lifetime_reply
      select user_id,'{identity['conversation_id']}',client_turn_id,id,1,1,1,0,0,'fixture-model','lifetime-v1'
        from public.user_memory where user_id='{OWNER}' and project_id={project};
      insert into public.user_memory_event(user_id,project_id,id,kind,life_stage,status,data,change_sequence)
      select user_id,project_id,'cost-event-'||sequence,'event',
        (array['baby','childhood','adolescence','young_adulthood','midlife','later_life'])[1+(sequence%6)::int],
        'active',jsonb_build_object('title','Synthetic cost event','stage_evidence',
          (select jsonb_agg(jsonb_build_object('source_id',s.id,'version',s.version,'char_start',offset_value,
             'char_end',offset_value+600,'quote',substring(s.text from offset_value+1 for 600)))
           from unnest(array[0,300,600]) offset_value)),sequence from public.user_narrator_source s;
      insert into public.user_memory_event_source
      select s.user_id,s.project_id,'cost-event-'||s.sequence,s.id,s.version,md5(offset_value::text),
        jsonb_build_object('source_id',s.id,'version',s.version,'char_start',offset_value,'char_end',offset_value+600,
          'quote',substring(s.text from offset_value+1 for 600)),'primary'
      from public.user_narrator_source s cross join unnest(array[0,300,600]) offset_value;
      update public.user_memoir_project set source_sequence={size},event_sequence={size},extraction_cursor={size}
        where user_id='{OWNER}' and project_id={project};
      commit; analyze public.user_narrator_source; analyze public.user_memory;
      analyze public.user_lifetime_reply; analyze public.user_memory_event; analyze public.user_memory_event_source;
      analyze public.user_lifetime_stage_volume;""")
    view = rpc(sql, 'read_lifetime_stage_readiness', project)
    assert sum(value['word_equivalents'] for value in view['stages'].values()) == size * word_equivalents(('memory '*512)[:1200])
    assert len(view['stages']) == 6 and view['pending'] is False
    plans = []
    for _ in range(3):
        result = sql(as_user("set statement_timeout='20s'; explain (analyze,buffers,format json) "
            f"select public.read_lifetime_stage_readiness({project});"))
        plans.append(json.loads(result.stdout)[0])
    definition = sql("select pg_get_functiondef('public.read_lifetime_stage_readiness(text)'::regprocedure);").stdout
    query = definition[definition.index('with transferred_memories'):definition.index(' into result from counts;')] + ' from counts'
    query = query.replace('p_project_id', project)
    # The original SECURITY DEFINER runs with this fixture owner and explicit
    # auth.uid filters. Inline its aggregation to expose the inner query plan.
    inner = sql(f"set request.jwt.claim.sub='{OWNER}'; set statement_timeout='20s'; "
        f"explain (analyze,buffers,format json) {query};")
    report = {'sources':size, 'original_characters_per_source':3584, 'evidence_links':size*3,
              'overlapping_spans_per_source':3, 'rpc_plans':plans,
              'aggregation_plan':json.loads(inner.stdout)[0],
              'scope':'Synthetic isolated PostgreSQL projection only; not a production SLA or concurrency test.'}
    path = tmp_path / f'readiness-query-{size}.json'
    if os.getenv('MEMOIR_READINESS_COST_REPORT'):
        path = Path(os.environ['MEMOIR_READINESS_COST_REPORT']) / path.name
        path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'sources':size, 'rpc_ms':[plan['Execution Time'] for plan in plans],
                      'aggregation_ms':report['aggregation_plan']['Execution Time'], 'report':str(path)}))
