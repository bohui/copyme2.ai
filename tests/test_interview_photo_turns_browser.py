"""Shipped interview UI, isolated synthetic API/media and no provider/model calls."""
import base64
import json
import os
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright

pytestmark = pytest.mark.skipif(not os.getenv('MEMOIR_BROWSER_URL'), reason='Requires isolated frontend')
PHOTO_ID = '11111111-1111-4111-8111-111111111111'
PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a9lcAAAAASUVORK5CYII=')


@pytest.fixture(params=[(1440, 1000), (390, 844)], ids=['desktop', 'phone'])
def photo_page(request):
    base = os.environ['MEMOIR_BROWSER_URL']
    reference = dict(key='/static/reference-fixture.png', image_url='/static/reference-fixture.png', title='Public gate reference', source_url='https://archive.example/gate')
    profile = dict(name='Fixture', preferred_language='en-AU', photo_memories={'photos': dict(favorites=[reference], selected=reference['key'], selection_revision='selection-1')})
    calls, errors = [], []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.getenv('CHROMIUM_EXECUTABLE', '/usr/bin/chromium'), args=['--no-sandbox'])
        context = browser.new_context(viewport={'width':request.param[0], 'height':request.param[1]}, reduced_motion='reduce')
        context.add_cookies([dict(name='copyme2_ui_locale', value='en-AU', url=base),dict(name='copyme2_ui_locale_source', value='fixed', url=base)])
        context.route('https://**', lambda r:r.abort())
        script = """const session=()=>({access_token:'fixture-'+(localStorage.getItem('fixture-owner')||'owner'),user:{id:localStorage.getItem('fixture-owner')||'owner',is_anonymous:true}});
          window.fixturePrincipal=id=>{localStorage.setItem('fixture-owner',id);window.fixtureAuth?.('SIGNED_IN',session())};
          window.supabase={createClient:()=>({auth:{getSession:async()=>({data:{session:session()}}),getUser:async()=>({data:{user:session().user}}),onAuthStateChange:fn=>{window.fixtureAuth=fn;return {}}}})};"""
        context.route('https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2', lambda r:r.fulfill(content_type='text/javascript',body=script))
        def api(route):
            path=route.request.url.split('/api/v1/memoir')[-1].split('?')[0]
            calls.append((path,route.request.headers,route.request.post_data_buffer))
            data={}
            if path=='/agent/config': data=dict(auth_mode='supabase',supabase_url='https://auth.test',supabase_publishable_key='public')
            elif path in ['/agent/profile','/user/profile']:
                data=profile if route.request.headers.get('authorization')=='Bearer fixture-owner' else dict(preferred_language='en-AU')
            elif path=='/projects/photos':
                data=dict(id='photos',mode='self',profile=profile if route.request.headers.get('authorization')=='Bearer fixture-owner' else {},revision=1)
            elif path.endswith('/journey'): data=dict(active_session=None)
            elif path=='/story/state': data=dict(family_features_enabled=False,recall_status=dict(payment_required=False))
            elif path=='/user/conversations':data=dict(items=[])
            elif path=='/user/projects/photos/history':data=dict(project_id='photos',policy_epoch='1',items=profile.get('history',[]),next_cursor=None)
            elif path=='/story/transcriptions':data=dict(text='I caught insects with my parents.')
            elif path=='/story/question-audio':return route.fulfill(status=503,json={})
            elif path.startswith('/agent/turns/'):
                data=profile.get('receipt',dict(state='not_found'))
            elif path=='/agent/projects/photos/photos': data=dict(id=PHOTO_ID,photo_id='upload:'+PHOTO_ID,kind='private_upload')
            elif path.endswith('/photos/'+PHOTO_ID+'/content'):
                return route.fulfill(body=PNG,content_type='image/png')
            elif path.endswith('/memory-sessions'):return route.fulfill(status=403,json={})
            route.fulfill(json=data)
        context.route('**/api/v1/memoir/**',api)
        context.route('**/static/reference-fixture.png',lambda r:r.fulfill(body=PNG,content_type='image/png'))
        context.add_init_script("""window.spoken=[];Object.defineProperty(window,'speechSynthesis',{value:{cancel(){},speak:utterance=>spoken.push(utterance.text)}});
          Object.defineProperty(navigator,'mediaDevices',{value:{getUserMedia:async()=>({getTracks:()=>[{stop(){}}]})}});
          window.MediaRecorder=class extends EventTarget{static isTypeSupported(){return true}constructor(){super();this.state='inactive';this.mimeType='audio/webm'}start(){this.state='recording'}stop(){this.state='inactive';this.dispatchEvent(new MessageEvent('dataavailable',{data:new Blob(['synthetic audio'])}));this.dispatchEvent(new Event('stop'))}};""")
        context.add_init_script("localStorage.setItem('memory-spark-project:owner',JSON.stringify({projectId:'photos',updatedAt:1}));sessionStorage.setItem('memory-spark-chat-history:owner:photos',JSON.stringify([{id:'opening',role:'assistant',text:'What games did you play?'}]));")
        context.add_init_script("""const nativeFetch=window.fetch;window.sentTurns=[];window.fetch=(url,options)=>{
          if(!String(url).endsWith('/agent/turn'))return nativeFetch(url,options);
          window.sentTurns.push(JSON.parse(options.body));
          if(window.failTurn)return Promise.reject(new Error('Synthetic connection interruption'));
          return Promise.resolve(new Response(new ReadableStream({start(controller){window.turnController=controller}}),{headers:{'Content-Type':'application/x-ndjson'}}));};
          window.turnEvent=(type,data)=>turnController.enqueue(new TextEncoder().encode(JSON.stringify({type,data})+'\\n'));
          window.finishTurn=data=>{turnEvent('conversation_saved',{conversation_saved:true,...data});turnController.close()};""")
        page=context.new_page();page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto(base+'/memoir/interview/photos',wait_until='networkidle')
        expect(page.locator('#chat-input')).to_be_enabled(timeout=30000)
        yield page,profile,calls,request.node.callspec.id
        assert not errors,errors
        browser.close()


def send(page,text='I caught insects with my parents.'):
    page.locator('#chat-input').fill(text)
    page.locator('#chat-form button[type=submit]').click()
    page.wait_for_function('sentTurns.length>0')


def receipt():
    return dict(state='source_accepted',photo_cue=dict(consumed=True,key='/static/reference-fixture.png',revision='selection-1'))


def test_acceptance_clears_cue_shows_response_card_and_keeps_only_one_question(photo_page):
    page,profile,_,viewport=photo_page
    expect(page.locator('.selected-photo-cue')).to_be_visible()
    send(page)
    expect(page.locator('.selected-photo-cue')).to_be_visible()
    page.evaluate('(data)=>turnEvent("source_accepted",data)',receipt())
    expect(page.locator('.selected-photo-cue')).to_have_count(0)
    reply='Catching insects with your parents sounds vivid. Where did you look for them?'
    cards=[dict(photo_id='reference:gate',kind='public_reference',title='Public gate reference',image_url='/static/reference-fixture.png',source_url='https://archive.example/gate')]
    page.evaluate('(data)=>finishTurn(data)',dict(reply=reply,response_photos=cards,**receipt()))
    expect(page.locator('.assistant-message .response-photo-card')).to_have_count(1)
    expect(page.locator('.assistant-message .message-text').last).to_have_text(reply)
    assert page.locator('.assistant-message .message-text').last.inner_text().count('?')==1
    assert 'question_pool' not in page.locator('#chat-history').inner_text()
    page.locator('.assistant-message [data-action=speak]').last.click()
    page.wait_for_function('spoken.length===1')
    assert page.evaluate('spoken[0]')==reply
    assert page.evaluate('sentTurns[0].photo_selection')==dict(key='/static/reference-fixture.png',revision='selection-1')
    assert len(profile['photo_memories']['photos']['favorites'])==1
    profile['photo_memories']['photos']['selected']=None
    page.reload(wait_until='networkidle')
    toggle=page.locator('[data-action=toggle-chat-history]')
    if toggle.count() and toggle.get_attribute('aria-expanded')=='false':toggle.click()
    expect(page.locator('.assistant-message .response-photo-card')).to_have_count(1)
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    out=Path('/tmp/issue41-ui');out.mkdir(exist_ok=True);page.screenshot(path=str(out/f'{viewport}-response.png'))


def test_failed_send_retains_cue_and_retry_identity_across_reload(photo_page):
    page,_,_,_=photo_page
    page.evaluate('window.failTurn=true')
    send(page)
    original=page.evaluate('sentTurns[0]')
    expect(page.locator('.selected-photo-cue')).to_be_visible()
    page.reload(wait_until='networkidle')
    retry=page.locator('[data-action=retry-interview-turn]')
    expect(retry).to_be_visible();retry.click()
    page.wait_for_function('sentTurns.length===1')
    assert page.evaluate('sentTurns[0].client_turn_id')==original['client_turn_id']
    assert page.evaluate('sentTurns[0].photo_selection')==original['photo_selection']
    page.evaluate('(data)=>finishTurn(data)',dict(reply='Which path did you take?',**receipt()))
    expect(page.locator('.selected-photo-cue')).to_have_count(0)


def test_private_upload_uses_owned_id_and_authenticated_blob_display(photo_page):
    page,_,calls,_=photo_page
    page.locator('#chat-attachments').set_input_files(dict(name='garden.png',mimeType='image/png',buffer=PNG))
    page.locator('#attachment-rights').check()
    send(page,'This is the garden I planted.')
    assert page.evaluate('sentTurns[0].uploaded_photo_ids')==[PHOTO_ID]
    expect(page.locator('.composer-wrap .composer-attachment')).to_have_count(1)
    page.evaluate('(data)=>finishTurn(data)',dict(reply='What did you plant first?',response_photos=[dict(photo_id='upload:'+PHOTO_ID,kind='private_upload',title='Your private photo')],**receipt()))
    expect(page.locator('.composer-wrap .composer-attachment')).to_have_count(0)
    image=page.locator('.assistant-message .response-photo-card img')
    expect(image).to_have_attribute('src',__import__('re').compile('^blob:'))
    private_reads=[headers for path,headers,_ in calls if path.endswith('/content')]
    assert private_reads and all(h['authorization']=='Bearer fixture-owner' for h in private_reads)
    page.evaluate('fixturePrincipal("other")')
    expect(page.locator('.response-photo-card')).to_have_count(0)
    expect(page.locator('.composer-attachment')).to_have_count(0)


def test_transcribed_answer_uses_the_same_photo_snapshot(photo_page):
    page,_,_,_=photo_page
    page.locator('[data-action=dictate]').click()
    expect(page.locator('[data-action=accept-dictation]')).to_be_visible()
    page.locator('[data-action=accept-dictation]').click()
    page.wait_for_function('sentTurns.length===1')
    assert page.evaluate('sentTurns[0].source_kind')=='narrator_transcript'
    assert page.evaluate('sentTurns[0].conversation_text')=='I caught insects with my parents.'
    assert page.evaluate('sentTurns[0].photo_selection')==dict(key='/static/reference-fixture.png',revision='selection-1')
    page.evaluate('(data)=>finishTurn(data)',dict(reply='Where did you look for insects?',**receipt()))
    expect(page.locator('.selected-photo-cue')).to_have_count(0)


def test_photo_only_upload_does_not_send_synthetic_narrator_text(photo_page):
    page,_,_,_=photo_page
    page.locator('#chat-attachments').set_input_files(dict(name='garden.png',mimeType='image/png',buffer=PNG))
    page.locator('#attachment-rights').check()
    page.locator('#chat-form button[type=submit]').click()
    page.wait_for_function('sentTurns.length===1')
    assert page.evaluate('sentTurns[0].text')==''
    assert page.evaluate('sentTurns[0].conversation_text')==''
    assert page.evaluate('sentTurns[0].uploaded_photo_ids')==[PHOTO_ID]
    page.evaluate('(data)=>finishTurn(data)',dict(reply='What would you like to tell me about this photo?',**receipt()))
    expect(page.locator('.composer-wrap .composer-attachment')).to_have_count(0)


def test_reload_recovers_durable_reply_and_card_without_resubmitting(photo_page):
    page,profile,_,_=photo_page
    send(page)
    page.evaluate('(data)=>turnEvent("source_accepted",data)',receipt())
    expect(page.locator('.selected-photo-cue')).to_have_count(0)
    profile['photo_memories']['photos']['selected']=None
    profile['receipt']=dict(state='conversation_saved',conversation_saved=True,reply='Who walked through the gate with you?',
      photo_cue=receipt()['photo_cue'],response_photos=[dict(photo_id='reference:gate',kind='public_reference',title='Public gate reference',image_url='/static/reference-fixture.png')])
    page.reload(wait_until='networkidle')
    toggle=page.locator('[data-action=toggle-chat-history]')
    if toggle.count() and toggle.get_attribute('aria-expanded')=='false':toggle.click()
    expect(page.locator('.response-photo-card')).to_have_count(1)
    expect(page.locator('.assistant-message .message-text').last).to_have_text(profile['receipt']['reply'])
    assert page.evaluate('sentTurns.length')==0
    expect(page.locator('[data-action=retry-interview-turn]')).to_have_count(0)


def test_fresh_tab_loads_authorized_canonical_photo_cards_without_local_receipt(photo_page):
    page,profile,_,_=photo_page
    profile['photo_memories']['photos']['selected']=None
    profile['history']=[dict(server_turn_id='saved-server-turn',client_turn_id='saved-client-turn',kind='agent',
      created_at='2026-10-08T12:00:00Z',source_status='active',source_version='1',
      narrator_text='I remember this private garden.',reply='What did you grow there?',
      response_photos=[dict(photo_id='upload:'+PHOTO_ID,kind='private_upload',title='Your private photo')])]
    fresh=page.context.new_page()
    fresh.goto(os.environ['MEMOIR_BROWSER_URL']+'/memoir/interview/photos',wait_until='networkidle')
    expect(fresh.locator('#chat-input')).to_be_enabled()
    toggle=fresh.locator('[data-action=toggle-chat-history]')
    if toggle.count() and toggle.get_attribute('aria-expanded')=='false':toggle.click()
    expect(fresh.locator('.assistant-message .response-photo-card')).to_have_count(1)
    expect(fresh.locator('.assistant-message .message-text').last).to_have_text('What did you grow there?')
    expect(fresh.locator('.response-photo-card img')).to_have_attribute('src',__import__('re').compile('^blob:'))
    assert fresh.evaluate('sentTurns.length')==0
    fresh.close()
