"""Viewport and streaming behavior using synthetic history/auth/model fixtures."""
import json
import os
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright

pytestmark = pytest.mark.skipif(not os.getenv('MEMOIR_BROWSER_URL'), reason='Requires isolated source frontend')
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def conversation_page():
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        context = browser.new_context(viewport={'width':390, 'height':844}, reduced_motion='reduce')
        context.add_cookies([{'name':'copyme2_ui_locale','value':'en-AU','url':os.environ['MEMOIR_BROWSER_URL']},
                            {'name':'copyme2_ui_locale_source','value':'fixed','url':os.environ['MEMOIR_BROWSER_URL']}])
        base = os.environ['MEMOIR_BROWSER_URL']
        user = {'id':'scroll-fixture-owner', 'is_anonymous':False, 'user_metadata':{}}
        script = f"""window.supabase={{createClient:()=>({{auth:{{
          getSession:async()=>({{data:{{session:{{access_token:'fixture-only',user:{json.dumps(user)}}}}}}}),
          getUser:async()=>({{data:{{user:{json.dumps(user)}}}}}),onAuthStateChange:()=>({{}})
        }}}})}};"""
        context.route('https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2', lambda r:r.fulfill(content_type='text/javascript',body=script))
        profile = {'preferred_language':'en-AU', 'name':'Fixture', 'conversation_language':{'initialized':True,'locale':'en-AU','source':'explicit','version':1,'revision':1}}
        def api(route):
            path = route.request.url.split('/api/v1/memoir')[-1].split('?')[0]
            data = {}
            if path == '/agent/config': data = {'supabase_url':'https://auth.test','supabase_publishable_key':'public','auth_mode':'supabase','show_thinking_steps':True}
            elif path in ('/agent/profile','/user/profile'): data = profile
            elif path == '/projects/scroll-project': data = {'id':'scroll-project','revision':1,'profile':profile,'mode':'self','workspace_unlocked':False}
            elif path == '/story/state': data = {'family_features_enabled':False,'recall_status':{'rounds_completed':0,'free_rounds':200,'paid':False,'payment_required':False}}
            elif path == '/user/conversations': data = {'items':[]}
            elif path == '/user/projects/scroll-project/history':
                data = {'project_id':'scroll-project', 'policy_epoch':'1', 'items':[], 'next_cursor':None}
            elif path == '/projects/scroll-project/journey': data = {'active_session':None}
            elif path == '/agent/place-journey': data = {'place_journey':None}
            elif path.endswith('/memory-sessions'): return route.fulfill(status=403,content_type='application/json',body='{}')
            return route.fulfill(content_type='application/json',body=json.dumps(data))
        context.route('**/api/v1/memoir/**', api)
        messages = [{'id':f'fixture-{i}', 'role':'user' if i%2 else 'assistant', 'text':f'Synthetic history {i}. '+('A familiar garden and a small path. '*8)} for i in range(40)]
        context.add_init_script(f"localStorage.setItem('memory-spark-project','scroll-project');sessionStorage.setItem('memory-spark-chat-history:scroll-project',{json.dumps(json.dumps(messages))});")
        # Timed ReadableStream is a real streaming browser response, without a live model.
        context.add_init_script("""const nativeFetch=window.fetch;
          window.fixtureTurns=0;
          window.fetch=(url, options)=>{
            if(!String(url).endsWith('/agent/turn')) return nativeFetch(url, options);
            window.fixtureTurns++;
            const encoder=new TextEncoder();let index=0;
            const stream=new ReadableStream({start(controller){
              setTimeout(()=>{const timer=setInterval(()=>{
                const event=index<32 ? {type:'text_delta',text:'Synthetic streamed garden detail '+index+'. '.repeat(12)} : {type:'result',data:{reply:'Synthetic streamed garden detail. '.repeat(100)}};
                controller.enqueue(encoder.encode(JSON.stringify(event)+'\\n'));index++;
                if(index>32){clearInterval(timer);controller.close();}
              },80);},300);
            }});
            return Promise.resolve(new Response(stream,{headers:{'Content-Type':'application/x-ndjson'}}));
          };""")
        page = context.new_page()
        page.goto(base+'/memoir/interview/scroll-project')
        expect(page.locator('#chat-input')).to_be_enabled(timeout=30000)
        toggle = page.locator('[data-action="toggle-chat-history"]')
        if toggle.get_attribute('aria-expanded') == 'false': toggle.click()
        expect(page.locator('.user-message')).to_have_count(20)
        page.evaluate("document.querySelector('#chat-scroll').scrollTop=1e9")
        yield page
        browser.close()


def metrics(page):
    return page.evaluate("""()=>{const s=document.querySelector('#chat-scroll');return {
      pageY:window.scrollY, pageHeight:document.documentElement.scrollHeight,height:innerHeight,
      bottom:s.scrollHeight-s.scrollTop-s.clientHeight,top:s.scrollTop,historyHeight:s.clientHeight,
      header:document.querySelector('.story-topbar').getBoundingClientRect().toJSON(),
      composer:document.querySelector('.composer-wrap').getBoundingClientRect().toJSON()};}""")


def screenshot(page, name):
    path = ROOT / 'output/scroll-debug' / f'{name}.png'
    path.parent.mkdir(parents=True,exist_ok=True)
    page.screenshot(path=str(path))


def expect_bottom(page):
    page.wait_for_function("(()=>{const e=document.querySelector('#chat-scroll');return e.scrollHeight-e.scrollTop-e.clientHeight<3})()")


def test_read_aloud_headers_align_for_short_and_long_replies(conversation_page):
    page = conversation_page
    for width, height in [(390, 844), (1440, 1000)]:
        page.set_viewport_size({'width': width, 'height': height})
        for label in ['◖ 朗读 · AI 语音', '◖ Listen · AI voice']:
            page.evaluate("""label => {
              const bubbles = [...document.querySelectorAll('.assistant-message .chat-bubble')];
              bubbles.forEach((bubble, index) => {
                bubble.querySelector('.message-text').textContent = index % 2
                  ? '韩凤江，很高兴认识您。您最早记得的一段往事是什么？'
                  : 'A longer memory of the childhood garden and the people who lived nearby. '.repeat(6);
                bubble.querySelector('.listen-button').textContent = label;
              });
            }""", label)
            boxes = page.locator('.assistant-message .chat-bubble').evaluate_all("""bubbles => bubbles.map(b => {
              const header = b.querySelector('.message-meta').getBoundingClientRect();
              const button = b.querySelector('.listen-button').getBoundingClientRect();
              const name = b.querySelector('.message-label').getBoundingClientRect();
              return {right: button.right, headerRight: header.right, nameRight: name.right,
                left: button.left, center: button.y + button.height / 2,
                nameCenter: name.y + name.height / 2};
            })""")
            assert len(boxes) > 1
            assert max(b['right'] for b in boxes) - min(b['right'] for b in boxes) < 1
            assert all(abs(b['right'] - b['headerRight']) < 1 for b in boxes)
            assert all(b['left'] > b['nameRight'] for b in boxes)
            assert all(abs(b['center'] - b['nameCenter']) < 1 for b in boxes)
        screenshot(page, f'read-aloud-aligned-{width}')


def test_viewport_resize_and_multiline_composer(conversation_page):
    page = conversation_page
    phase = os.environ.get('SCROLL_CAPTURE_PHASE','after')
    for width,height in [(390,844),(1440,1000),(823,768),(844,390)]:
        page.set_viewport_size({'width':width,'height':height})
        page.wait_for_timeout(150)
        screenshot(page,f'{phase}-{width}x{height}')
        m=metrics(page)
        if phase=='before': continue
        assert m['pageY']==0 and m['pageHeight']<=height+1, m
        assert abs(m['header']['top'])<1 and abs(m['composer']['bottom']-height)<1, m
        assert m['historyHeight']>40, m
        expect_bottom(page)
        page.locator('#chat-input').fill('Long synthetic input\n'*25)
        page.wait_for_timeout(100)
        assert metrics(page)['pageHeight']<=height+1
        assert page.locator('#chat-input').evaluate('(e)=>e.scrollHeight>e.clientHeight')
        page.locator('#chat-input').fill('')
        expect_bottom(page)


def test_send_stream_scrollback_late_content_and_keyboard(conversation_page):
    page=conversation_page
    scroll=page.locator('#chat-scroll')
    scroll.evaluate('(e)=>e.scrollTop=80')
    field=page.locator('#chat-input')
    field.fill('A new synthetic memory. '*35)
    page.locator('#chat-form button[type="submit"]').click()
    page.locator('#chat-form').dispatch_event('submit')
    expect(page.locator('.user-message')).to_have_count(21)
    expect(page.locator('.thinking:visible, .message-thinking:visible')).to_have_count(1)
    page.wait_for_timeout(200)
    assert metrics(page)['bottom']<3, metrics(page)
    assert page.evaluate('fixtureTurns')==1
    page.wait_for_timeout(400)
    expect_bottom(page)
    scroll.evaluate('(e)=>e.scrollTop=100')
    page.wait_for_timeout(300)
    assert metrics(page)['top']<120, metrics(page)
    scroll.evaluate('(e)=>e.scrollTop=1e9')
    page.wait_for_timeout(300)
    assert metrics(page)['bottom']<3
    expect(page.locator('#chat-form button[type="submit"]')).to_be_enabled(timeout=10000)
    # ResizeObserver must follow late media/layout growth, and preserve scrollback.
    page.evaluate("window.late=new Image();document.querySelector('#chat-history').append(late);setTimeout(()=>{late.src='data:image/svg+xml,'+encodeURIComponent('<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"200\" height=\"500\"></svg>')},50)")
    page.wait_for_timeout(150)
    assert metrics(page)['bottom']<3
    scroll.evaluate('(e)=>e.scrollTop=80')
    page.wait_for_timeout(100)
    page.evaluate("late.style.height='850px'")
    page.wait_for_timeout(150)
    assert metrics(page)['top']<100
    # Simulate VisualViewport keyboard events; real device IME remains a manual check.
    page.evaluate("""window.fixtureViewport=new EventTarget();Object.assign(fixtureViewport,{height:460,offsetTop:0,scale:1});Object.defineProperty(window,'visualViewport',{value:fixtureViewport,configurable:true});window.dispatchEvent(new Event('resize'));""")
    page.wait_for_timeout(150)
    assert metrics(page)['composer']['bottom']<=461
    assert metrics(page)['top']<100
    page.evaluate("fixtureViewport.height=844;window.dispatchEvent(new Event('resize'))")
    page.wait_for_timeout(150)
    assert metrics(page)['composer']['bottom']<=845
    scroll.evaluate('(e)=>e.scrollTop=1e9')
    page.wait_for_timeout(100)
    page.evaluate("fixtureViewport.height=460;window.dispatchEvent(new Event('resize'))")
    page.wait_for_timeout(150)
    expect_bottom(page)
    page.evaluate("fixtureViewport.height=844;window.dispatchEvent(new Event('resize'))")
    page.wait_for_timeout(150)
    expect_bottom(page)
    # Keyboard access and dialogs keep their own reachable content.
    scroll.focus()
    assert scroll.get_attribute('tabindex')=='0'
    page.locator('[data-profile-trigger]').click()
    page.locator('[data-profile-action="settings"]').click()
    expect(page.locator('[data-profile-settings]')).to_be_visible()
    page.keyboard.press('Escape')
    expect(page.locator('[data-profile-settings]')).to_have_count(0)
    field.fill('Another synthetic memory.')
    page.locator('#chat-form button[type="submit"]').click()
    page.wait_for_timeout(200)
    assert metrics(page)['bottom']<3
    assert page.evaluate('fixtureTurns')==2
    screenshot(page,'after-mobile-stream')


def test_mobile_voice_controls_with_synthetic_microphone(conversation_page):
    page=conversation_page
    page.evaluate("""()=>{window.fixtureMicRequests=0;window.fixtureTrack={enabled:true,stop(){}};
      Object.defineProperty(navigator,'mediaDevices',{configurable:true,value:{getUserMedia:async()=>{fixtureMicRequests++;return {getTracks:()=>[fixtureTrack]}}}});
      window.AudioContext=undefined;window.webkitAudioContext=undefined;
      window.MediaRecorder=class extends EventTarget {
        static isTypeSupported(){return true} constructor(){super();this.state='inactive';this.mimeType='audio/webm'}
        start(){this.state='recording'} stop(){this.state='inactive';this.dispatchEvent(new Event('stop'))}
      };}""")
    for width in [320,390,560,823]:
        page.set_viewport_size({'width':width,'height':844})
        button=page.locator('.voice-mode-launcher')
        expect(button).to_be_visible()
        box=button.bounding_box()
        assert box['x']>=0 and box['x']+box['width']<=width
        assert box['y']+box['height']<=844
    page.set_viewport_size({'width':390,'height':844})
    page.locator('.voice-mode-launcher').click()
    expect(page.locator('#chat-form')).to_have_attribute('data-voice-mode','on')
    expect(page.locator('.voice-mode-status')).to_be_visible()
    assert page.evaluate('fixtureMicRequests')==1
    page.locator('[data-action="mute-voice"]').click()
    assert page.evaluate('fixtureTrack.enabled') is False
    page.locator('[data-action="mute-voice"]').click()
    assert page.evaluate('fixtureTrack.enabled') is True
    screenshot(page,'after-mobile-voice')
    page.locator('.voice-mode-end').click()
    expect(page.locator('.voice-mode-launcher')).to_be_visible()
    assert page.evaluate('fixtureMicRequests')==1


def test_saved_draft_stays_reachable_without_page_scroll(conversation_page):
    page=conversation_page
    page.route('**/api/v1/memoir/story/private-draft?*',lambda r:r.fulfill(content_type='application/json',body=json.dumps({'milestone':5,'preview':{'title':'Synthetic saved draft','text':'Synthetic draft paragraph. '*200}})))
    page.reload()
    expect(page.locator('.private-draft-status')).to_be_visible(timeout=10000)
    for width,height in [(390,844),(823,768),(1440,1000)]:
        page.set_viewport_size({'width':width,'height':height})
        page.wait_for_timeout(150)
        assert metrics(page)['pageHeight']<=height+1
        page.locator('.private-draft-status summary').click()
        expect(page.locator('.private-draft-status h3')).to_be_visible()
        page.wait_for_timeout(100)
        assert metrics(page)['pageHeight']<=height+1
        assert page.locator('.private-draft-status').evaluate('(e)=>e.scrollHeight>e.clientHeight')
        page.locator('.private-draft-status summary').click()
        # A draft without an active map stays in the conversation. It must
        # remain readable without activating an empty map workspace.
        expect(page.locator('#workspace-detail')).to_have_count(0)
        expect(page.locator('[data-action="toggle-workspace"]')).to_have_count(0)
        assert metrics(page)['composer']['bottom']<=height+1
        expect(page.locator('.private-draft-status')).to_be_visible()
    screenshot(page,'after-desktop-workspace')
