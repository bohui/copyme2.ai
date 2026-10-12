"""Governed compatibility pages preserve saved legacy prose and exact provenance."""
import json
import pytest
from test_lifetime_memory_postgres import sql, event_database, private_database, attachment_database, database, resolve
from test_shared_memory_events_postgres import rpc, literal
from test_agent_commit_postgres import OWNER, OTHER


def legacy_fixture(sql, locale='en-AU', count=10, content=None):
    identity = resolve(sql)
    project = identity['project_id']
    sections=[]
    for n in range(count):
        source=rpc(sql,'accept_user_narrator_source', f"{literal(project)},'00000000-0000-4000-8000-{n:012d}','Original {n}'")
        event=f'legacy-event-{n}'
        sql(f"insert into public.user_memory_event(user_id,project_id,id,revision,kind,life_stage,status,data,change_sequence) values('{OWNER}',{literal(project)},{literal(event)},1,'event','childhood','active','{{\"title\":\"Saved event\"}}',{n+1});")
        section={'id':f'section-{n:04d}','revision':1,'fingerprint':f'fingerprint-{n}','title':f'Section {n}',
            'content':content if content is not None else f'Protected original paragraph {n}', 'event_ids':[event],
            'source_refs':[{'source_id':source['id'],'version':1,'char_start':0,'char_end':len(source['text'])}]}
        sections.append(section)
        sql(f"insert into public.user_memoir_section_revision(user_id,project_id,locale,section_id,revision,fingerprint,data,event_manifest) values('{OWNER}',{literal(project)},'{locale}',{literal(section['id'])},1,{literal(section['fingerprint'])},{literal(section)}::jsonb,{literal([{'id':event,'revision':1}])}::jsonb);")
    bundle={'sections':sections,'preview':{'title':'Saved memoir','text':'Legacy full preview must never be loaded'}}
    sql(f"insert into public.user_memoir_manuscript(user_id,project_id,locale,revision,covered_round,bundle,human_locked,eligible) values('{OWNER}',{literal(project)},'{locale}',1,5,{literal(bundle)}::jsonb,true,true);")
    return identity, sections


def test_legacy_protected_prose_pages_are_complete_without_rewriting_or_full_preview(sql):
    identity,sections=legacy_fixture(sql)
    project=identity['project_id']
    before=sql('select bundle::text from public.user_memoir_manuscript;').stdout
    head=rpc(sql,'read_lifetime_legacy_draft_head',f"{literal(project)},'en-AU'")
    assert head['preview']['text']==sections[0]['content']
    assert head['page_complete'] is False and head['publication_approved'] is False
    assert head['coverage_scope']=='legacy_saved_sections' and head['legacy'] is True
    seen=[head['preview']['text']];cursor=head['next_cursor']
    while cursor:
        page=rpc(sql,'read_lifetime_legacy_draft_page',f"{literal(project)},'{head['snapshot_id']}','{cursor}'")
        seen.extend(row['preview']['text'] for row in page['records']);cursor=page['next_cursor']
    assert seen==[section['content'] for section in sections]
    assert sql('select bundle::text from public.user_memoir_manuscript;').stdout==before
    assert 'Legacy full preview' not in json.dumps(head)


def test_large_legacy_section_is_chunked_without_losing_original_bytes(sql):
    original='记忆a'*9000
    identity,sections=legacy_fixture(sql,count=1,content=original)
    project=identity['project_id'];head=rpc(sql,'read_lifetime_legacy_draft_head',f"{literal(project)},'en-AU'")
    seen=head['preview']['text'];cursor=head['next_cursor']
    while cursor:
        page=rpc(sql,'read_lifetime_legacy_draft_page',f"{literal(project)},'{head['snapshot_id']}','{cursor}'")
        assert len(json.dumps(page).encode())<150000
        seen+=''.join(row['preview']['text'] for row in page['records']);cursor=page['next_cursor']
    assert seen==original


def test_legacy_page_rechecks_locale_owner_privacy_and_source_revision(sql):
    identity,sections=legacy_fixture(sql)
    project=identity['project_id'];head=rpc(sql,'read_lifetime_legacy_draft_head',f"{literal(project)},'en-AU'")
    assert rpc(sql,'read_lifetime_legacy_draft_page',f"{literal(project)},'{head['snapshot_id']}'",owner=OTHER,check=False).returncode
    source=sections[0]['source_refs'][0]['source_id']
    rpc(sql,'change_user_narrator_source',f"{literal(project)},'{source}',1,'withdraw',null")
    assert rpc(sql,'read_lifetime_legacy_draft_page',f"{literal(project)},'{head['snapshot_id']}'",check=False).returncode
    view=rpc(sql,'read_lifetime_legacy_draft_head',f"{literal(project)},'en-AU'")
    assert view['preview'] is None and view['original_withheld'] is True


def test_current_privacy_exclusion_withholds_legacy_prose_without_erasing_it(sql):
    identity,sections=legacy_fixture(sql)
    sql(f"insert into public.user_profile(user_id,profile) values('{OWNER}','{{\"memory_preferences\":{{\"excluded_topics\":[\"School\"]}}}}') on conflict(user_id) do update set profile=excluded.profile;")
    head=rpc(sql,'read_lifetime_legacy_draft_head',literal(identity['project_id']))
    assert head['preview'] is None and head['original_withheld'] is True
    assert head['error']=='LIFETIME_LEGACY_PROVENANCE_REQUIRED'
    assert sql('select count(*) from public.user_memoir_section_revision;').stdout.strip()=='10'


def test_repeated_protected_section_bytes_select_one_latest_revision_and_progress(sql):
    identity,sections=legacy_fixture(sql,count=2)
    sql("insert into public.user_memoir_section_revision select user_id,project_id,locale,section_id,revision+1,fingerprint,data,event_manifest from public.user_memoir_section_revision;")
    project=identity['project_id'];head=rpc(sql,'read_lifetime_legacy_draft_head',f"{literal(project)},'en-AU'")
    assert head['first_record']['section_revision']==2
    page=rpc(sql,'read_lifetime_legacy_draft_page',f"{literal(project)},'{head['snapshot_id']}','{head['next_cursor']}',1")
    assert page['records'][0]['section_id']=='section-0001' and page['complete'] is True
    assert page['next_cursor'] is None and page['records'][0]['section_revision']==2
