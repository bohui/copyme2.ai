"""Synthetic mobile map albums; all API, photo and imagery responses are fixtures."""
import json
import os
import base64
import re
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright

pytestmark = pytest.mark.skipif(not os.getenv('MEMOIR_BROWSER_URL'), reason='Requires isolated frontend')
OUTPUT = Path(__file__).resolve().parents[1] / 'output/phone-map-albums'


@pytest.mark.parametrize('album_page', ['overlap-events'], indirect=True)
def test_cards_sort_by_first_event_and_follow_the_100_km_visible_area(album_page):
    page, _, _ = album_page
    page.set_viewport_size({'width': 1440, 'height': 960})
    page.locator('[data-memory-overview]').click()
    cards = page.locator('.map-memory-cards .map-memory-card.is-city')
    expect(cards).to_have_count(2, timeout=15000)
    assert cards.locator('.map-memory-summary').all_text_contents() == ['承德', '悉尼']
    for width in (1440, 390):
        page.set_viewport_size({'width': width, 'height': 960})
        for latitude, show in ((0, False), (41.69, True), (42.14, False), (40.97, True)):
            page.evaluate('''latitude=>{
              const viewer=window.__mapViewer;viewer.camera.cancelFlight();
              viewer.camera.setView({destination:Cesium.Cartesian3.fromDegrees(117.93,latitude,6000)});
              viewer.scene.requestRender();
            }''', latitude)
            if show:
                expect(page.locator('.map-memory-card:visible')).to_have_count(3, timeout=5000)
                expect(page.locator('[data-photo-album]:visible')).to_have_count(3)
                expect(page.locator('.map-photo-album-layer')).not_to_contain_text('悉尼')
            else:
                expect(page.locator('.map-memory-card:visible')).to_have_count(0, timeout=5000)
                expect(page.locator('[data-photo-album]:visible')).to_have_count(0)


@pytest.mark.parametrize('album_page', ['events'], indirect=True)
def test_reopening_restores_the_active_city_and_city_zoom_keeps_scaled_footprints(album_page):
    page, _, _ = album_page
    page.set_viewport_size({'width': 1440, 'height': 960})
    page.evaluate('''() => {
      const proto=CanvasRenderingContext2D.prototype,draw=proto.drawImage,clear=proto.clearRect;
      proto.clearRect=function(...args){if(this.canvas.matches('.map-memory-trail'))window.trailStamps=[];
        return clear.apply(this,args);};
      proto.drawImage=function(...args){if(this.canvas.matches('.map-memory-trail')&&args[0]?.src?.endsWith('/map-footprints.svg'))
        (window.trailStamps??=[]).push(args[3]);return draw.apply(this,args);};
      window.__mapViewer.camera.setView({destination:Cesium.Cartesian3.fromDegrees(151.2,-33.86,2500)});
      window.__mapViewer.scene.requestRender();
    }''')
    expect(page.locator('.map-memory-cards [data-memory-explore="move"]')).to_be_visible()
    page.locator('.workspace-media-map-header .workspace-toggle').click()
    expect(page.locator('.workspace-detail.is-collapsed')).to_be_visible()
    page.locator('.workspace-detail.is-collapsed .workspace-toggle').click()
    expect(page.locator('.place-journey-scene.is-cesium-map')).to_be_visible(timeout=30000)
    expect(page.locator('.map-memory-cards [data-memory-explore="move"]')).to_be_visible()
    expect(page.locator('.map-memory-cards .map-memory-card')).to_have_count(1)
    expect(page.locator('.map-photo-album-layer')).not_to_contain_text('承德')
    assert page.evaluate('window.__mapViewer.camera.positionCartographic.height') < 40000
    for longitude, latitude, size in [(151.2, -33.86, 16), (117.93, 40.97, 10)]:
        page.evaluate('''([longitude,latitude]) => {
          window.__mapViewer.camera.setView({destination:Cesium.Cartesian3.fromDegrees(longitude,latitude,2500)});
          window.__mapViewer.scene.requestRender();
        }''', [longitude, latitude])
        page.wait_for_function('(size)=>window.trailStamps?.length>0&&trailStamps.every(value=>value===size)', arg=size, timeout=5000)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(OUTPUT / 'reopened-city-footprints.png'))


@pytest.fixture
def album_page(request):
    mode = getattr(request, 'param', 'saved')
    state_mode = mode.removeprefix('unresolved-')
    base = os.environ['MEMOIR_BROWSER_URL']
    city = dict(place='承德', hierarchy=['Earth', '中国', '河北', '承德'], granularity='city',
                latitude=40.97, longitude=117.93, period='1980s', revision=1, status='active', schema_version=1)
    places = [city, dict(city, place='双桥区', hierarchy=city['hierarchy']+['双桥区'], granularity='suburb', latitude=40.94, longitude=117.96, revision=2),
              dict(city, place='大石庙镇', hierarchy=city['hierarchy']+['大石庙镇'], granularity='suburb', latitude=40.9401, longitude=117.9601, revision=3)]
    if mode in ('events','estimated-events','overlap-events'):
        places.append(dict(city,place='悉尼',hierarchy=['Earth','澳大利亚','悉尼'],latitude=-33.86,longitude=151.2,revision=4))
    if mode == 'current':
        places = [dict(city, period='')]
    for i, place in enumerate(places):
        if mode.startswith('unresolved'):
            place['map_pin']=None
        date = '2026-08-01' if mode == 'current' else '1983'
        place.update(photo_search_period=place['period'], photo_search_policy='place-source-rights-v13',
                     photo_search_place=place['place']+', 承德' if place['granularity']=='suburb' else place['place'],
                     photo_search_complete=state_mode not in ('loading', 'error','current'), photo_search_at=1,
                     photo_search_latitude=place['latitude'], photo_search_longitude=place['longitude'],
                     pictures=[] if state_mode in ('empty','loading','error','current') else [dict(asset_id=f'{i}-{j}', title=f'{place["place"]} fixture {j}',
                       image_url=f'/static/album-fixture-{i}-{j}.svg', source_url='https://archive.example/photo',
                       attribution='Synthetic test archive', date_expression=date, latitude=place['latitude'],
                       longitude=place['longitude'], allowed_actions={'embed':True}) for j in range(3)])
    if mode == 'unmapped':
        for place in places:
            place.pop('latitude')
            place.pop('longitude')
    profile = {'name':'Fixture', 'preferred_language':'zh-CN', 'memory_places':places}
    if mode in ('estimated-events','overlap-events'):profile['birth_year']=1983
    calls, errors = [], []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width':390,'height':844},
            reduced_motion='no-preference' if mode=='slow-flight' else 'reduce', is_mobile=True, has_touch=True)
        context.add_cookies([{'name':'copyme2_ui_locale','value':'zh-CN','url':base}, {'name':'copyme2_ui_locale_source','value':'fixed','url':base}])
        def boundary(route):
            if route.request.url.startswith(base) or any(host in route.request.url for host in ('cesium.com/', 'fonts.googleapis.com/', 'fonts.gstatic.com/')):
                route.continue_()
            else:
                route.abort()
        context.route('**/*', boundary)
        def cesium(route):
            if mode == 'script-error':
                return route.abort()
            response = route.fetch()
            imagery = '''\nCesium.Google2DImageryProvider.fromUrl=async()=>new Cesium.GridImageryProvider();
              const OriginalViewer=Cesium.Viewer;window.Cesium={...Cesium,Viewer:new Proxy(OriginalViewer,{construct(target,args){
                const viewer=Reflect.construct(target,args);window.__mapViewer=viewer;
                viewer.scene.renderError.addEventListener((scene,error)=>console.error('Map render failed: '+error));
                return viewer;}})};'''
            if mode == 'tile-error':
                imagery += '''Cesium.Google2DImageryProvider.fromUrl=async()=>{const provider=new Cesium.GridImageryProvider();
                  provider.requestImage=()=>Promise.reject(new Error('Synthetic tile rejection'));return provider;};'''
            if mode == 'slow-flight':
                imagery += '''window.holdMapTiles=true;window.pendingMapTiles=[];window.mapFlights=[];window.finishedMapFlights=0;
                  window.releaseMapTiles=()=>{window.holdMapTiles=false;pendingMapTiles.splice(0).forEach(resolve=>resolve());};
                  Cesium.Google2DImageryProvider.fromUrl=async()=>{const provider=new Cesium.GridImageryProvider(),request=provider.requestImage.bind(provider);
                    provider.requestImage=(...args)=>{const image=request(...args);return window.holdMapTiles
                      ? new Promise(resolve=>pendingMapTiles.push(()=>resolve(image))) : image;};return provider;};
                  const ViewerWithFlightTrace=Cesium.Viewer;
                  window.Cesium={...Cesium,Viewer:new Proxy(ViewerWithFlightTrace,{construct(target,args){
                    const viewer=Reflect.construct(target,args),fly=viewer.camera.flyTo.bind(viewer.camera);
                    viewer.camera.flyTo=options=>{mapFlights.push({duration:options.duration,
                      height:Cesium.Cartographic.fromCartesian(options.destination).height,
                      loaded:viewer.scene.globe.tilesLoaded,layers:viewer.imageryLayers.length});
                      window.holdMapTiles=true;return fly({...options,complete:()=>{window.finishedMapFlights++;options.complete?.();}});};
                    return viewer;}})};'''
            route.fulfill(response=response, body=response.text()+imagery)
        context.route('**/Build/Cesium/Cesium.js', cesium)
        context.route('**/static/album-fixture-*.svg', lambda r:r.fulfill(content_type='image/svg+xml',body='<svg xmlns="http://www.w3.org/2000/svg" width="320" height="220"><rect width="320" height="220" fill="#c4d8d2"/><path d="M0 180L110 70L230 180L320 100V220H0" fill="#397465"/><rect x="130" y="130" width="80" height="80" fill="#eee1bb"/><path d="M120 140L170 100L220 140" fill="#a65c43"/></svg>'))
        def api(route):
            path = route.request.url.split('/api/v1/memoir')[-1].split('?')[0]
            data = {}
            if path == '/agent/config': data = {'auth_mode':'test','google_maps_browser_api_key':'' if mode == 'missing-key' else 'synthetic-key'}
            elif path in ('/agent/profile','/user/profile'):
                if route.request.method == 'PATCH': profile.update(route.request.post_data_json)
                data = profile
            elif path == '/projects/album-project':
                if route.request.method == 'PATCH': profile.update(route.request.post_data_json.get('profile',{}))
                data = {'id':'album-project','revision':1,'profile':profile,'mode':'self','workspace_unlocked':False}
            elif path == '/story/state': data = {'family_features_enabled':False,'recall_status':{'payment_required':False}}
            elif path == '/story/readiness':
                data = {'stages':{'baby':{'percent':30,'color':'amber','word_equivalents':300},
                                  'childhood':{'percent':10,'color':'red','word_equivalents':100},
                                  'midlife':{'percent':50,'color':'green','word_equivalents':1000}}}
            elif path == '/story/map-events' and mode in ('events','estimated-events','overlap-events'):
                events=[dict(id=id,revision=1,kind='event',status='active',life_stage=stage,title=title,
                    temporal={'expression':f'Age {age}','precision':'age'},
                    places=[{'role':'setting','status':'supported','place':place}])
                    for id,age,place,stage,title in [('return',40,places[2],'midlife','Return home'),
                        ('school',6,places[1],'childhood','First school'),('birth',0,places[0],'baby','Birth'),
                        ('move',20,places[-1],'young_adulthood','Move to Sydney')]]
                if mode in ('estimated-events','overlap-events'):
                    for event in events:
                        if event['id']=='birth':
                            event.update(title='Born in Chengde in April 1983',
                                temporal=dict(expression='1983年4月',precision='month',year_start=1983),yearConfidenceScore=1)
                        else:
                            start,end,confidence={'school':(1988,1990,.6),'move':(2011,2026,.8),'return':(2023,2023,.7)}[event['id']]
                            event.update(temporal=None,yearConfidenceScore=confidence,temporal_estimate=dict(
                                year_start=start,year_end=end,age_start=start-1983,age_end=end-1983,confidence=confidence,
                                rationale='Original duration and narrator birth anchors.'))
                if mode=='overlap-events':
                    residence=next(event for event in events if event['id']=='move')
                    residence.update(life_stage='unplaced',temporal_anchor='present',yearConfidenceScore=.3,
                        temporal_estimate=dict(year_start=1983,year_end=2026,age_start=0,age_end=43,confidence=.3,
                            rationale='The residence start is unknown within this broad interval.'))
                data={'project_id':'album-project','events':events,'policy_epoch':1,'source_revision':1,'event_revision':1,'complete':True}
            elif path == '/story/map-photos':
                data={'project_id':'album-project','photos':[dict(photo_id='upload:aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
                    kind='private_upload',title='My school photo',event_ids=['school'])] if mode in ('events','estimated-events','overlap-events') else []}
            elif path == '/agent/projects/album-project/photos/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/content':
                assert route.request.headers.get('authorization','').startswith('Bearer ')
                return route.fulfill(content_type='image/png',body=base64.b64decode(
                    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a9l8AAAAASUVORK5CYII='))
            elif path == '/user/conversations': data = {'items':[]}
            elif path.endswith('/journey'): data = {'active_session':None}
            elif path.endswith('/place-photos') or (path.startswith('/agent/places/') and path.endswith('/photos')):
                calls.append(route.request.url)
                data = {'items':[], 'status':'UNAVAILABLE' if state_mode=='error' else 'NO_MATCH', 'searching':False}
            return route.fulfill(json=data)
        context.route('**/api/v1/memoir/**', api)
        context.add_init_script("localStorage.setItem('memory-spark-project','album-project');sessionStorage.setItem('memory-spark-chat-history:album-project',JSON.stringify([{id:'opening',role:'assistant',text:'Synthetic memory recall conversation'}]));")
        if state_mode == 'loading':
            arriving = dict(asset_id='arriving',title='Arriving dated reference',image_url='/static/album-fixture-arriving.svg',
                source_url='https://archive.example/photo',attribution='Synthetic test archive',date_expression='1986',
                latitude=places[-1]['latitude'],longitude=places[-1]['longitude'],allowed_actions={'embed':True})
            context.add_init_script(r'''const originalFetch=window.fetch;window.fetch=(url,options)=>/\/(?:place-photos|photos)\?/.test(String(url))
              ? new Promise(resolve=>{window.finishPhotoSearch=()=>resolve(new Response(JSON.stringify({items:'''+json.dumps([arriving])+''',status:'PARTIAL',searching:false}),{headers:{'Content-Type':'application/json'}}));})
              : originalFetch(url,options);''')
        page = context.new_page()
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.on('console',lambda message:errors.append(message.text) if message.text.startswith('Map render failed:') else None)
        page.goto(base+'/memoir/interview/album-project',wait_until='networkidle')
        expect(page.locator('#chat-input')).to_be_enabled(timeout=30000)
        if mode == 'unmapped':
            expect(page.locator('.story-shell.conversation-only')).to_be_visible(timeout=30000)
        elif mode in ('script-error', 'tile-error', 'missing-key'):
            expect(page.locator('[data-map-retry]')).to_be_visible(timeout=30000)
        elif mode == 'slow-flight':
            page.wait_for_function('window.pendingMapTiles?.length>0',timeout=30000)
        else:
            expect(page.locator('.place-journey-scene.is-cesium-map')).to_be_visible(timeout=30000)
        yield page, calls, errors
        assert not errors, errors
        browser.close()


@pytest.mark.parametrize('album_page', ['slow-flight'], indirect=True)
@pytest.mark.parametrize('width', [390, 1440])
def test_opening_flight_waits_for_imagery_at_each_zoom_without_an_extra_arrival_zoom(album_page, width):
    page, _, _ = album_page
    page.set_viewport_size({'width':width,'height':960})
    assert page.evaluate('mapFlights.length') == 0
    assert not page.evaluate('__mapViewer.scene.screenSpaceCameraController.enableInputs')
    for stage in range(1, 4):
        page.evaluate('releaseMapTiles()')
        page.wait_for_function('(stage)=>mapFlights.length===stage',arg=stage,timeout=20000)
        page.wait_for_function('(stage)=>finishedMapFlights===stage',arg=stage,timeout=15000)
        assert page.evaluate('mapFlights.length') == stage
        assert not page.locator('.place-journey-scene').evaluate("element=>element.classList.contains('is-cesium-map')")
        page.wait_for_function('pendingMapTiles.length>0',timeout=5000)
    page.evaluate('releaseMapTiles()')
    expect(page.locator('.place-journey-scene.is-cesium-map')).to_be_visible(timeout=15000)
    page.wait_for_timeout(1300)
    flights = page.evaluate('mapFlights')
    assert len(flights) == 3, 'The event overlay must not start a second arrival zoom'
    assert all(flight['loaded'] and flight['layers'] == 1 and flight['duration'] >= 2.8 for flight in flights)
    assert flights[0]['height'] > flights[1]['height'] > flights[2]['height']
    assert page.evaluate('__mapViewer.scene.globe.tilesLoaded')
    assert page.evaluate('__mapViewer.scene.screenSpaceCameraController.enableInputs')
    OUTPUT.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(OUTPUT/f'loaded-flight-{width}.png'))


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
    expect(page.locator('.life-stage-navigator, .life-stage-tabs')).to_have_count(0)
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
def test_empty_search_states_stay_hidden_until_photos_arrive(album_page, request):
    page,calls,_=album_page
    mode=request.node.callspec.params['album_page'].removeprefix('unresolved-')
    expect(page.locator('.map-photo-album-layer')).not_to_be_visible()
    expect(page.locator('[data-photo-album], [data-photo-marker], .map-album-placeholder')).to_have_count(0)
    if mode=='error':
        assert calls
    elif mode=='loading':
        page.wait_for_function("typeof finishPhotoSearch === 'function'")
        page.evaluate('finishPhotoSearch()')
        album=page.locator('[data-photo-album]:visible')
        expect(album).to_have_count(1)
        expect(album.locator('img')).to_have_count(1)
        album.tap()
        dialog=page.get_by_role('dialog')
        expect(dialog).to_be_visible()
        expect(dialog.locator('figure')).to_have_count(1)
        assert '1986' in dialog.inner_text()
        dialog.locator('[data-close-photo-album]').click()
        expect(dialog).not_to_be_visible()
        expect(album).to_be_focused()
    elif mode=='current':
        assert calls and all('period=&' in url or url.endswith('period=') for url in calls), calls


def test_desktop_floating_albums_and_phone_resize_preserve_map(album_page):
    page,_,_=album_page
    page.set_viewport_size({'width':1440,'height':960})
    page.evaluate('''() => {
      window.__mapViewer.camera.setView({destination:Cesium.Cartesian3.fromDegrees(117.93,40.97,40000)});
      window.__mapViewer.scene.requestRender();
    }''')
    expect(page.locator('.workspace-media-gallery')).to_have_count(0)
    expect(page.locator('.workspace-media-map-header h2')).to_have_count(0)
    expect(page.locator('.map-photo-album-layer.is-desktop [data-photo-album]:visible')).to_have_count(1)
    scene=page.locator('.place-journey-scene').bounding_box()
    overview=page.locator('.workspace-media-overview').bounding_box()
    assert abs(scene['width']-overview['width'])<2 and abs(scene['height']-overview['height'])<2
    page.locator('[data-photo-album]:visible').first.click()
    expect(page.get_by_role('dialog')).to_be_visible()
    expect(page.get_by_role('dialog').locator('figure')).to_have_count(9)
    page.keyboard.press('Escape')
    expect(page.get_by_role('dialog')).not_to_be_visible()
    page.screenshot(path=str(OUTPUT/'after-desktop.png'))
    page.evaluate('() => {window.__previousMapViewer=window.__mapViewer;}')
    for width,height in [(320,568),(430,932),(760,580),(390,500)]:
        page.set_viewport_size({'width':width,'height':height})
        expect(page.locator('[data-photo-album]:visible').first).to_be_visible()
        assert page.evaluate('window.__previousMapViewer===window.__mapViewer')
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        scene=page.locator('.place-journey-scene').bounding_box()
        assert scene['height']>=100,scene
        assert page.locator('#chat-input').bounding_box()['y']<height


@pytest.mark.parametrize('album_page',['empty','error','loading'],indirect=True)
def test_desktop_hides_photo_lane_until_photos_arrive(album_page, request):
    page,_,_=album_page
    loading = request.node.callspec.params['album_page'] == 'loading'
    if loading:
        page.wait_for_function("typeof finishPhotoSearch === 'function'")
    for width in (1440, 823):
        page.set_viewport_size({'width':width,'height':960})
        expect(page.locator('.workspace-media-gallery')).to_have_count(0)
        expect(page.locator('.map-photo-album-layer')).not_to_be_visible()
        expect(page.locator('[data-photo-album], [data-photo-marker], .map-album-placeholder')).to_have_count(0)
        expect(page.locator('.workspace-media-overview.no-gallery')).to_be_visible()
        overview = page.locator('.workspace-media-overview').bounding_box()
        map_panel = page.locator('.workspace-media-map').bounding_box()
        assert map_panel['width'] > overview['width'] * .9
    if loading:
        page.evaluate('finishPhotoSearch()')
        expect(page.locator('.workspace-media-gallery')).to_have_count(0)
        expect(page.locator('.map-photo-album-layer.is-desktop img')).to_have_count(1)
        expect(page.locator('.workspace-media-overview.no-gallery')).to_be_visible()


@pytest.mark.parametrize('album_page',['events'],indirect=True)
def test_desktop_event_chronology_photo_latitude_and_personal_photos_on_zoom(album_page):
    page,_,_=album_page
    page.set_viewport_size({'width':1440,'height':960})
    cards=page.locator('.map-memory-layer.is-desktop .map-memory-cards > .map-memory-anchor > .map-memory-card')
    expect(cards).to_have_count(2)
    assert ['Birth','Move to Sydney']==[
        card.locator('.map-memory-summary').inner_text() for card in cards.all()]
    expect(cards.first.locator('.map-memory-avatar img')).to_have_count(3)
    expect(page.locator('.map-memory-confidence, .map-memory-avatar small')).to_have_count(0)
    cards.first.locator('[data-map-memory]').click()
    children=page.locator('.map-memory-city-events .map-memory-card')
    expect(children).to_have_count(3)
    assert ['Birth','First school','Return home']==[card.locator('.map-memory-summary').inner_text() for card in children.all()]
    expect(cards.first.locator('[data-map-memory]')).to_have_attribute('aria-expanded','true')
    expect(children.nth(1).locator('.map-memory-avatar img')).to_have_count(1)
    albums=page.locator('.map-photo-album-layer.is-desktop .map-album-overflow [data-photo-album]')
    expect(albums).to_have_count(2)
    assert [album.locator('.map-album-place').inner_text() for album in albums.all()]==['承德','悉尼']
    overview=page.locator('[data-memory-overview]').bounding_box()
    collapse=page.locator('.workspace-media-map-header .workspace-toggle').bounding_box()
    scene=page.locator('.place-journey-scene').bounding_box()
    assert overview['x']<scene['x']+30 and collapse['x']>scene['x']+scene['width']-65
    albums.first.click()
    dialog=page.locator('.map-photo-album-viewer')
    expect(dialog).to_be_visible()
    figures=dialog.locator('figure')
    assert figures.first.get_attribute('data-photo-kind')=='private_upload'
    private=figures.first.locator('[data-private-response-photo]')
    expect(private).to_be_visible()
    assert private.get_attribute('src').startswith('blob:')
    private.click()
    expect(page.locator('.response-photo-viewer')).to_be_visible()
    page.locator('.response-photo-viewer button').click()
    dialog.locator('[data-close-photo-album]').click()
    expect(dialog).not_to_be_visible()
    # Expanding a city leaves the overview in place; zooming filters both lanes.
    expect(albums).to_have_count(2)
    page.locator('[data-memory-city]').click()
    expect(cards).to_have_count(3)
    expect(albums).to_have_count(3)
    assert [album.locator('.map-album-place').inner_text() for album in albums.all()]==['承德','大石庙镇','双桥区']
    assert ['Birth','First school','Return home']==[card.locator('.map-memory-summary').inner_text() for card in cards.all()]
    cards.nth(1).locator('[data-map-memory]').click()
    expect(page.locator('.map-memory-detail')).to_have_count(0)
    expect(cards.nth(1).locator('[data-memory-explore="school"]')).to_be_visible()
    school=albums.filter(has_text='双桥区')
    expect(school.locator('.map-album-stack img').last).to_have_attribute('data-private-response-photo','aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa')
    school.click()
    expect(dialog.locator('figure').first).to_have_attribute('data-photo-kind','private_upload')
    dialog.locator('[data-close-photo-album]').click()
    page.evaluate('''() => {window.__mapViewer.camera.setView({destination:Cesium.Cartesian3.fromDegrees(151.2,-33.86,2500)});
      window.__mapViewer.scene.requestRender();}''')
    expect(cards).to_have_count(1)
    expect(cards.first.locator('.map-memory-summary')).to_have_text('Move to Sydney')
    expect(albums).to_have_count(1)
    expect(albums.first.locator('.map-album-place')).to_have_text('悉尼')
    page.locator('[data-memory-overview]').click()
    expect(cards).to_have_count(2)
    expect(albums).to_have_count(2)
    OUTPUT.mkdir(parents=True,exist_ok=True)
    page.screenshot(path=str(OUTPUT/'after-desktop-events.png'))
    page.set_viewport_size({'width':1440,'height':640})
    cards.first.locator('[data-map-memory]').click()
    event_list=page.locator('.map-memory-cards')
    event_list.evaluate('(element) => {element.scrollTop=100;}')
    assert event_list.evaluate('(element) => element.scrollTop')==100
    albums.last.click()
    expect(dialog).to_be_visible()
    dialog.locator('[data-close-photo-album]').click()
    expect(dialog).not_to_be_visible()
    assert event_list.evaluate('(element) => element.scrollTop')==100
    page.locator('.workspace-media-map-header .workspace-toggle').click()
    expect(page.locator('.workspace-detail.is-collapsed')).to_be_visible()
    page.locator('.workspace-detail.is-collapsed .workspace-toggle').click()
    expect(page.locator('.place-journey-scene')).to_be_visible()
    expect(page.locator('.workspace-media-map-header h2')).to_have_count(0)
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')


@pytest.mark.parametrize('album_page',['events'],indirect=True)
def test_phone_city_expansion_and_zoom_keep_only_local_events_and_photos(album_page):
    page,_,_=album_page
    cities=page.locator('.map-memory-cards .map-memory-card.is-city')
    expect(cities).to_have_count(2)
    cities.first.locator('[data-map-memory]').tap()
    expect(page.locator('.map-memory-city-events [data-map-memory]')).to_have_count(3)
    expect(cities.first.locator('[data-map-memory]')).to_have_attribute('aria-expanded','true')
    page.locator('[data-memory-city]').tap()
    expect(cities).to_have_count(0)
    expect(page.locator('.map-memory-cards [data-map-memory]')).to_have_count(3)
    expect(page.locator('.map-memory-cards')).not_to_contain_text('Move to Sydney')
    expect(page.locator('[data-photo-album]:visible')).to_have_count(3)
    expect(page.locator('.map-photo-album-layer')).not_to_contain_text('悉尼')
    OUTPUT.mkdir(parents=True,exist_ok=True)
    page.screenshot(path=str(OUTPUT/'after-phone-events.png'))
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')


@pytest.mark.parametrize('album_page',['estimated-events'],indirect=True)
def test_estimated_years_and_ages_stay_visible_without_confidence_scores_in_city_events(album_page):
    page,_,_=album_page
    page.set_viewport_size({'width':1440,'height':960})
    cities=page.locator('.map-memory-cards .map-memory-card.is-city')
    expect(cities).to_have_count(2)
    cities.first.locator('[data-map-memory]').click()
    school=page.locator('.map-memory-city-events .map-memory-card').filter(has_text='First school')
    expect(school.locator('.map-memory-date')).to_have_text('约1988–1990年 · 约5–7岁')
    expect(school.locator('.map-memory-confidence, .map-memory-avatar small')).to_have_count(0)
    expect(school.locator('.map-memory-avatar img')).to_have_count(1)
    OUTPUT.mkdir(parents=True,exist_ok=True)
    page.screenshot(path=str(OUTPUT/'after-desktop-estimated-events.png'))
    page.locator('[data-memory-city]').click()
    expect(page.locator('.map-memory-cards [data-map-memory]')).to_have_count(3)
    expect(page.locator('.map-memory-cards')).not_to_contain_text('Move to Sydney')


@pytest.mark.parametrize('album_page',['estimated-events'],indirect=True)
@pytest.mark.parametrize('width',[390,1440],ids=['phone','desktop'])
def test_one_visible_city_keeps_inline_event_cards_through_zoom_without_popups(album_page,width):
    page,_,_=album_page
    page.set_viewport_size({'width':width,'height':960})
    cards=page.locator('.map-memory-cards .map-memory-card')
    for height in [80000,8000,60000]:
        page.evaluate('''height => {
          window.__mapViewer.camera.setView({destination:Cesium.Cartesian3.fromDegrees(117.95,40.95,height)});
          window.__mapViewer.scene.requestRender();
        }''',height)
        expect(cards).to_have_count(3)
        expect(page.locator('.map-memory-cards')).not_to_contain_text('Move to Sydney')
        expect(page.locator('.map-memory-cards')).not_to_contain_text('承德')
        expect(page.locator('.map-memory-cards')).not_to_contain_text('婴儿时期')
    expect(page.locator('.life-stage-navigator, .life-stage-tabs, .map-memory-detail')).to_have_count(0)
    birth=cards.filter(has_text='Born in Chengde in April 1983')
    expect(birth).to_have_count(1)
    assert birth.locator('.map-memory-summary').evaluate('(node) => parseFloat(getComputedStyle(node).fontSize)')>=18
    expect(birth.locator('.map-memory-avatar')).to_have_attribute('style','--readiness:30%')
    expect(birth.locator('.map-memory-avatar')).to_have_class('map-memory-avatar readiness-amber')
    expect(birth.locator('.map-memory-avatar')).to_have_css('background-image',re.compile('conic-gradient'))
    birth.locator('[data-map-memory]').click()
    page.wait_for_function('''() => {const viewer=window.__mapViewer;
      return (viewer.scene.mode===Cesium.SceneMode.SCENE2D
        ? viewer.camera.frustum.right-viewer.camera.frustum.left : viewer.camera.positionCartographic.height)<18000;}''')
    expect(page.locator('.map-memory-detail')).to_have_count(0)
    expect(cards).to_have_count(3)
    OUTPUT.mkdir(parents=True,exist_ok=True)
    page.screenshot(path=str(OUTPUT/f'inline-event-card-{width}.png'))
    birth.locator('[data-memory-explore="birth"]').click()
    expect(page.locator('.workspace-memory-focus')).to_contain_text('Born in Chengde in April 1983')
    expect(page.locator('#chat-input')).to_be_focused()
    expect(page.locator('.map-memory-detail')).to_have_count(0)
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')


@pytest.mark.parametrize('album_page',['unmapped','script-error','tile-error','missing-key'],indirect=True)
def test_missing_map_stays_hidden_and_failed_map_keeps_retry(album_page,request):
    page,_,_=album_page
    page.set_viewport_size({'width':1440,'height':960})
    if request.node.callspec.params['album_page']=='unmapped':
        expect(page.locator('.story-shell.conversation-only')).to_be_visible()
        expect(page.locator('#workspace-detail')).to_have_count(0)
        expect(page.locator('.life-stage-navigator')).to_have_count(0)
    else:
        expect(page.locator('.workspace-media-map')).to_be_visible()
        expect(page.locator('[data-map-retry]')).to_be_visible()
        expect(page.locator('.workspace-media-gallery')).to_have_count(0)
    expect(page.locator('#chat-input')).to_be_enabled()


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
def test_no_pin_groups_hide_empty_albums(album_page,request):
    page,calls,_=album_page
    expect(page.locator('.map-photo-album-layer')).not_to_be_visible()
    expect(page.locator('[data-photo-album], [data-photo-marker], .map-album-placeholder')).to_have_count(0)
    assert page.evaluate('window.__mapViewer.entities.values.length')==0
    if request.node.callspec.params['album_page']=='unresolved-error':
        assert calls


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
