"""Synthetic mobile map albums; all API, photo and imagery responses are fixtures."""
import json
import os
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright

pytestmark = pytest.mark.skipif(not os.getenv('MEMOIR_BROWSER_URL'), reason='Requires isolated frontend')
OUTPUT = Path(__file__).resolve().parents[1] / 'output/phone-map-albums'


@pytest.fixture
def album_page(request):
    mode = getattr(request, 'param', 'saved')
    state_mode = mode.removeprefix('unresolved-')
    base = os.environ['MEMOIR_BROWSER_URL']
    city = dict(place='承德', hierarchy=['Earth', '中国', '河北', '承德'], granularity='city',
                latitude=40.97, longitude=117.93, period='1980s', revision=1, status='active', schema_version=1)
    places = [city, dict(city, place='双桥区', hierarchy=city['hierarchy']+['双桥区'], granularity='suburb', latitude=40.94, longitude=117.96, revision=2),
              dict(city, place='大石庙镇', hierarchy=city['hierarchy']+['大石庙镇'], granularity='suburb', latitude=40.9401, longitude=117.9601, revision=3)]
    if mode == 'current':
        places = [dict(city, period='')]
    for i, place in enumerate(places):
        if mode.startswith('unresolved'):
            place['map_pin']=None
        date = '2026-08-01' if mode == 'current' else '1983'
        place.update(photo_search_period=place['period'], photo_search_policy='place-fallback-gps-time-v8',
                     photo_search_place=place['place']+', 承德' if place['granularity']=='suburb' else place['place'],
                     photo_search_complete=state_mode not in ('loading', 'error','current'), photo_search_at=1,
                     photo_search_latitude=place['latitude'], photo_search_longitude=place['longitude'],
                     pictures=[] if state_mode in ('empty','loading','error','current') else [dict(asset_id=f'{i}-{j}', title=f'{place["place"]} fixture {j}',
                       image_url=f'/static/album-fixture-{i}-{j}.svg', source_url='https://archive.example/photo',
                       attribution='Synthetic test archive', date_expression=date, latitude=place['latitude'],
                       longitude=place['longitude'], allowed_actions={'embed':True}) for j in range(3)])
    profile = {'name':'Fixture', 'preferred_language':'zh-CN', 'memory_places':places}
    calls, errors = [], []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width':390,'height':844}, reduced_motion='reduce', is_mobile=True, has_touch=True)
        context.add_cookies([{'name':'copyme2_ui_locale','value':'zh-CN','url':base}, {'name':'copyme2_ui_locale_source','value':'fixed','url':base}])
        def boundary(route):
            if route.request.url.startswith(base) or any(host in route.request.url for host in ('cesium.com/', 'fonts.googleapis.com/', 'fonts.gstatic.com/')):
                route.continue_()
            else:
                route.abort()
        context.route('**/*', boundary)
        def cesium(route):
            response = route.fetch()
            route.fulfill(response=response, body=response.text()+'''\nCesium.Google2DImageryProvider.fromUrl=async()=>new Cesium.GridImageryProvider();
              const OriginalViewer=Cesium.Viewer;window.Cesium={...Cesium,Viewer:new Proxy(OriginalViewer,{construct(target,args){
                const viewer=Reflect.construct(target,args);window.__mapViewer=viewer;return viewer;}})};''')
        context.route('**/Build/Cesium/Cesium.js', cesium)
        context.route('**/static/album-fixture-*.svg', lambda r:r.fulfill(content_type='image/svg+xml',body='<svg xmlns="http://www.w3.org/2000/svg" width="320" height="220"><rect width="320" height="220" fill="#c4d8d2"/><path d="M0 180L110 70L230 180L320 100V220H0" fill="#397465"/><rect x="130" y="130" width="80" height="80" fill="#eee1bb"/><path d="M120 140L170 100L220 140" fill="#a65c43"/></svg>'))
        def api(route):
            path = route.request.url.split('/api/v1/memoir')[-1].split('?')[0]
            data = {}
            if path == '/agent/config': data = {'auth_mode':'test','google_maps_browser_api_key':'synthetic-key'}
            elif path in ('/agent/profile','/user/profile'):
                if route.request.method == 'PATCH': profile.update(route.request.post_data_json)
                data = profile
            elif path == '/projects/album-project':
                if route.request.method == 'PATCH': profile.update(route.request.post_data_json.get('profile',{}))
                data = {'id':'album-project','revision':1,'profile':profile,'mode':'self','workspace_unlocked':False}
            elif path == '/story/state': data = {'family_features_enabled':False,'recall_status':{'payment_required':False}}
            elif path == '/user/conversations': data = {'items':[]}
            elif path.endswith('/journey'): data = {'active_session':None}
            elif path.endswith('/place-photos'):
                calls.append(route.request.url)
                data = {'items':[], 'status':'UNAVAILABLE' if state_mode=='error' else 'NO_MATCH', 'searching':False}
            return route.fulfill(json=data)
        context.route('**/api/v1/memoir/**', api)
        context.add_init_script("localStorage.setItem('memory-spark-project','album-project');sessionStorage.setItem('memory-spark-chat-history:album-project',JSON.stringify([{id:'opening',role:'assistant',text:'Synthetic memory recall conversation'}]));")
        if state_mode == 'loading':
            arriving = dict(asset_id='arriving',title='Arriving dated reference',image_url='/static/album-fixture-arriving.svg',
                source_url='https://archive.example/photo',attribution='Synthetic test archive',date_expression='1986',
                latitude=places[-1]['latitude'],longitude=places[-1]['longitude'],allowed_actions={'embed':True})
            context.add_init_script('''const originalFetch=window.fetch;window.fetch=(url,options)=>String(url).includes('/place-photos?')
              ? new Promise(resolve=>{window.finishPhotoSearch=()=>resolve(new Response(JSON.stringify({items:'''+json.dumps([arriving])+''',status:'PARTIAL',searching:false}),{headers:{'Content-Type':'application/json'}}));})
              : originalFetch(url,options);''')
        page = context.new_page()
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto(base+'/memoir/interview/album-project',wait_until='networkidle')
        expect(page.locator('#chat-input')).to_be_enabled(timeout=30000)
        expect(page.locator('.place-journey-scene.is-cesium-map')).to_be_visible(timeout=30000)
        yield page, calls, errors
        assert not errors, errors
        browser.close()


def test_phone_map_and_album_navigation(album_page):
    page, _, _ = album_page
    OUTPUT.mkdir(parents=True,exist_ok=True)
    phase=os.getenv('ALBUM_CAPTURE_PHASE','after')
    page.screenshot(path=str(OUTPUT/f'{phase}-phone.png'))
    if phase == 'before':
        return
    assert page.locator('.story-topbar').bounding_box()['height'] <= 56
    expect(page.locator('.workspace-media-map-header h2')).not_to_be_visible()
    expect(page.locator('.place-journey-heading')).not_to_be_visible()
    expect(page.locator('.workspace-media-gallery')).not_to_be_visible()
    expect(page.locator('.life-stage-mobile-label').first).to_be_visible()
    scene=page.locator('.place-journey-scene').bounding_box()
    panel=page.locator('.workspace-media-overview').bounding_box()
    assert scene['height'] >= panel['height']-48, (scene,panel)
    stacks=page.locator('.map-photo-album-layer > .map-album-anchor [data-photo-album]:visible')
    expect(stacks).to_have_count(2)
    boxes=stacks.all()
    a,b=[item.bounding_box() for item in boxes]
    assert a['x']+a['width']<=b['x'] or b['x']+b['width']<=a['x'] or a['y']+a['height']<=b['y'] or b['y']+b['height']<=a['y'],(a,b)
    for item in boxes:
        box=item.bounding_box()
        assert box['width']>=44 and box['height']>=44
        assert item.locator('img').count()==3
    before=page.url
    stacks.first.tap()
    dialog=page.get_by_role('dialog')
    expect(dialog).to_be_visible()
    expect(dialog.locator('figure')).to_have_count(3)
    assert '1983' in dialog.inner_text()
    assert page.url==before
    page.screenshot(path=str(OUTPUT/'after-phone-album.png'))
    page.go_back()
    expect(dialog).not_to_be_visible()
    page.go_forward()
    expect(dialog).to_be_visible()
    dialog.locator('[data-close-photo-album]').tap()
    expect(dialog).not_to_be_visible()
    stacks=page.locator('[data-photo-album]:visible')
    stacks.last.tap()
    expect(dialog).to_be_visible()
    assert '大石庙镇' in dialog.inner_text()
    page.keyboard.press('Escape')
    expect(dialog).not_to_be_visible()
    page.wait_for_function('!history.state?.memoirPhotoAlbum')
    marker=page.locator('[data-photo-marker]:visible').last
    marker_box=marker.bounding_box()
    assert marker_box['width']==44 and marker_box['height']==44
    marker.tap()
    expect(dialog).to_be_visible()
    dialog.locator('[data-close-photo-album]').click()
    expect(dialog).not_to_be_visible()
    page.wait_for_function('!history.state?.memoirPhotoAlbum')
    # Real Cesium picking also opens the corresponding album.
    page.evaluate('''() => {const viewer=window.__mapViewer;const entity=viewer.entities.values[0];
      const point=Cesium.SceneTransforms.worldToWindowCoordinates(viewer.scene,entity.position.getValue(Cesium.JulianDate.now()));
      viewer.screenSpaceEventHandler.getInputAction(Cesium.ScreenSpaceEventType.LEFT_CLICK)({position:point});}''')
    expect(dialog).to_be_visible()
    dialog.locator('[data-close-photo-album]').click()
    expect(dialog).not_to_be_visible()
    # Dragging the uncovered canvas remains a map gesture.
    page.wait_for_function('!history.state?.memoirPhotoAlbum')
    previous=page.evaluate('window.__mapViewer.camera.position.x')
    scene=page.locator('.place-journey-scene').bounding_box()
    gesture_y=scene['y']+scene['height']*.65
    assert page.evaluate('([x,y])=>document.elementFromPoint(x,y).tagName', [scene['x']+40,gesture_y])=='CANVAS'
    page.mouse.move(scene['x']+40,gesture_y)
    page.mouse.down();page.mouse.move(scene['x']+150,gesture_y,steps=10);page.mouse.up()
    page.wait_for_function('(old)=>window.__mapViewer.camera.position.x!==old',arg=previous)
    expect(dialog).not_to_be_visible()
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')


@pytest.mark.parametrize('album_page',['empty','error','loading','unresolved-loading','current'],indirect=True)
def test_album_search_states_and_current_default(album_page, request):
    page,calls,_=album_page
    mode=request.node.callspec.params['album_page'].removeprefix('unresolved-')
    page.locator('[data-photo-album]:visible').last.tap()
    dialog=page.get_by_role('dialog')
    expect(dialog).to_be_visible()
    expect(dialog.locator('figure')).to_have_count(0)
    if mode=='error':
        expect(dialog.locator('[data-photo-retry]')).to_be_visible()
        dialog.locator('[data-photo-retry]').click()
        assert calls
    elif mode=='loading':
        expect(dialog.locator('[role="status"]')).to_be_visible()
        page.evaluate('finishPhotoSearch()')
        expect(dialog.locator('.is-loading')).to_have_count(0)
        expect(dialog.locator('figure')).to_have_count(1)
        assert '1986' in dialog.inner_text()
    elif mode=='current':
        assert calls and all('period=&' in url or url.endswith('period=') for url in calls), calls
    dialog.locator('[data-close-photo-album]').click()
    expect(dialog).not_to_be_visible()
    if mode=='loading':
        expect(page.locator('[data-photo-album]:visible').last.locator('img')).to_have_count(1)
        expect(page.locator('[data-photo-album]:visible').last).to_be_focused()


def test_desktop_gallery_and_phone_resize_preserve_map(album_page):
    page,_,_=album_page
    page.set_viewport_size({'width':1440,'height':960})
    expect(page.locator('.workspace-media-gallery')).to_be_visible()
    expect(page.locator('.place-journey-heading')).to_be_visible()
    expect(page.locator('[data-photo-album]:visible')).to_have_count(0)
    assert page.locator('.workspace-media-gallery figure').count()==3
    page.screenshot(path=str(OUTPUT/'after-desktop.png'))
    page.evaluate('window.__previousMapViewer=window.__mapViewer')
    for width,height in [(320,568),(430,932),(760,580),(390,500)]:
        page.set_viewport_size({'width':width,'height':height})
        expect(page.locator('[data-photo-album]:visible').first).to_be_visible()
        assert page.evaluate('window.__previousMapViewer===window.__mapViewer')
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        scene=page.locator('.place-journey-scene').bounding_box()
        assert scene['height']>=100,scene
        assert page.locator('#chat-input').bounding_box()['y']<height


@pytest.mark.parametrize('album_page',['saved','unresolved'],indirect=True)
def test_every_city_group_album_keeps_its_own_photos(album_page,request):
    page,_,_=album_page
    expect(page.locator('[data-photo-album]:visible')).to_have_count(3)
    if request.node.callspec.params['album_page']=='unresolved':
        assert page.evaluate('window.__mapViewer.entities.values.length')==0
        expect(page.locator('[data-photo-marker]:visible')).to_have_count(0)
    for place in ['承德','双桥区','大石庙镇']:
        album=page.locator('[data-photo-album]:visible').filter(has_text=place)
        expect(album).to_have_count(1)
        if place=='承德':
            assert album.bounding_box()['height']==44
        album.tap()
        dialog=page.get_by_role('dialog')
        expect(dialog).to_be_visible()
        assert dialog.locator('figcaption a').all_text_contents()==[f'{place} fixture {i}' for i in range(3)]
        assert '1983' in dialog.inner_text()
        dialog.locator('[data-close-photo-album]').click()
        expect(dialog).not_to_be_visible()
        page.wait_for_function('!history.state?.memoirPhotoAlbum')
    page.screenshot(path=str(OUTPUT/f'after-{request.node.callspec.params["album_page"]}-all-albums.png'))
    expect(page.locator('.place-journey-heading')).not_to_be_visible()


@pytest.mark.parametrize('album_page',['unresolved-empty','unresolved-error'],indirect=True)
def test_no_pin_groups_keep_photo_status_and_retry_reachable(album_page,request):
    page,calls,_=album_page
    expect(page.locator('[data-photo-album]:visible')).to_have_count(3)
    assert page.evaluate('window.__mapViewer.entities.values.length')==0
    for place in ['承德','双桥区','大石庙镇']:
        page.locator('[data-photo-album]:visible').filter(has_text=place).tap()
        dialog=page.get_by_role('dialog')
        expect(dialog).to_be_visible()
        expect(dialog.locator('figure')).to_have_count(0)
        expect(dialog.locator('[role="status"]')).to_be_visible()
        if request.node.callspec.params['album_page']=='unresolved-error':
            retry=dialog.locator('[data-photo-retry]')
            expect(retry).to_be_visible()
            before=len(calls)
            retry.click()
            expect(retry).to_be_visible()
            assert len(calls)>before
        dialog.locator('[data-close-photo-album]').click()
        expect(dialog).not_to_be_visible()
        page.wait_for_function('!history.state?.memoirPhotoAlbum')


def test_pinned_overflow_album_keeps_keyboard_focus_across_cesium_frames(album_page):
    page,_,_=album_page
    page.set_viewport_size({'width':390,'height':500})
    overflow=page.locator('.map-album-overflow [data-album-pinned="true"] [data-photo-album]:visible')
    expect(overflow).to_have_count(2)
    key=overflow.first.get_attribute('data-photo-album')
    page.locator('[data-photo-album]:visible').filter(has_text='承德').focus()
    page.keyboard.press('Tab')
    focus=page.evaluate('''() => new Promise(resolve => {
      const states=[document.activeElement.dataset.photoAlbum || null];
      const remove=window.__mapViewer.scene.postRender.addEventListener(() => {
        states.push(document.activeElement.dataset.photoAlbum || null);
        if(states.length===7){remove();resolve(states);}
      });
      window.__mapViewer.scene.requestRender();
    })''')
    assert focus==[key]*7,focus
    page.keyboard.press('Enter')
    dialog=page.get_by_role('dialog')
    expect(dialog).to_be_visible()
    expect(dialog.locator('h2')).to_have_text('双桥区')
    dialog.locator('[data-close-photo-album]').click()
    expect(dialog).not_to_be_visible()
    page.screenshot(path=str(OUTPUT/'after-short-phone-overflow.png'))


def test_city_tray_tap_wins_over_marker_projected_behind_it(album_page):
    page,_,_=album_page
    city=page.locator('[data-photo-album]:visible').filter(has_text='承德')
    box=city.bounding_box()
    scene=page.locator('.place-journey-scene').bounding_box()
    point={'x':box['x']+box['width']/2,'y':box['y']+box['height']/2}
    key=city.get_attribute('data-photo-album')
    # Feed a pin behind the chip through real Cesium postRender positioning.
    page.evaluate('''point => {
      Cesium.SceneTransforms.worldToWindowCoordinates=()=>new Cesium.Cartesian2(point.x,point.y);
      window.__mapViewer.scene.requestRender();
    }''',{'x':point['x']-scene['x'],'y':point['y']-scene['y']})
    page.wait_for_function('''([x,y]) => {
      const box=document.querySelector('[data-photo-marker]').getBoundingClientRect();
      return Math.abs(box.x+22-x)<1 && Math.abs(box.y+22-y)<1;
    }''',arg=[point['x'],point['y']])
    hit=page.evaluate('''([x,y]) => {
      const button=document.elementFromPoint(x,y).closest('[data-photo-album], [data-photo-marker]');
      return {kind:button?.dataset.photoAlbum ? 'album':'marker',key:button?.dataset.photoAlbum || button?.dataset.photoMarker};
    }''',[point['x'],point['y']])
    page.touchscreen.tap(point['x'],point['y'])
    dialog=page.get_by_role('dialog')
    expect(dialog).to_be_visible()
    actual={'hit':hit,'opened':dialog.locator('h2').inner_text()}
    assert actual=={'hit':{'kind':'album','key':key},'opened':'承德'},actual
    assert dialog.locator('figcaption a').all_text_contents()==[f'承德 fixture {i}' for i in range(3)]


def test_workspace_toggle_and_album_back_preserve_project_route(album_page):
    page,_,_=album_page
    url=page.url
    page.evaluate("history.replaceState({...history.state,fixtureRoute:'phone-map'},'',location.href)")
    page.locator('[data-action="toggle-workspace"]').tap()
    expect(page.locator('#workspace-detail')).to_have_class('workspace-detail is-collapsed')
    expect(page.locator('[data-photo-album]:visible')).to_have_count(0)
    assert page.url==url
    page.locator('[data-action="toggle-workspace"]').tap()
    expect(page.locator('.place-journey-scene.is-cesium-map')).to_be_visible()
    expect(page.locator('[data-photo-album]:visible')).to_have_count(3)
    page.locator('[data-photo-album]:visible').filter(has_text='承德').tap()
    expect(page.get_by_role('dialog')).to_be_visible()
    assert page.evaluate('history.state.fixtureRoute')=='phone-map'
    assert page.url==url
    page.go_back()
    expect(page.get_by_role('dialog')).not_to_be_visible()
    expect(page.locator('[data-photo-album]:visible')).to_have_count(3)
    assert page.evaluate('history.state.fixtureRoute')=='phone-map'
    assert page.url==url
    expect(page.locator('#chat-input')).to_be_enabled()


def test_album_back_forward_preserves_a_pending_chat_reply(album_page):
    page, _, _ = album_page
    interview = page.url
    page.evaluate("""()=>{const nativeFetch=window.fetch;window.fixtureRecoveries=0;window.fixtureAlbumPops=0;
      addEventListener('popstate',()=>{window.fixtureAlbumPops++});
      window.fetch=(url,options)=>{
        if(String(url).endsWith('/agent/config')) window.fixtureRecoveries++;
        if(String(url).endsWith('/memory-sessions')) return Promise.resolve(new Response('{}',{status:403}));
        if(!String(url).endsWith('/agent/turn')) return nativeFetch(url,options);
        window.fixtureReplySignal=options.signal;
        return Promise.resolve(new Response(new ReadableStream({start(controller){window.fixtureReplyController=controller;
          controller.enqueue(new TextEncoder().encode(JSON.stringify({type:'text_delta',text:'Synthetic pending album reply.'})+'\\n'));
        }}),{headers:{'Content-Type':'application/x-ndjson'}}));
      };
    }""")
    page.locator('#chat-input').fill('Synthetic album navigation memory.')
    page.locator('#chat-form button[type="submit"]').click()
    expect(page.get_by_text('Synthetic pending album reply.', exact=True)).to_be_visible()
    page.locator('.map-photo-album:visible').first.click()
    dialog = page.locator('.map-photo-album-viewer')
    expect(dialog).to_be_visible()
    page.go_back()
    page.wait_for_function('fixtureAlbumPops === 1')
    expect(dialog).not_to_be_visible()
    assert page.evaluate('fixtureReplySignal.aborted') is False
    assert page.evaluate('fixtureRecoveries') == 0
    expect(page).to_have_url(interview)
    page.evaluate("fixtureReplyController.enqueue(new TextEncoder().encode(JSON.stringify({type:'text_delta',text:' Still replying.'})+'\\n'))")
    expect(page.get_by_text('Synthetic pending album reply. Still replying.', exact=True)).to_be_visible()
    page.go_forward()
    page.wait_for_function('fixtureAlbumPops === 2')
    expect(dialog).to_be_visible()
    assert page.evaluate('fixtureReplySignal.aborted') is False
    assert page.evaluate('fixtureRecoveries') == 0
    page.evaluate("""()=>{fixtureReplyController.enqueue(new TextEncoder().encode(JSON.stringify({type:'result',data:{
      reply:'Synthetic pending album reply. Still replying.',conversation_saved:true}})+'\\n'));fixtureReplyController.close();}""")
    expect(page.locator('#chat-form button[type="submit"]')).to_be_enabled()
    dialog.locator('[data-close-photo-album]').click()
    expect(dialog).not_to_be_visible()
    expect(page.get_by_text('Synthetic album navigation memory.', exact=True)).to_be_visible()
    expect(page.get_by_text('Synthetic pending album reply. Still replying.', exact=True)).to_be_visible()
