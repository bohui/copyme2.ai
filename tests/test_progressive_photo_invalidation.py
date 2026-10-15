"""Validated image-bundle storage, not live image admission or photo exposure.

The canonical producer currently declares assets=[]. These tests explicitly
supply a synthetic eligible asset catalog to the real composer validator and
renderer, then exercise the actual PostgreSQL commit/read/invalidation path.
They do not establish an upload-to-composer asset mapping in production.
"""
import asyncio
from copy import deepcopy
import hashlib
from uuid import uuid4

import pytest

from apps.api.canonical_composer import composer_request
from apps.api.memoir_preview import skill_operation
from apps.api.progressive_composer import batch_job
from test_canonical_composer_provenance import controlled_draft
from test_lifetime_composer_capacity import seeded_composer, service
from test_lifetime_memory_postgres import sql, event_database, private_database, attachment_database, database
from test_lifetime_review_repairs import add_photo_link
from test_shared_memory_events_postgres import literal, rpc
from test_agent_commit_postgres import OTHER


def catalog_link(sql, identity, source, first):
    """Bind a declared synthetic catalog ID, without guessing an upload mapping."""
    link = add_photo_link(sql, identity, source, first)
    prior = sql(f"select photo_id from public.user_interview_photo_link where id='{link}';").stdout.strip()
    asset = 'fixture_' + uuid4().hex
    sql(f"update public.user_interview_photo_link set photo_id={literal(asset)} where id='{link}';")
    sql(f"update public.user_interview_turn set photo_context=(select jsonb_agg(case when p->>'photo_id'={literal(prior)} then jsonb_set(p,'{{photo_id}}',to_jsonb({literal(asset)}::text)) else p end) from jsonb_array_elements(photo_context) p) where project_id={literal(identity['project_id'])} and photo_context @> jsonb_build_array(jsonb_build_object('photo_id',{literal(prior)}));")
    return link, asset


def block(key, source, *, asset=None, quote=None):
    text = source['text'] if quote is None else quote
    start = source['text'].index(text)
    return dict(id=key, type='image' if asset else 'paragraph', text='' if asset else text,
        asset_id=asset, asset_version='1' if asset else None, caption='',
        alt='Narrator-selected image.' if asset else '', credit='', uncertainty=[],
        source_refs=[dict(source_id=source['id'],version='1',char_start=start,char_end=start+len(text))])


def validated_result(page, blocks):
    request = composer_request(batch_job(page))
    assert request['assets'] == []  # Current product does not admit image assets.
    refs = [ref for item in blocks for ref in item['source_refs']]
    request['assets'] = [dict(id=asset,version='1',project_id=page['project_id'],origin='user_upload',
        resolver_ref=f"asset://synthetic/{asset}/1",content_sha256=hashlib.sha256(asset.encode()).hexdigest(),
        status='active',allowed=True,capabilities=dict(web=True,download=True,print=False),
        metadata_source_refs=refs) for asset in sorted({item['asset_id'] for item in blocks if item['asset_id']})]
    plan = asyncio.run(skill_operation('plan',request))
    assert plan['ready'], plan
    draft = controlled_draft(dict(request=request,plan=plan),'I grew up in Chengde.','Childhood')
    assert draft['kind'] == 'sample_chapter'
    chapter = draft['chapters'][0]
    chapter['blocks'] = deepcopy(blocks)
    chapter['source_refs'] = refs
    validation = asyncio.run(skill_operation('validate',request,draft))
    assert validation['ok'], validation
    rendered = asyncio.run(skill_operation('render',request,draft))
    if request['assets']:
        assert '<figure data-asset-ref=' in rendered['memoir.html']
    # Use the same block and heading flattening as compose_shared_snapshot.
    event_ids = chapter['event_ids']
    sections = [dict(id=chapter['id']+'__'+item['id'],chapter_id=chapter['id'],event_ids=event_ids,
        source_refs=item['source_refs'],content=item['text'],block=deepcopy(item)) for item in blocks]
    sections.append(dict(id=chapter['id']+'__heading',chapter_id=chapter['id'],event_ids=event_ids,
        source_refs=chapter['source_refs'],content=chapter['title'],heading=dict(title=chapter['title'],subtitle='')))
    return dict(_controlled_model_fixture=True,status='ready',validation=validation,
        review=dict(ready_for_user_review=True,publication_approved=False,findings=[]),
        manuscript=dict(kind='sample_chapter'),sections=sections,preview=dict(text=source_text(blocks)),
        photo_association_manifest=request['context']['photo_association_manifest'])


def source_text(blocks):
    return ' '.join(item['text'] for item in blocks if item['text'])


def commit(sql, lane, page, blocks):
    result = validated_result(page, blocks)
    service(sql,'commit_lifetime_memoir_lane_page',f"'{lane}','{page['token']}',{page['page_number']},{literal(result)}")
    return service(sql,'complete_lifetime_memoir_lane',f"'{lane}','{page['token']}'")


def selected(sql, key):
    return sql(f"select row_to_json(s)::text from public.user_lifetime_memoir_section s where partition_key like '%:home-chapter__{key}' order by snapshot_id;").stdout


def refresh_event(sql, identity, source, lane, first):
    new = rpc(sql,'accept_user_narrator_source',f"{literal(identity['project_id'])},'{uuid4()}','My parents often took me there.'")
    ref = dict(source_id=new['id'],version=1,quote=new['text'],char_start=0,char_end=len(new['text']))
    event = dict(existing_id=first['partition']['id'],expected_revision=1,kind='event',title='Childhood',source_refs=[ref])
    rpc(sql,'apply_user_memory_events',f"{literal(identity['project_id'])},{literal([{'id':new['id'],'version':1}])},{literal([event])}")
    sql(f"update public.user_memoir_lane set pending=true where id='{lane}';")
    return service(sql,'claim_memoir_lane',f"'{lane}',900")


@pytest.mark.parametrize('action', ['update', 'delete'])
@pytest.mark.parametrize('location', ['bundle', 'proposal'])
def test_progressive_photo_change_purges_exact_asset_and_preserves_other_writing(sql, action, location):
    identity, source, lane, first = seeded_composer(sql)
    service(sql,'yield_lifetime_memoir_lane',f"'{lane}','{first['token']}'")
    changed, asset = catalog_link(sql,identity,source,first)
    sibling, sibling_asset = catalog_link(sql,identity,source,first)
    page = service(sql,'claim_memoir_lane',f"'{lane}',900")
    initial = [block('prose',source),block('photo-0',source,asset=asset if location=='bundle' else None),
               block('photo-1',source,asset=sibling_asset)]
    assert commit(sql,lane,page,initial)['status'] == 'saved'
    if location == 'proposal':
        sql('update public.user_lifetime_memoir_section set approved=true;')
        page = refresh_event(sql,identity,source,lane,first)
        assert commit(sql,lane,page,[block('prose',source),block('photo-0',source,asset=asset),
            block('photo-1',source,asset=sibling_asset),block('unreviewed',source)])['status'] == 'proposed'
        before = rpc(sql,'read_lifetime_private_draft_page',f"{literal(identity['project_id'])},'{page['snapshot_id']}'")
        original = next(item for item in before['records'] if item['id'].endswith('__photo-0'))
        assert original['preview']['text'] == source['text'] and original['proposal_digest']
        candidate = next(item for item in before['records'] if item['id'].endswith('__unreviewed'))
        assert candidate['preview'] is None and candidate['proposed_preview']['text'] == source['text']
        assert rpc(sql,'read_lifetime_private_draft_page',f"{literal(identity['project_id'])},'{page['snapshot_id']}'",owner=OTHER,check=False).returncode != 0
    else:
        sql('update public.user_lifetime_memoir_section set human_locked=true;')
    assert asset in selected(sql,'photo-0')
    unaffected = sql("select row_to_json(s)::text from public.user_lifetime_memoir_section s where partition_key not like '%:home-chapter__photo-0' order by snapshot_id,partition_key;").stdout
    assert sibling_asset in unaffected and source['text'] in unaffected
    rounds = sql('select count(*) from public.user_completed_round;').stdout
    before_noop = selected(sql,'photo-0')
    sql(f"update public.user_interview_photo_link set description=description where id='{changed}';")
    assert selected(sql,'photo-0') == before_noop
    if action == 'update':
        sql(f"update public.user_interview_photo_link set description='Corrected attribution' where id='{changed}';")
    else:
        sql(f"delete from public.user_interview_photo_link where id='{changed}';")
    assert asset not in selected(sql,'photo-0')
    assert sql("select row_to_json(s)::text from public.user_lifetime_memoir_section s where partition_key not like '%:home-chapter__photo-0' order by snapshot_id,partition_key;").stdout == unaffected
    assert sql('select count(*) from public.user_completed_round;').stdout == rounds
    if location == 'proposal':
        after = rpc(sql,'read_lifetime_private_draft_page',f"{literal(identity['project_id'])},'{page['snapshot_id']}'")
        restored = next(item for item in after['records'] if item['id'].endswith('__photo-0'))
        assert restored['preview']['text'] == original['preview']['text']
        assert restored['proposed_preview'] is None and restored['proposal_digest'] is None
        candidate_after = next(item for item in after['records'] if item['id'].endswith('__unreviewed'))
        assert candidate_after == candidate
        head = rpc(sql,'read_lifetime_private_draft_head',literal(identity['project_id']))
        assert head['preview']['text'] == source['text']


@pytest.mark.parametrize('action', ['update', 'delete'])
def test_photo_change_rejects_inflight_progressive_commit(sql, action):
    identity, source, lane, first = seeded_composer(sql)
    service(sql,'yield_lifetime_memoir_lane',f"'{lane}','{first['token']}'")
    link, asset = catalog_link(sql,identity,source,first)
    page = service(sql,'claim_memoir_lane',f"'{lane}',900")
    proposed = validated_result(page,[block('image',source,asset=asset)])
    for phase in ('prepare','draft','review'):
        sql(f"set role service_role;select public.record_lifetime_lane_output('{lane}','{page['token']}',{page['page_number']},'{phase}','{'a'*64}','{page['page_digest']}');")
    if action == 'update':
        sql(f"update public.user_interview_photo_link set description='Corrected attribution' where id='{link}';")
    else:
        sql(f"delete from public.user_interview_photo_link where id='{link}';")
    result = sql(f"set role service_role;select public.commit_lifetime_memoir_lane_page('{lane}','{page['token']}',{page['page_number']},{literal(proposed)},'{page['page_digest']}');",check=False)
    assert result.returncode != 0 and 'stale progressive batch' in result.stderr
    assert sql('select count(*) from public.user_lifetime_memoir_section;').stdout.strip() == '0'


def test_same_asset_in_another_exact_evidence_span_remains_unchanged(sql):
    identity, source, lane, first = seeded_composer(sql)
    service(sql,'yield_lifetime_memoir_lane',f"'{lane}','{first['token']}'")
    first_link, asset = catalog_link(sql,identity,source,first)
    second_link, _ = catalog_link(sql,identity,source,first)
    for link, quote in [(first_link,'I grew up'),(second_link,'Chengde.')]:
        sql(f"update public.user_interview_photo_link set photo_id={literal(asset)},quote={literal(quote)} where id='{link}';")
    page = service(sql,'claim_memoir_lane',f"'{lane}',900")
    commit(sql,lane,page,[block('prose',source),block('photo-first',source,asset=asset,quote='I grew up'),
        block('photo-second',source,asset=asset,quote='Chengde.')])
    sibling = selected(sql,'photo-second')
    assert asset in sibling
    sql(f"delete from public.user_interview_photo_link where id='{first_link}';")
    assert not selected(sql,'photo-first')
    assert selected(sql,'photo-second') == sibling


@pytest.mark.parametrize('retired_link_writing_id', [False, True])
@pytest.mark.parametrize('status,provenance', [('unlinked','narrator_metadata'),('invalidated','narrator_metadata'),
    ('confirmed','visual_derived'),('confirmed','narrator')])
def test_link_outside_canonical_photo_basis_preserves_current_writing(sql,status,provenance,retired_link_writing_id):
    identity, source, lane, first = seeded_composer(sql)
    service(sql,'yield_lifetime_memoir_lane',f"'{lane}','{first['token']}'")
    inactive, asset = catalog_link(sql,identity,source,first)
    active, _ = catalog_link(sql,identity,source,first)
    sql(f"update public.user_interview_photo_link set quote='I grew up',status='{status}',provenance='{provenance}' where id='{inactive}';")
    sql(f"update public.user_interview_photo_link set photo_id={literal(asset)} where id='{active}';")
    page = service(sql,'claim_memoir_lane',f"'{lane}',900")
    key = inactive if retired_link_writing_id else 'current-photo'
    commit(sql,lane,page,[block(key,source,asset=asset)])
    before = selected(sql,key)
    assert asset in before
    sql(f"delete from public.user_interview_photo_link where id='{inactive}';")
    assert selected(sql,key) == before


def test_current_canonical_request_cannot_admit_an_image_without_an_asset_catalog(sql):
    _, source, _, page = seeded_composer(sql)
    request = composer_request(batch_job(page))
    assert request['assets'] == []
    plan = asyncio.run(skill_operation('plan',request))
    draft = controlled_draft(dict(request=request,plan=plan),source['text'],'Childhood')
    draft['chapters'][0]['blocks'] = [block('image',source,asset='synthetic_unavailable_asset')]
    validation = asyncio.run(skill_operation('validate',request,draft))
    assert not validation['ok']
    assert any(item['code']=='INELIGIBLE_ASSET' for item in validation['errors'])
    assert not any(item['code']=='SCHEMA' for item in validation['errors'])
    invalid = deepcopy(draft)
    invalid['chapters'][0]['blocks'][0]['type'] = 'photo'
    rejected = asyncio.run(skill_operation('validate',request,invalid))
    assert not rejected['ok'] and any(item['code']=='SCHEMA' for item in rejected['errors'])
