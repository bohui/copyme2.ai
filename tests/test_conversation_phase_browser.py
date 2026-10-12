"""Conversation guidance on the shipped UI with synthetic API/Auth only."""
import json
import os
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright
from browser_supabase_fixture import install_supabase_fixture

pytestmark = pytest.mark.skipif(not os.getenv('MEMOIR_BROWSER_URL'), reason='Requires isolated frontend')


def phase(**overrides):
    return {**dict(schema_version=1, phase='comfort', selection='automatic', preferred_phase=None,
                   revision=0, reason='initial', source_turn_id=None), **overrides}


@pytest.fixture(params=[('en-AU', 1440, 1000), ('zh-CN', 390, 844)], ids=['english-desktop', 'chinese-phone'])
def phase_page(request):
    locale, width, height = request.param
    base = os.environ['MEMOIR_BROWSER_URL']
    copy = json.loads((Path(__file__).resolve().parents[1] / f'apps/web/messages/{locale}.json').read_text())['Memoir']['phase']
    states = {('owner', 'phases'): phase(), ('owner', 'other'): phase(phase='shape', selection='explicit', preferred_phase='shape', revision=3),
              ('other', 'phases'): phase(phase='explore', selection='explicit', preferred_phase='explore', revision=8)}
    calls, errors = [], []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.getenv('CHROMIUM_EXECUTABLE', '/usr/bin/chromium'), args=['--no-sandbox'])
        context = browser.new_context(viewport={'width':width, 'height':height}, reduced_motion='reduce')
        context.add_cookies([dict(name='copyme2_ui_locale', value=locale, url=base), dict(name='copyme2_ui_locale_source', value='fixed', url=base)])
        context.route('https://**', lambda route: route.abort())
        install_supabase_fixture(context, """if (location.protocol === 'http:' || location.protocol === 'https:') {
          const session=()=>({access_token:'fixture-'+(localStorage.getItem('fixture-owner')||'owner'),user:{id:localStorage.getItem('fixture-owner')||'owner',is_anonymous:true}});
          window.fixturePrincipal=id=>{localStorage.setItem('fixture-owner',id);window.fixtureAuth?.('SIGNED_IN',session())};
          window.supabase={createClient:()=>({auth:{getSession:async()=>({data:{session:session()}}),getUser:async()=>({data:{user:session().user}}),onAuthStateChange:fn=>{window.fixtureAuth=fn;return {}}}})};
        }""")
        context.add_init_script("""if (location.protocol === 'http:' || location.protocol === 'https:') {
          localStorage.setItem('memory-spark-project:owner',JSON.stringify({projectId:'phases',updatedAt:1}));
          const owner=localStorage.getItem('fixture-owner')||'owner';
          for(const project of ['phases','other']) {
            const key='memory-spark-chat-history:'+owner+':'+project;
            if(sessionStorage.getItem(key)===null)sessionStorage.setItem(key,JSON.stringify([{id:'saved-opening',role:'assistant',text:'A saved conversation.'}]));
          }
          const nativeFetch=window.fetch;window.sentTurns=[];
          window.fetch=(url,options)=>{
            if(String(url).endsWith('/agent/turn')) {
              sentTurns.push(JSON.parse(options.body));
              return Promise.resolve(new Response(new ReadableStream({start(controller){window.turnController=controller},cancel(){window.cancelledTurns=(window.cancelledTurns||0)+1}}),{headers:{'Content-Type':'application/x-ndjson'}}));
            }
            return nativeFetch(url,options);
          };
          window.turnEvent=(type,data)=>turnController.enqueue(new TextEncoder().encode(JSON.stringify({type,data})+'\\n'));
        }""")

        def api(route):
            path = route.request.url.split('/api/v1/memoir')[-1].split('?')[0]
            owner = route.request.headers.get('authorization', '').removeprefix('Bearer fixture-')
            body = route.request.post_data_json if route.request.post_data else None
            calls.append((path, route.request.method, owner, body))
            data = {}
            if path == '/agent/config':
                data = dict(auth_mode='supabase', supabase_url='https://auth.test', supabase_publishable_key='public')
            elif path in ['/agent/profile', '/user/profile']:
                data = dict(name='Fixture', preferred_language=locale)
            elif path.endswith('/conversation-phase'):
                project = path.split('/')[-2]
                value = states.setdefault((owner, project), phase())
                if route.request.method == 'PATCH':
                    if body['expected_revision'] != value['revision']:
                        route.fulfill(status=409, json={'detail':'Choice changed'}); return
                    action = body['action']
                    value['revision'] += 1
                    if action in ['comfort', 'explore', 'shape']:
                        value.update(phase=action, selection='explicit', preferred_phase=action)
                    elif action == 'automatic':
                        value.update(selection='automatic', preferred_phase=None)
                data = dict(conversation_phase=dict(value))
            elif path.startswith('/projects/') and len(path.split('/')) == 3:
                data = dict(id=path.split('/')[-1], mode='self', profile=dict(name='Fixture', preferred_language=locale), revision=1)
            elif path.endswith('/journey'):
                data = dict(active_session=None)
            elif path == '/story/state':
                data = dict(family_features_enabled=False, recall_status=dict(payment_required=False))
            elif path == '/user/conversations':
                data = dict(items=[])
            elif path.endswith('/history'):
                data = dict(project_id=path.split('/')[-2], policy_epoch='1', items=[], next_cursor=None)
            elif path.endswith('/memory-sessions'):
                route.fulfill(status=403, json={}); return
            route.fulfill(json=data)

        context.route('**/api/v1/memoir/**', api)
        context.on('page', lambda page: page.on('pageerror', lambda error: errors.append(error.stack)))
        page = context.new_page()
        page.goto(base + '/memoir/interview/phases', wait_until='networkidle')
        expect(page.locator('[data-phase-action=comfort]')).to_be_enabled(timeout=30000)
        yield page, states, calls, copy, context, base
        assert not errors, errors
        browser.close()


def click(page, action):
    button = page.locator(f'[data-phase-action={action}]')
    expect(button).to_be_enabled()
    button.click()
    expect(page.locator('[data-phase-action=comfort]')).to_be_enabled()


def test_controls_are_accessible_localized_and_never_submit_narration(phase_page):
    page, _, calls, copy, _, _ = phase_page
    expect(page.get_by_role('group', name=copy['choices'])).to_be_visible()
    expect(page.get_by_role('button', name=copy['comfort'], exact=True)).to_be_visible()
    page.locator('#chat-input').fill('A thought I have not sent yet.')
    previous = page.locator('#chat-history').inner_text()
    for action in ['comfort', 'explore', 'shape', 'automatic', 'skip']:
        click(page, action)
        if action != 'skip':
            expect(page.locator(f'[data-phase-action={action}]')).to_have_attribute('aria-pressed', 'true')
    expect(page.locator('[data-phase-action=pause]')).to_have_count(0)
    expect(page.locator('[data-phase-action=resume]')).to_have_count(0)
    expect(page.locator('[data-action=voice-input]')).to_be_visible()
    shape = page.get_by_role('button', name=copy['shape'], exact=True)
    shape.focus(); shape.press('Enter')
    expect(page.locator('[data-phase-action=shape]')).to_be_focused()
    expect(page.locator('#chat-input')).to_have_value('A thought I have not sent yet.')
    assert page.locator('#chat-history').inner_text() == previous
    assert page.evaluate('sentTurns.length') == 0
    assert not any(path in ['/story/rounds', '/agent/turn'] or path.endswith('/answers') for path, *_ in calls)
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    assert '%' not in page.locator('.conversation-phase').inner_text()
    assert page.locator('.conversation-phase [role=progressbar]').count() == 0


def test_explicit_choice_survives_reload_without_a_resume_step(phase_page):
    page, _, _, copy, _, _ = phase_page
    click(page, 'shape')
    page.reload(wait_until='networkidle')
    expect(page.locator('[data-phase-action=shape]')).to_have_attribute('aria-pressed', 'true')
    expect(page.locator('.phase-status')).to_have_text(copy['shapeStatus'])
    expect(page.locator('#chat-input')).to_be_enabled()
    expect(page.locator('[data-action=voice-input]')).to_be_visible()
    expect(page.locator('[data-phase-action=resume]')).to_have_count(0)
    assert page.evaluate('sentTurns.length') == 0


def test_stale_tab_reconciles_without_replaying_or_overwriting_the_newer_choice(phase_page):
    page, states, calls, copy, context, base = phase_page
    other = context.new_page()
    other.goto(base + '/memoir/interview/phases', wait_until='networkidle')
    expect(other.locator('[data-phase-action=shape]')).to_be_enabled()
    click(other, 'shape'); click(other, 'comfort')
    before = sum(method == 'PATCH' for _, method, *_ in calls)
    # Programmatic click keeps the first page stale without focus revalidation.
    page.locator('[data-phase-action=comfort]').evaluate('button => button.click()')
    expect(page.locator('.phase-status')).to_have_text(copy['conflict'])
    expect(page.locator('[data-phase-action=comfort]')).to_have_attribute('aria-pressed', 'true')
    expect(page.locator('#chat-input')).to_be_enabled()
    expect(page.locator('[data-action=voice-input]')).to_be_visible()
    assert sum(method == 'PATCH' for _, method, *_ in calls) == before + 1
    assert states[('owner', 'phases')]['phase'] == 'comfort'


def test_project_and_account_switches_use_their_own_authoritative_state(phase_page):
    page, _, _, _, _, base = phase_page
    click(page, 'comfort')
    page.evaluate("history.pushState({},'', '/memoir/interview/other');window.dispatchEvent(new PopStateEvent('popstate'))")
    expect(page.locator('[data-phase-action=shape]')).to_have_attribute('aria-pressed', 'true')
    expect(page.locator('#chat-input')).to_be_enabled()
    page.goto(base + '/memoir/interview/phases', wait_until='networkidle')
    expect(page.locator('[data-phase-action=comfort]')).to_have_attribute('aria-pressed', 'true')
    page.evaluate('fixturePrincipal("other")')
    expect(page.locator('[data-phase-action=explore]')).to_have_attribute('aria-pressed', 'true')
    expect(page.locator('#chat-input')).to_be_enabled()
    expect(page.locator('[data-phase-action=resume]')).to_have_count(0)


def test_saved_turn_updates_phase_before_workspace_finishes_without_delaying_next_input(phase_page):
    page, states, _, copy, _, _ = phase_page
    page.locator('#chat-input').fill('I remember the little garden.')
    page.locator('#chat-form button[type=submit]').click()
    page.wait_for_function('sentTurns.length === 1')
    saved = phase(phase='explore', revision=1, reason='supported_memory')
    states[('owner', 'phases')] = saved
    page.evaluate('(conversation_phase) => turnEvent("conversation_saved", {conversation_saved:true, reply:"What grew there?", conversation_phase})', saved)
    expect(page.locator('.phase-status')).to_have_text(copy['exploreStatus'])
    expect(page.locator('#chat-form button[type=submit]')).to_be_enabled()
    click(page, 'shape')
    page.evaluate('(conversation_phase) => {turnEvent("result", {reply:"What grew there?", conversation_phase});turnController.close()}', saved)
    expect(page.locator('[data-phase-action=shape]')).to_have_attribute('aria-pressed', 'true')
    assert page.evaluate('sentTurns.length') == 1


def test_guidance_changes_wait_for_saved_reply_and_next_message_needs_no_resume(phase_page):
    page, states, _, copy, _, _ = phase_page
    page.locator('#chat-input').fill('I remember the garden.')
    page.locator('#chat-form button[type=submit]').click()
    page.wait_for_function('sentTurns.length === 1')
    expect(page.locator('#chat-form button[type=submit]')).to_be_disabled()
    for action in ['comfort','explore','shape','automatic','skip']:
        expect(page.locator(f'[data-phase-action={action}]')).to_be_disabled()
    expect(page.locator('[data-phase-action=pause]')).to_have_count(0)
    saved = phase(phase='explore', revision=1, reason='narration')
    states[('owner', 'phases')] = saved
    page.evaluate('(conversation_phase) => {turnEvent("conversation_saved", {conversation_saved:true, reply:"What grew there?", conversation_phase});turnController.close()}', saved)
    expect(page.locator('#chat-form button[type=submit]')).to_be_enabled()
    click(page, 'shape')
    page.locator('#chat-input').fill('Actually, the year was 1966.')
    page.locator('#chat-form button[type=submit]').click()
    page.wait_for_function('sentTurns.length === 2')
    saved = dict(states[('owner', 'phases')])
    page.evaluate('(conversation_phase) => {turnEvent("conversation_saved", {conversation_saved:true, reply:"The garden year is 1966.", conversation_phase});turnController.close()}', saved)
    expect(page.locator('[data-phase-action=shape]')).to_have_attribute('aria-pressed','true')
    expect(page.locator('#chat-form button[type=submit]')).to_be_enabled()
    expect(page.locator('[data-action=voice-input]')).to_be_visible()


def test_correction_finishes_at_recall_limit_and_guidance_controls_remain_available(phase_page):
    page, states, _, copy, _, _ = phase_page
    click(page, 'shape')
    page.locator('#chat-input').fill('Actually, the year was 1966.')
    page.locator('#chat-form button[type=submit]').click()
    page.wait_for_function('sentTurns.length === 1')
    saved = dict(states[('owner', 'phases')])
    page.evaluate('''(conversation_phase) => {
      turnEvent('conversation_saved', {conversation_saved:true, reply:'The year is 1966.', conversation_phase,
        recall_status:{rounds_completed:20, payment_required:true}});
      turnController.close();
    }''', saved)
    expect(page.locator('.assistant-message .message-text').last).to_have_text('The year is 1966.')
    expect(page.locator('.phase-status')).to_have_text(copy['shapeStatus'])
    expect(page.locator('#chat-form')).to_have_count(0)
    assert page.evaluate("Object.keys(sessionStorage).filter(key => key.startsWith('memory-spark-pending-turn:')).length") == 0
    click(page, 'comfort')
    expect(page.locator('[data-phase-action=comfort]')).to_have_attribute('aria-pressed', 'true')
    expect(page.locator('[data-phase-action=pause]')).to_have_count(0)
    expect(page.locator('#chat-form')).to_have_count(0)
    assert page.evaluate('sentTurns.length') == 1
