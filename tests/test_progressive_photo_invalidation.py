"""Exact progressive photo dependencies on disposable PostgreSQL."""
from copy import deepcopy

import pytest

from test_lifetime_composer_capacity import seeded_composer, section_result, service
from test_lifetime_memory_postgres import sql, event_database, private_database, attachment_database, database
from test_lifetime_review_repairs import add_photo_link
from test_shared_memory_events_postgres import literal


@pytest.mark.parametrize('action', ['update', 'delete'])
@pytest.mark.parametrize('location', ['bundle', 'proposal'])
def test_progressive_photo_change_purges_exact_asset_and_preserves_other_writing(sql, action, location):
    identity, source, lane, first = seeded_composer(sql)
    service(sql, 'yield_lifetime_memoir_lane', f"'{lane}','{first['token']}'")
    changed = add_photo_link(sql, identity, source, first)
    sibling = add_photo_link(sql, identity, source, first)
    links = {link: sql(f"select photo_id from public.user_interview_photo_link where id='{link}';").stdout.strip()
             for link in (changed, sibling)}
    page = service(sql, 'claim_memoir_lane', f"'{lane}',900")
    original = section_result(page)
    prose = original['sections'][0]
    prose.update(id='prose', chapter_id='prose')
    prose['block']['id'] = 'prose'
    original['sections'] = [prose]
    for index, (link, asset) in enumerate(links.items()):
        photo = deepcopy(prose)
        photo.update(id=f'photo-{index}', chapter_id=f'photo-{index}', content='')
        photo['block'].update(id=f'photo-{index}', type='photo', text='', asset_id=asset,
                              asset_version='1', caption='A narrator-selected childhood photo.')
        original['sections'].append(photo)
    service(sql, 'commit_lifetime_memoir_lane_page', f"'{lane}','{page['token']}',0,{literal(original)}")
    assert service(sql, 'complete_lifetime_memoir_lane', f"'{lane}','{page['token']}'")['status'] == 'saved'
    if location == 'proposal':
        # A pending protected proposal can introduce a photo absent from its original.
        sql(f"update public.user_lifetime_memoir_section set approved=true,proposal=bundle,bundle={literal({'preview':{'text':source['text']},'sections':[prose]})} where partition_key like '%:photo-0';")
    else:
        sql('update public.user_lifetime_memoir_section set human_locked=true;')
    target = sql(f"select row_to_json(s)::text from public.user_lifetime_memoir_section s where partition_key like '%:photo-0';").stdout
    assert links[changed] in target and 'progressive:' in target
    unaffected = sql(f"select row_to_json(s)::text from public.user_lifetime_memoir_section s where partition_key not like '%:photo-0' order by partition_key;").stdout
    assert links[sibling] in unaffected and source['text'] in unaffected
    rounds = sql('select count(*) from public.user_completed_round;').stdout
    sql(f"update public.user_interview_photo_link set description=description where id='{changed}';")
    assert sql(f"select row_to_json(s)::text from public.user_lifetime_memoir_section s where partition_key like '%:photo-0';").stdout == target
    if action == 'update':
        sql(f"update public.user_interview_photo_link set description='Corrected attribution' where id='{changed}';")
    else:
        sql(f"delete from public.user_interview_photo_link where id='{changed}';")
    assert sql(f"select count(*) from public.user_lifetime_memoir_section where partition_key like '%:photo-0';").stdout.strip() == '0'
    assert sql(f"select row_to_json(s)::text from public.user_lifetime_memoir_section s where partition_key not like '%:photo-0' order by partition_key;").stdout == unaffected
    assert sql('select count(*) from public.user_completed_round;').stdout == rounds


@pytest.mark.parametrize('action', ['update', 'delete'])
def test_photo_change_rejects_inflight_progressive_commit(sql, action):
    identity, source, lane, first = seeded_composer(sql)
    service(sql, 'yield_lifetime_memoir_lane', f"'{lane}','{first['token']}'")
    link = add_photo_link(sql, identity, source, first)
    page = service(sql, 'claim_memoir_lane', f"'{lane}',900")
    proposed = section_result(page)
    for phase in ('prepare', 'draft', 'review'):
        sql(f"set role service_role;select public.record_lifetime_lane_output('{lane}','{page['token']}',{page['page_number']},'{phase}','{'a'*64}','{page['page_digest']}');")
    if action == 'update':
        sql(f"update public.user_interview_photo_link set description='Corrected attribution' where id='{link}';")
    else:
        sql(f"delete from public.user_interview_photo_link where id='{link}';")
    result = sql(f"set role service_role;select public.commit_lifetime_memoir_lane_page('{lane}','{page['token']}',{page['page_number']},{literal(proposed)},'{page['page_digest']}');", check=False)
    assert result.returncode != 0 and 'stale progressive batch' in result.stderr
    assert sql('select count(*) from public.user_lifetime_memoir_section;').stdout.strip() == '0'


def test_same_asset_in_another_exact_evidence_span_remains_unchanged(sql):
    identity, source, lane, first = seeded_composer(sql)
    service(sql, 'yield_lifetime_memoir_lane', f"'{lane}','{first['token']}'")
    first_link = add_photo_link(sql, identity, source, first)
    second_link = add_photo_link(sql, identity, source, first)
    asset = sql(f"select photo_id from public.user_interview_photo_link where id='{first_link}';").stdout.strip()
    quotes = [(first_link, 'I grew up', 'photo-first'), (second_link, 'Chengde.', 'photo-second')]
    for link, quote, _ in quotes:
        sql(f"update public.user_interview_photo_link set photo_id={literal(asset)},quote={literal(quote)} where id='{link}';")
    page = service(sql, 'claim_memoir_lane', f"'{lane}',900")
    result = section_result(page)
    prose = result['sections'][0]
    prose.update(id='prose', chapter_id='prose')
    prose['block']['id'] = 'prose'
    for _, quote, key in quotes:
        photo = deepcopy(prose)
        start = source['text'].index(quote)
        refs = [dict(source_id=source['id'], version=1, char_start=start, char_end=start+len(quote))]
        photo.update(id=key, chapter_id=key, source_refs=refs, content='')
        photo['block'].update(id=key, type='photo', text='', asset_id=asset, asset_version='1', source_refs=refs)
        result['sections'].append(photo)
    service(sql, 'commit_lifetime_memoir_lane_page', f"'{lane}','{page['token']}',0,{literal(result)}")
    service(sql, 'complete_lifetime_memoir_lane', f"'{lane}','{page['token']}'")
    sibling = sql("select row_to_json(s)::text from public.user_lifetime_memoir_section s where partition_key like '%:photo-second';").stdout
    assert asset in sibling
    sql(f"delete from public.user_interview_photo_link where id='{first_link}';")
    assert sql("select count(*) from public.user_lifetime_memoir_section where partition_key like '%:photo-first';").stdout.strip() == '0'
    assert sql("select row_to_json(s)::text from public.user_lifetime_memoir_section s where partition_key like '%:photo-second';").stdout == sibling


@pytest.mark.parametrize('retired_link_writing_id', [False, True])
@pytest.mark.parametrize('status,provenance', [
    ('unlinked', 'narrator_metadata'), ('invalidated', 'narrator_metadata'),
    ('confirmed', 'visual_derived'), ('confirmed', 'narrator'),
])
def test_link_outside_canonical_photo_basis_preserves_current_writing(sql, status, provenance, retired_link_writing_id):
    identity, source, lane, first = seeded_composer(sql)
    service(sql, 'yield_lifetime_memoir_lane', f"'{lane}','{first['token']}'")
    inactive = add_photo_link(sql, identity, source, first)
    active = add_photo_link(sql, identity, source, first)
    asset = sql(f"select photo_id from public.user_interview_photo_link where id='{inactive}';").stdout.strip()
    sql(f"update public.user_interview_photo_link set quote='I grew up',status='{status}',provenance='{provenance}' where id='{inactive}';")
    sql(f"update public.user_interview_photo_link set photo_id={literal(asset)} where id='{active}';")
    page = service(sql, 'claim_memoir_lane', f"'{lane}',900")
    result = section_result(page)
    photo = result['sections'][0]
    key = inactive if retired_link_writing_id else 'current-photo'
    photo.update(id=key, chapter_id=key, content='')
    photo['block'].update(id=key, type='photo', text='', asset_id=asset, asset_version='1')
    service(sql, 'commit_lifetime_memoir_lane_page', f"'{lane}','{page['token']}',0,{literal(result)}")
    service(sql, 'complete_lifetime_memoir_lane', f"'{lane}','{page['token']}'")
    before = sql('select row_to_json(s)::text from public.user_lifetime_memoir_section s;').stdout
    assert asset in before
    sql(f"delete from public.user_interview_photo_link where id='{inactive}';")
    assert sql('select row_to_json(s)::text from public.user_lifetime_memoir_section s;').stdout == before
