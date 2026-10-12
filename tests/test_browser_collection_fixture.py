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


def test_failure_state_is_frozen_before_screenshot_processes_late_startup(tmp_path):
    page=Page();state=install_collection_startup(page,'en-AU')
    original_screenshot=page.screenshot
    def late_screenshot(**options):
        state['created']=1
        state['consents'].extend(['recording','storyteller_assent'])
        state['request_details'].append({'url':'late request'})
        page.url='http://127.0.0.1:3010/memoir/interview/'+COLLECTION_PROJECT
        original_screenshot(**options)
    page.screenshot=late_screenshot
    with pytest.raises(AssertionError,match='startup is incomplete'):
        with collection_diagnostics(page,state,tmp_path,'immutable'):
            assert state['created']==1,'startup is incomplete'
    saved=json.loads((tmp_path/'immutable-failure.json').read_text())
    assert state['created']==1 and len(state['consents'])==2
    assert saved['startup']['created']==0 and saved['startup']['consents']==[]
    assert saved['startup']['request_details']==[]
    assert saved['page_url']=='http://127.0.0.1:3010/memoir'


@pytest.mark.parametrize('missing_consent',[False,True])
def test_startup_barriers_precede_click_and_wait_for_delayed_completions(monkeypatch,missing_consent):
    import browser_collection_review as fixture
    state=None
    class DelayedPage(Page):
        def __init__(self):
            super().__init__();self.waits=[];self.clicked=False;self.completed=False;self.visible_checked=False
        def expect_request_finished(self,predicate,*,timeout):
            assert timeout==250 and not self.clicked
            routes=[Route('/projects','POST',{'mode':'self'}),
                Route('/projects/'+COLLECTION_PROJECT+'/consents','POST',{'purpose':'recording','granted':True,'locale':'en-AU'}),
                Route('/projects/'+COLLECTION_PROJECT+'/consents','POST',{'purpose':'storyteller_assent','granted':True,'locale':'en-AU'}),
                Route('/projects/'+COLLECTION_PROJECT+'/journey')]
            matches=[route for route in routes if predicate(route.request)]
            assert len(matches)==1
            assert not predicate(Route('/projects/foreign/consents','POST',{'purpose':'recording'}).request)
            assert not predicate(Route('/projects','GET').request)
            selected=matches[0]
            selected.request.response=lambda:SimpleNamespace(status=selected.response['status'])
            page=self
            class Pending:
                value=selected.request
                def __enter__(self):page.waits.append(selected);return self
                def __exit__(self,exc_type,exc,trace):
                    assert page.clicked
                    if not page.completed:
                        # Route callbacks run only after the click and when the
                        # synchronization barrier yields to the browser loop.
                        for route in page.waits:
                            if missing_consent and route.request.post_data_json and route.request.post_data_json.get('purpose')=='storyteller_assent':continue
                            page.handler(route)
                        page.completed=True
                        page.url='http://127.0.0.1:3010/memoir/interview/'+COLLECTION_PROJECT
                    if missing_consent:raise TimeoutError('consent completion deadline')
            return Pending()
        def get_by_role(self,role,*,name):
            assert role=='button' and name=='Begin my story'
            def click(*,timeout):
                assert timeout==250 and len(self.waits)==4 and state['created']==0
                self.clicked=True
            return SimpleNamespace(click=click)
        def locator(self,selector):
            assert selector=='[data-profile-trigger]'
            return self
    page=DelayedPage();state=install_collection_startup(page,'en-AU')
    class Assertions:
        def to_have_url(self,pattern,*,timeout):
            assert timeout==250 and pattern.search(page.url)
        def to_be_visible(self,*,timeout):
            assert timeout==250 and state['created']==1 and len(state['consents'])==2
            page.visible_checked=True
    monkeypatch.setattr(fixture,'expect',lambda target:Assertions())
    if missing_consent:
        with pytest.raises(TimeoutError,match='completion deadline'):
            fixture.start_collection_story(page,'en-AU',timeout=250)
        assert not page.visible_checked
    else:
        fixture.start_collection_story(page,'en-AU',timeout=250)
        assert page.visible_checked and state['created']==1 and set(state['consents'])=={'recording','storyteller_assent'}
