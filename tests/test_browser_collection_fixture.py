"""The collection browser setup models exact startup APIs and rejects surprises."""
from types import SimpleNamespace
import json
from pathlib import Path

import pytest

from browser_collection_review import install_collection_startup, COLLECTION_PROJECT, collection_diagnostics


class Page:
    url = 'http://127.0.0.1:3010/memoir'
    frames = [SimpleNamespace(name='', url=url)]

    def __init__(self):
        self.events = {}

    def on(self, name, callback):
        self.events[name] = callback

    def screenshot(self, *, path, full_page):
        assert full_page
        Path(path).write_bytes(b'synthetic screenshot')

    def route(self, pattern, handler):
        assert pattern == '**/api/v1/memoir/**'
        self.handler = handler


class Route:
    def __init__(self, path, method='GET', payload=None):
        self.request = SimpleNamespace(url='http://127.0.0.1:3010/api/v1/memoir'+path,
            method=method, post_data_json=payload)
        self.response = None
        self.aborted = False

    def fulfill(self, **response):
        self.response = response

    def abort(self):
        self.aborted = True


@pytest.mark.parametrize('locale',['en-AU','zh-CN'])
@pytest.mark.parametrize('explicit_language',[False,True])
def test_startup_creates_and_hydrates_exact_project_with_consent(locale,explicit_language):
    page=Page();state=install_collection_startup(page,locale)
    def call(path,method='GET',payload=None):
        route=Route(path,method,payload);page.handler(route)
        assert not route.aborted
        return route.response
    created=call('/projects','POST',{'mode':'self',**({'language':locale} if explicit_language else {})})
    assert created['status']==201 and created['json']['id']==COLLECTION_PROJECT
    assert created['json']['profile']['preferred_language']==locale
    assert call('/projects/'+COLLECTION_PROJECT)['json']['id']==COLLECTION_PROJECT
    for purpose in ['recording','storyteller_assent']:
        response=call('/projects/'+COLLECTION_PROJECT+'/consents','POST',{'purpose':purpose,'granted':True,'locale':locale})
        assert response['json']['purpose']==purpose and response['json']['granted'] is True
    assert call('/projects/'+COLLECTION_PROJECT+'/journey')['json']['active_session'] is None
    assert call('/story/state')['json']['recall_status']['payment_required'] is False
    assert call('/story/readiness?project_id='+COLLECTION_PROJECT)['json']['stages']=={}
    assert call('/story/private-draft?project_id='+COLLECTION_PROJECT+'&language='+locale)['json']['preview'] is None
    assert state['created']==1 and set(state['consents'])=={'recording','storyteller_assent'}
    assert state['unexpected']==[]


@pytest.mark.parametrize('path,method',[
    ('/projects/foreign','GET'),('/projects','GET'),('/agent/turn','POST'),
    ('/user/profile','POST'),('/story/readiness?project_id=foreign','GET'),
])
def test_unknown_or_wrong_method_api_never_gets_catchall_success(path,method):
    page=Page();state=install_collection_startup(page,'en-AU');route=Route(path,method,{})
    page.handler(route)
    assert route.aborted and route.response is None
    assert state['unexpected']==[(method,path)]


def test_failure_evidence_preserves_url_frame_stack_and_unmatched_request(tmp_path):
    page=Page();state=install_collection_startup(page,'en-AU')
    request=Route('/agent/turn','POST',{}).request
    request.frame=page.frames[0];request.resource_type='fetch';request.failure='net::ERR_FAILED'
    page.events['request'](request)
    page.events['requestfailed'](request)
    error=RuntimeError('Synthetic browser exception');error.stack='Error: synthetic\n at client.js:1'
    page.events['pageerror'](error)
    page.handler(Route('/agent/turn','POST',{}))
    with pytest.raises(RuntimeError,match='original failure'):
        with collection_diagnostics(page,state,tmp_path,'review-en-AU'):
            raise RuntimeError('original failure')
    saved=json.loads((tmp_path/'review-en-AU-failure.json').read_text())
    assert saved['page_url']==page.url and saved['frames'][0]['url']==page.url
    assert 'original failure' in saved['error_stack']
    assert saved['startup']['browser_errors'][0]['stack']==error.stack
    assert saved['startup']['unexpected']==[['POST','/agent/turn']]
    assert saved['startup']['request_details'][0]['frame_url']==page.url
    assert saved['startup']['failed_requests'][0]['failure']=='net::ERR_FAILED'
