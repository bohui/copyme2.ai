"""Contextual workspace actions on the production frontend with controlled APIs."""
import json
import os
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest
from playwright.sync_api import expect, sync_playwright
from browser_supabase_fixture import install_supabase_fixture

pytestmark = pytest.mark.skipif(not os.getenv('MEMOIR_BROWSER_URL'), reason='Requires isolated frontend')


@pytest.fixture(params=[('en-AU',1440,1000),('zh-CN',390,844)], ids=['english-desktop','chinese-phone'])
def workspace_page(request):
    locale,width,height = request.param
    base = os.environ['MEMOIR_BROWSER_URL']
    copy = json.loads((Path(__file__).resolve().parents[1]/f'apps/web/messages/{locale}.json').read_text())['Memoir']['workspace']
    event = dict(id='garden-event',revision=3,kind='event',title='The little garden',status='active',
        life_stage='childhood',temporal={'expression':'1965','precision':'year','year_start':1965},source_refs=[])
    record = dict(id='garden-partition',event_id=event['id'],preview={'title':'The garden','text':'My original garden story.'},
        proposed_preview=None,proposal_digest=None)
    draft = dict(snapshot_id=str(uuid4()),root_digest='a'*64,locale=locale,status='ready',updating=False,
        preview=record['preview'],first_record=record,page_complete=True,retrieval_complete=True,
        snapshot_state='completed',coverage_round=5)
    control = {'fail_once':False,'payment_required':False}
    calls,errors = [],[]
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        context = browser.new_context(viewport={'width':width,'height':height},reduced_motion='reduce')
        context.add_cookies([dict(name='copyme2_ui_locale',value=locale,url=base),dict(name='copyme2_ui_locale_source',value='fixed',url=base)])
        context.route('https://**',lambda route:route.abort())
        install_supabase_fixture(context,"""if (location.protocol==='http:' || location.protocol==='https:') {
          const session=()=>({access_token:'fixture-owner',user:{id:'owner',is_anonymous:false}});
          window.supabase={createClient:()=>({auth:{getSession:async()=>({data:{session:session()}}),getUser:async()=>({data:{user:session().user}}),onAuthStateChange:()=>({})}})};
        }""")
        context.add_init_script("""if (location.protocol==='http:' || location.protocol==='https:') {
          localStorage.setItem('memory-spark-project:owner',JSON.stringify({projectId:'workspace',updatedAt:1}));
          const key='memory-spark-chat-history:owner:workspace';
          if(sessionStorage.getItem(key)===null)sessionStorage.setItem(key,JSON.stringify([{id:'opening',role:'assistant',text:'A saved conversation.'}]));
        }""")
        def api(route):
            path = route.request.url.split('/api/v1/memoir')[-1].split('?')[0]
            body = route.request.post_data_json if route.request.post_data else None
            calls.append((path,route.request.method,deepcopy(body)))
            data = {}
            if path=='/agent/config':
                data=dict(auth_mode='supabase',supabase_url='https://auth.test',supabase_publishable_key='public',show_thinking_steps=False)
            elif path in ['/agent/profile','/user/profile']:
                data=dict(name='Fixture',preferred_language=locale)
            elif path.startswith('/projects/') and len(path.split('/'))==3:
                data=dict(id=path.split('/')[-1],mode='self',profile=dict(name='Fixture',preferred_language=locale),revision=1,workspace_unlocked=True)
            elif path.endswith('/journey'):
                data=dict(active_session=None)
            elif path=='/story/state':
                data=dict(family_features_enabled=True,payment_features=['family_tree','timeline'],recall_status=dict(rounds_completed=20,free_rounds=20,paid=True,payment_required=control['payment_required']))
            elif path=='/agent/family-context':
                data=dict(family_features_enabled=True,family_context=dict(people=[],relationships=[],events=[]))
            elif path=='/story/events':
                data=dict(events=[deepcopy(event)],complete=True,next_cursor=None)
            elif path=='/story/private-draft':
                data=deepcopy(draft)
            elif path=='/story/private-draft/section':
                data=deepcopy(record)
            elif path=='/story/private-draft/rework':
                record.update(proposed_preview={'title':'The garden revised','text':'The revised garden story.'},proposal_digest='b'*64)
                draft.update(snapshot_id=str(uuid4()),root_digest='c'*64,first_record=deepcopy(record),proposed_preview=record['proposed_preview'])
                if control['fail_once']:
                    control['fail_once']=False
                    route.fulfill(status=503,json={'detail':'Lost acknowledgement'});return
                data=dict(request_id=body['request_id'],status='pending')
            elif path=='/story/private-draft/proposal':
                if body['accept']:
                    record['preview']=record['proposed_preview']
                    draft['preview']=record['preview']
                record.update(proposed_preview=None,proposal_digest=None)
                draft.update(first_record=deepcopy(record),proposed_preview=None)
                data=deepcopy(draft)
            elif path=='/agent/turn':
                data=dict(reply='Tell me a little more.',conversation_saved=True,recall_status=dict(rounds_completed=21,free_rounds=20,paid=True,payment_required=False))
            elif path=='/user/conversations':
                data=dict(items=[])
            elif path.endswith('/history'):
                data=dict(project_id=path.split('/')[-2],policy_epoch='1',items=[],next_cursor=None)
            elif path.endswith('/memory-sessions'):
                route.fulfill(status=403,json={});return
            elif path.startswith('/projects/'):
                data=dict(items=[],next_cursor=None)
            route.fulfill(json=data)
        context.route('**/api/v1/memoir/**',api)
        context.on('page',lambda page:page.on('pageerror',lambda error:errors.append(error.stack)))
        page = context.new_page()
        page.goto(base+'/memoir/interview/workspace',wait_until='networkidle')
        expect(page.locator('[data-add-workspace-memory]')).to_be_visible(timeout=30000)
        yield page,calls,copy,record,draft,control
        assert not errors,errors
        assert not any(path.endswith('/conversation-phase') for path,_,_ in calls)
        browser.close()


def test_stage_action_preserves_unsent_words_and_sends_only_scoped_context(workspace_page):
    page,calls,copy,*_ = workspace_page
    expect(page.locator('[data-phase-action]')).to_have_count(0)
    page.locator('#chat-input').fill('My unsent memory.')
    page.locator('[data-life-stage-tab=later_life]').click()
    page.locator('[data-add-workspace-memory]').click()
    expect(page.locator('#chat-input')).to_have_value('My unsent memory.')
    expect(page.locator('#chat-input')).to_be_focused()
    assert not any(path=='/agent/turn' for path,_,_ in calls)
    page.locator('#chat-form button[type=submit]').click()
    expect(page.locator('#chat-form button[type=submit]')).to_be_enabled()
    body=next(body for path,_,body in calls if path=='/agent/turn')
    assert body['conversation_text']=='My unsent memory.'
    assert body['workspace_focus']=={'kind':'add_memory','life_stage':'later_life'}
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')


def test_event_action_continues_exact_memory_and_can_finish_without_changing_mode(workspace_page):
    page,calls,copy,*_ = workspace_page
    page.locator('[data-workspace-tab=timeline]').click()
    page.locator('[data-explore-workspace-memory=garden-event]').click()
    expect(page.locator('.workspace-memory-focus')).to_contain_text('The little garden')
    page.locator('#chat-input').fill('There were roses.')
    page.locator('#chat-form button[type=submit]').click()
    expect(page.locator('#chat-form button[type=submit]')).to_be_enabled()
    body=next(body for path,_,body in calls if path=='/agent/turn')
    assert body['workspace_focus']=={'kind':'explore_memory','event_id':'garden-event','event_revision':3}
    page.locator('#chat-input').fill('We watered them every morning.')
    page.locator('#chat-form button[type=submit]').click()
    expect(page.locator('#chat-form button[type=submit]')).to_be_enabled()
    assert [body for path,_,body in calls if path=='/agent/turn'][-1]['workspace_focus'] is None
    page.locator('[data-finish-workspace-memory]').click()
    expect(page.locator('.workspace-memory-focus')).to_have_count(0)


def test_focus_is_a_visit_task_and_does_not_survive_reload(workspace_page):
    page,*_ = workspace_page
    page.locator('[data-add-workspace-memory]').click()
    expect(page.locator('.workspace-memory-focus')).to_be_visible()
    page.reload(wait_until='networkidle')
    expect(page.locator('.workspace-memory-focus')).to_have_count(0)
    expect(page.locator('[data-phase-action]')).to_have_count(0)


def test_section_rework_calls_composer_and_reviews_replacement_before_acceptance(workspace_page):
    page,calls,copy,record,draft,_ = workspace_page
    page.locator('.saved-draft-sections summary').click()
    page.locator('[data-rework-section=garden-partition]').click()
    page.locator('#section-rework-instruction').fill('Make this section shorter.')
    if evidence := os.getenv('MEMOIR_BROWSER_EVIDENCE_DIR'):
        directory=Path(evidence);directory.mkdir(parents=True,exist_ok=True)
        page.screenshot(path=str(directory/f'rework-{page.viewport_size["width"]}.png'),full_page=True)
    page.locator('#section-rework-form button[type=submit]').click()
    expect(page.get_by_text(copy['reworkReady'],exact=True)).to_be_visible()
    assert next(body for path,_,body in calls if path=='/story/private-draft/rework')['partition_id']=='garden-partition'
    assert not any(path=='/agent/turn' for path,_,_ in calls)
    expect(page.locator('.private-draft-section')).to_contain_text('My original garden story.')
    page.locator('details').filter(has=page.locator('[data-proposal-accept=true]')).locator('summary').click()
    page.locator('[data-proposal-accept=true]').click()
    expect(page.locator('.private-draft-section')).to_contain_text('The revised garden story.')
    sent=next(body for path,_,body in calls if path=='/story/private-draft/proposal')
    assert sent['snapshot_id']==draft['snapshot_id'] and sent['expected_proposal_digest']=='b'*64


def test_lost_acknowledgement_retries_the_exact_revision_request(workspace_page):
    page,calls,copy,_,_,control = workspace_page
    control['fail_once']=True
    page.locator('.saved-draft-sections summary').click()
    page.locator('[data-rework-section=garden-partition]').click()
    page.locator('#section-rework-instruction').fill('Keep the wording simple.')
    page.locator('#section-rework-form button[type=submit]').click()
    expect(page.get_by_text(copy['reworkError'],exact=True)).to_be_visible()
    page.get_by_role('button',name=copy['retrySectionRework'],exact=True).click()
    expect(page.get_by_text(copy['reworkReady'],exact=True)).to_be_visible()
    attempts=[body for path,_,body in calls if path=='/story/private-draft/rework']
    assert len(attempts)==2 and attempts[0]==attempts[1]
