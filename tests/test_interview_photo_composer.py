"""Canonical photo significance stays derived and source/version scoped."""
from copy import deepcopy
import pytest
from apps.api.canonical_composer import composer_request


def job():
    text='I remember visiting Lizheng Gate; I recognise that gate in the photo.'
    source={'id':'source','project_id':'project','kind':'narrator_chat','author_role':'storyteller','text':text,'status':'active','version':1,'sequence':1}
    association={'id':'link','event_id':'visit','photo_id':'reference:gate','source_id':'source','source_version':1,
        'quote':text,'description':'The narrator identifies Lizheng Gate.','provenance':'narrator_metadata','status':'confirmed'}
    event={'id':'visit','status':'active','revision':2,'life_stage':'childhood','title':'Visits to Lizheng Gate',
        'source_refs':[{'source_id':'source','version':1,'quote':text}], 'photo_associations':[association]}
    return {'user_id':'owner','project_id':'project','sources':[source],'events':[event],'locale':'en-AU',
        'source_manifest':[{'id':'source','version':1}],'event_manifest':[{'id':'visit','revision':2}],
        'base_revision':0,'policy_epoch':1,'coverage_round':5,'previous':None}


def test_authorized_photo_significance_reaches_composer_without_becoming_testimony_or_pixels():
    before=job();request=composer_request(before)
    photo=request['context']['photo_associations'][0]
    assert photo['event_id']=='visit' and photo['source_refs']==request['events'][0]['source_refs']
    assert photo['description']=='The narrator identifies Lizheng Gate.'
    assert photo['derived'] is True and photo['provenance']=='narrator_metadata'
    assert request['assets']==[] and len(request['sources'])==1
    assert request['sources'][0]['text']==before['sources'][0]['text']


@pytest.mark.parametrize('change',['withdrawn','wrong_version','unknown_event','bad_quote','pending'])
def test_stale_or_unsupported_photo_context_never_enters_memoir_projection(change):
    value=job();a=value['events'][0]['photo_associations'][0]
    if change=='withdrawn':value['sources'][0]['status']='withdrawn'
    if change=='wrong_version':a['source_version']=2
    if change=='unknown_event':a['event_id']='other'
    if change=='bad_quote':a['quote']='A fabricated childhood scene'
    if change=='pending':a['status']='pending'
    assert composer_request(value)['context']['photo_associations']==[]


def test_photo_association_revision_changes_composer_snapshot_fingerprint():
    value=job();before=composer_request(value)
    value['events'][0]['photo_associations'][0]['description']='Updated narrator attribution.'
    after=composer_request(value)
    assert before['snapshot']['id']!=after['snapshot']['id']


@pytest.mark.parametrize('change',['unlink','description','unrelated_change'])
def test_photo_dependency_changes_force_recomposition_and_reject_old_section_reuse(monkeypatch,change):
    import asyncio
    import os
    from types import SimpleNamespace
    from apps.api import canonical_composer as composer
    value=job();original=composer.composer_request(value)
    config=composer.fingerprint({'locale':value['locale'],'skill':'shared-composer-4',
        'model':os.getenv('MEMORY_SPARK_MEMOIR_COMPOSER_MODEL',os.getenv('MEMORY_SPARK_LLM_MODEL','gpt-5.6-luna-pooled')),'policy':original['policy']})
    refs=original['events'][0]['source_refs']
    chapter={'id':'chapter','title':'Gate','subtitle':'','event_ids':['visit'],'period_ids':['stage_childhood'],
             'source_refs':refs,'blocks':[{'id':'block','text':'Old photo claim','source_refs':refs,'event_ids':['visit']}]}
    manifest={'visit':composer.fingerprint(original['context']['photo_associations'])}
    value.update(base_revision=1,lane_id='lane',token='token',policy_epoch=2)
    value['previous']={'manuscript':{'kind':'sample_chapter','chapters':[chapter]},'draft':{'input_fingerprint':original['request_id']},
        'event_manifest':deepcopy(value['event_manifest']),'content_config':config,'photo_association_manifest':manifest,
        'preview':{'text':'Old photo claim'},'sections':[{'chapter_id':'chapter','event_ids':['visit'],'source_refs':refs,
             'block':chapter['blocks'][0],'content':'Old photo claim'}]}
    if change=='description':value['events'][0]['photo_associations'][0]['description']='Corrected narrator identification.'
    else:value['events'][0]['photo_associations']=[]
    if change=='unrelated_change':
        other=deepcopy(value['events'][0]);other.update(id='other',revision=2,photo_associations=[])
        value['events'].append(other);value['event_manifest'].append({'id':'other','revision':2})
    seen=[]
    class Broker:
        async def rpc(self,*a,**kwargs):return None
    async def prepare(runtime,storage,project,locale,phase,packet):
        return {'event_id':packet['partition']['id'],'context':'Supported visit','source_refs':packet['partition']['source_refs']}
    async def compose(request,*a,**kwargs):
        seen.append(request)
        assert 'visit' in request['context']['dirty_event_ids']
        assert request['context']['preserved_sections']==[]
        assert 'chapter' in request['context']['projection_invalidated_chapter_ids']
        return {'status':'ready','manuscript':{'kind':'sample_chapter','chapters':[]}}
    monkeypatch.setattr(composer,'composer_call',prepare);monkeypatch.setattr(composer,'compose_candidate',compose)
    worker=SimpleNamespace(worker_url='http://controlled.invalid',worker_secret='synthetic',worker_transport=None,broker=Broker())
    result=asyncio.run(composer.compose_shared_snapshot(value,worker))
    assert seen and not result.get('unchanged')
    assert result['photo_association_manifest'] != manifest


def test_unchanged_photo_manifest_reuses_reviewed_bundle_without_model_calls():
    import asyncio
    import os
    from types import SimpleNamespace
    from apps.api.canonical_composer import compose_shared_snapshot, fingerprint
    value=job();original=composer_request(value)
    previous={'manuscript':{'kind':'sample_chapter','chapters':[]},'draft':{'input_fingerprint':original['request_id']},
        'event_manifest':deepcopy(value['event_manifest']),
        'photo_association_manifest':original['context']['photo_association_manifest'],
        'content_config':fingerprint({'locale':value['locale'],'skill':'shared-composer-4',
            'model':os.getenv('MEMORY_SPARK_MEMOIR_COMPOSER_MODEL',os.getenv('MEMORY_SPARK_LLM_MODEL','gpt-5.6-luna-pooled')),
            'policy':original['policy']}),'sections':[]}
    value.update(previous=previous,base_revision=1)
    result=asyncio.run(compose_shared_snapshot(value,SimpleNamespace()))
    assert result=={**previous,'unchanged':True}
