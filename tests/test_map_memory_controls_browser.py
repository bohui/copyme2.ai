"""Real map renderer and styles, with camera readiness controlled and no network."""
from pathlib import Path
from urllib.parse import urlsplit
import mimetypes

import pytest
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'output/playwright'
HTML = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<link rel="stylesheet" href="/static/styles.css">
<body style="margin:0"><main class="story-shell" style="display:flex;height:100vh;margin:0;border:0;border-radius:0">
<div id="chat-scroll" hidden></div><section class="workspace-media-overview">
<div class="workspace-media-map"><div class="workspace-media-header workspace-media-map-header">
<button data-all-places>完整旅程</button><button class="workspace-toggle" aria-label="Collapse">&gt;</button>
</div><div class="place-journey-card"><div class="place-journey-scene" style="background:#173f45"></div></div>
</div></section></main><script type="module">
import {createMapMemoryEvents} from '/client/memoir/map-memory-events.mjs';
import {groupPlaces} from '/client/memoir/places.mjs';
const city={place:'Chengde',granularity:'city',hierarchy:['Earth','China','Chengde'],latitude:40.95,longitude:117.96};
const events=[{id:'birth',canonical:true,revision:1,status:'active',kind:'event',life_stage:'baby',title:'Birth',
  temporal:{expression:'1983',precision:'year',year_start:1983},places:[{role:'setting',status:'supported',place:city}]},
  ...['one','two'].map(id=>({id,canonical:true,revision:1,status:'active',kind:'event',title:id,places:[]}))];
const scene=document.querySelector('.place-journey-scene');
let redraw=()=>{};
const viewer={isDestroyed:()=>false,scene:{mode:2,postRender:{addEventListener(callback){redraw=callback;return ()=>{};}}},
  camera:{frustum:{left:-100000,right:100000},flyTo(){}}};
const cesium={SceneMode:{SCENE2D:2},Cartesian3:{fromDegrees:(longitude,latitude)=>({longitude,latitude})},
  SceneTransforms:{worldToWindowCoordinates:()=>({x:scene.clientWidth*.7,y:scene.clientHeight*.6})}};
const map=createMapMemoryEvents({getEvents:()=>events,getGroups:places=>groupPlaces([city,...places.filter(place=>place.place!==city.place)]),getProfile:()=>({birth_year:1983}),
  getScope:()=> 'fixture:'+events[0].revision,getIdentity:()=> 'fixture',getStage:()=> 'all',lifeStageText:stage=>stage,
  getPage:()=>({next_cursor:'fixture-next'}),
  t:(key,values)=>({mapMemoryJourney:'人生足迹',mapMemoryOverview:'完整旅程',mapEventExpand:'展开记忆'}[key]||key)});
map.sync(scene);
window.mapControls={update(patch){Object.assign(events[0],patch);map.sync(scene);},attach(){map.attach(viewer,cesium);},arrive(){scene.classList.add('is-cesium-map');redraw();},
  redraw(){redraw();}};
addEventListener('resize',()=>redraw());
</script></html>'''


@pytest.fixture
def controls_page(request):
    with sync_playwright() as pw:
        if not Path(pw.chromium.executable_path).is_file():
            pytest.skip('Chromium is required for map browser checks')
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1440, 'height': 960})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))

        def serve(route):
            url = urlsplit(route.request.url)
            if url.netloc != 'map-controls.invalid':
                return route.abort()
            if url.path == '/':
                return route.fulfill(content_type='text/html', body=getattr(request, 'param', HTML))
            if url.path.startswith('/static/album-fixture-'):
                return route.fulfill(content_type='image/svg+xml', body='<svg xmlns="http://www.w3.org/2000/svg" width="320" height="220"><rect width="320" height="220" fill="#94bdac"/><path d="M0 180L110 70L230 180L320 100V220H0" fill="#397465"/></svg>')
            for prefix, directory in [('/client/', ROOT / 'apps/web/client'), ('/static/', ROOT / 'apps/web/public'),
                                      ('/messages/', ROOT / 'apps/web/messages')]:
                if url.path.startswith(prefix):
                    path = (directory / url.path.removeprefix(prefix)).resolve()
                    if path.is_relative_to(directory) and path.is_file():
                        content_type = 'text/javascript' if path.suffix in {'.js', '.mjs'} else mimetypes.guess_type(path)[0]
                        return route.fulfill(content_type=content_type or 'application/octet-stream', body=path.read_bytes())
            route.abort()

        page.route('**/*', serve)
        yield page
        assert not errors, errors
        browser.close()


def controls(page):
    return page.evaluate('''() => Object.fromEntries([
      ['overview','.map-memory-toolbar [data-memory-overview]'],['status','.map-memory-status'],
      ['collapse','.workspace-toggle'],['caption','.map-memory-caption']].map(([key,selector])=>{
        const element=document.querySelector(selector);
        if (!element) return [key,null];
        const box=element.getBoundingClientRect();
        return [key,{x:box.x,y:box.y,width:box.width,height:box.height,display:getComputedStyle(element).display}];
      }))''')


@pytest.mark.parametrize('width', [1440, 1024, 390])
def test_map_controls_keep_their_settled_layout_before_and_during_flight(controls_page, width):
    page = controls_page
    page.set_viewport_size({'width': width, 'height': 960})
    page.goto('http://map-controls.invalid/')
    page.wait_for_function("window.mapControls && document.querySelector('.map-memory-status')")
    initial = controls(page)
    page.evaluate('mapControls.attach()')
    flying = controls(page)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(OUTPUT / f'map-controls-{width}-flight.png'))
    page.evaluate('mapControls.arrive()')
    settled = controls(page)
    assert page.locator('.map-memory-card.is-city').count() == 1
    assert page.locator('[data-memory-explore]').count() == 0
    assert page.locator('[data-memory-more]').count() == 1
    page.screenshot(path=str(OUTPUT / f'map-controls-{width}-settled.png'))
    for phase, layout in [('initial', initial), ('flight', flying)]:
        for key in settled:
            if settled[key] is None:
                assert layout[key] is None, (phase, key)
                continue
            assert layout[key]['display'] == settled[key]['display'], (phase, key, layout[key], settled[key])
            for dimension in ('x', 'y', 'width', 'height'):
                assert layout[key][dimension] == pytest.approx(settled[key][dimension], abs=1), (phase, key, layout[key], settled[key])
    if width > 760:
        overview, collapse = settled['overview'], settled['collapse']
        assert overview['x'] + overview['width'] <= collapse['x']


def test_map_controls_follow_viewport_changes_during_flight(controls_page):
    page = controls_page
    page.goto('http://map-controls.invalid/')
    page.wait_for_function('window.mapControls')
    page.evaluate('mapControls.attach()')
    for width in (390, 1024, 1440):
        page.set_viewport_size({'width': width, 'height': 960})
        page.evaluate('mapControls.redraw()')
        if width > 760:
            layout = controls(page)
            assert layout['caption']['display'] == 'none'
            assert layout['overview']['x'] + layout['overview']['width'] <= layout['collapse']['x']


ALBUM_HTML = HTML.split('<script type="module">')[0] + '''<script type="module">
import {createPlaceWorkspace} from '/client/memoir/place-workspace.mjs';
import {createPhotoWorkspace} from '/client/memoir/photo-workspace.mjs';
const chengde={place:'Chengde',granularity:'city',hierarchy:['Earth','China','Chengde'],latitude:40.95,longitude:117.96,period:'1983'};
const sydney={place:'Sydney',granularity:'city',hierarchy:['Earth','Australia','Sydney'],latitude:-33.86,longitude:151.2,period:'1983'};
const entries=[chengde,sydney].map((place,index)=>({...place,pictures:[{asset_id:String(index),
  image_url:`/static/album-fixture-${index}.svg`,date_expression:'1983',latitude:place.latitude,longitude:place.longitude,
  allowed_actions:{embed:true}}]}));
const state={project:{id:'fixture',profile:{memory_places:entries,birth_year:1983}},supabase:{user:{id:'owner'}},
  lifeStage:'all',chat:[],workspaceFocus:{place:'Chengde',source_sequence:1},timeline:[{id:'birth',canonical:true,revision:1,status:'active',kind:'event',life_stage:'baby',
  title:'Born in Chengde',temporal:{expression:'1983',precision:'year',year_start:1983},
  places:[{role:'setting',status:'supported',place:chengde}]}]};
const dependencies={state,profile:()=>state.project.profile,render(){},lifeStageText:stage=>stage,
  captureProjectScope:()=> 'fixture',isCurrentProjectScope:()=>true};
let places;
const photos=createPhotoWorkspace({...dependencies,placeMapTarget:entry=>places.placeMapTarget(entry)});
places=createPlaceWorkspace({...dependencies,photos});
const scene=document.querySelector('.place-journey-scene');
scene.classList.add('is-cesium-map');
let city='Chengde';
const callbacks=[];
const viewer={isDestroyed:()=>false,entities:{getById(){}},
  scene:{mode:2,postRender:{addEventListener(callback){callbacks.push(callback);return ()=>{};}}},
  camera:{frustum:{left:-40000,right:40000},flyTo(flight){queueMicrotask(()=>flight.complete?.());},
    computeViewRectangle(){
      const target=city==='Sydney' ? sydney : city==='empty' ? {latitude:0,longitude:0} : chengde;
      const offset=city==='near' ? .8 : city==='far' ? 1.1 : -.1;
      const degrees=city===null ? {west:-180,south:-85,east:180,north:85}
        : {west:target.longitude-.1,south:target.latitude+offset,east:target.longitude+.1,north:target.latitude+offset+.2};
      return Object.fromEntries(Object.entries(degrees).map(([key,value])=>[key,value*Math.PI/180]));
    }}};
const cesium={SceneMode:{SCENE2D:2},Cartesian3:{fromDegrees:(longitude,latitude)=>({longitude,latitude})},
  SceneTransforms:{worldToWindowCoordinates:(_,point)=>({
    x:city==='empty' ? -5000 : city===null ? scene.clientWidth*(point.longitude<130 ? .55 : .75)
      : (point.longitude<130 ? city==='Chengde' : city==='Sydney') ? scene.clientWidth*.6 : -5000,
    y:scene.clientHeight*.6})}};
function redraw(){for(let i=0;i<2;i++)for(const callback of callbacks)callback();}
places.mapPhotoAlbums.sync(scene);places.mapPhotoAlbums.attach(viewer,cesium,[]);
places.mapMemoryEvents.sync(scene);places.mapMemoryEvents.attach(viewer,cesium);
await new Promise(resolve=>setTimeout(resolve,0));redraw();
window.mapAlbums={view(next,span=80000){city=next;viewer.camera.frustum={left:-span/2,right:span/2};redraw();}};
</script></html>'''


@pytest.mark.parametrize('controls_page', [ALBUM_HTML], indirect=True, ids=['city-albums'])
@pytest.mark.parametrize('width', [1440, 1024, 390])
def test_photo_lists_follow_the_visible_city_at_every_zoom(controls_page, width):
    page = controls_page
    page.set_viewport_size({'width': width, 'height': 960})
    page.goto('http://map-controls.invalid/')
    page.wait_for_function('window.mapAlbums')
    labels = page.locator('[data-photo-album] .map-album-place')
    for city in ('Chengde', 'Sydney', 'Chengde'):
        for span in (80000, 40000, 8000, 80000):
            page.evaluate('([city,span])=>mapAlbums.view(city,span)', [city, span])
            assert labels.all_text_contents() == [city], (city, span, labels.all_text_contents())
    if width > 760:
        page.evaluate('mapAlbums.view(null)')
        assert labels.all_text_contents() == ['Chengde', 'Sydney']


@pytest.mark.parametrize('controls_page', [ALBUM_HTML], indirect=True, ids=['city-albums'])
@pytest.mark.parametrize('width', [1440, 1024])
def test_photo_connector_matches_events_and_reaches_the_visible_stack(controls_page, width):
    page = controls_page
    page.set_viewport_size({'width': width, 'height': 960})
    page.add_init_script('''const proto=CanvasRenderingContext2D.prototype;
      for(const name of ['clearRect','beginPath','moveTo','lineTo','stroke']){
        const original=proto[name];proto[name]=function(...args){
          if(name==='clearRect')this.canvas.connectors=[];
          if(name==='beginPath')this.connector={};
          if(name==='moveTo')this.connector.start=args;
          if(name==='lineTo')this.connector.end=args;
          if(name==='stroke'&&this.connector?.start&&this.connector?.end)
            this.canvas.connectors.push({...this.connector,color:this.strokeStyle,width:this.lineWidth});
          return original.apply(this,args);
        };
      }''')
    page.goto('http://map-controls.invalid/')
    page.wait_for_function('window.mapAlbums')
    result = page.evaluate('''() => {
      const canvas=document.querySelector('.map-album-links'),bounds=canvas.getBoundingClientRect();
      const album=[...document.querySelectorAll('[data-photo-album]')].find(item=>item.textContent.includes('Chengde'));
      const stack=album.querySelector('.map-album-stack').getBoundingClientRect();
      return {photo:canvas.connectors[0],event:document.querySelector('.map-memory-trail').connectors[0],
        stack:{left:stack.left-bounds.left,right:stack.right-bounds.left,top:stack.top-bounds.top,bottom:stack.bottom-bounds.top}};
    }''')
    OUTPUT.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(OUTPUT / f'map-city-albums-{width}.png'))
    photo, event, stack = result['photo'], result['event'], result['stack']
    assert (photo['color'], photo['width']) == (event['color'], event['width']), result
    assert photo['end'] == event['end'], result
    assert stack['left'] < photo['start'][0] < stack['right'], result
    assert stack['top'] < photo['start'][1] < stack['bottom'], result


@pytest.mark.parametrize('controls_page', [ALBUM_HTML], indirect=True, ids=['city-albums'])
@pytest.mark.parametrize('width', [1440, 390])
def test_panning_off_all_locations_clears_both_card_lists(controls_page, width):
    page = controls_page
    page.set_viewport_size({'width': width, 'height': 960})
    page.goto('http://map-controls.invalid/')
    page.wait_for_function('window.mapAlbums')
    for span in (80000, 8000, 200000):
        page.evaluate('span=>mapAlbums.view("empty",span)', span)
        assert page.locator('.map-memory-card:visible').count() == 0
        assert page.locator('[data-photo-album]:visible').count() == 0
    page.evaluate('mapAlbums.view("Chengde",80000)')
    assert page.locator('.map-memory-card:visible').count() == 1
    assert page.locator('[data-photo-album] .map-album-place').all_text_contents() == ['Chengde']
    page.evaluate('mapAlbums.view("Sydney",80000)')
    assert page.locator('.map-memory-card:visible').count() == 0
    assert page.locator('[data-photo-album] .map-album-place').all_text_contents() == ['Sydney']


@pytest.mark.parametrize('controls_page', [ALBUM_HTML], indirect=True, ids=['city-albums'])
@pytest.mark.parametrize('width', [1440, 390])
def test_both_lists_stay_while_the_100_km_city_circle_touches_the_view(controls_page, width):
    page = controls_page
    page.set_viewport_size({'width': width, 'height': 960})
    page.goto('http://map-controls.invalid/')
    page.wait_for_function('window.mapAlbums')
    for span in (80000, 8000):
        page.evaluate('span=>mapAlbums.view("near",span)', span)
        assert page.locator('.map-memory-card:visible').count() == 1
        assert page.locator('[data-photo-album] .map-album-place').all_text_contents() == ['Chengde']
        page.evaluate('span=>mapAlbums.view("far",span)', span)
        assert page.locator('.map-memory-card:visible').count() == 0
        assert page.locator('[data-photo-album]:visible').count() == 0


def test_event_card_keeps_its_dom_while_only_changed_text_fades(controls_page):
    page=controls_page
    page.goto('http://map-controls.invalid/')
    page.wait_for_function('window.mapControls')
    page.evaluate('mapControls.attach();mapControls.arrive()')
    page.locator('[data-memory-city]').click()
    page.wait_for_selector('[data-memory-explore="birth"]')
    page.evaluate("""() => {
      window.originalCard=document.querySelector('.map-memory-card');
      window.originalTitle=document.querySelector('.map-memory-summary');
      window.originalText=originalTitle.querySelector('[data-memory-text]').firstChild;
      window.originalExplore=document.querySelector('[data-memory-explore="birth"]');originalExplore.focus();
      mapControls.update({revision:2,title:'Birth at hospital',summary:'A happy childhood by the river.',
        temporal:{expression:'1984',precision:'year',year_start:1984},
        places:[{role:'setting',status:'supported',place:{place:'Chengde Hospital',granularity:'landmark',
          hierarchy:['Earth','China','Chengde','Chengde Hospital'],latitude:40.96,longitude:117.95}}]});
    }""")
    assert page.evaluate("originalCard===document.querySelector('.map-memory-card')"), 'Updating an event replaced its whole card'
    assert page.evaluate("originalTitle===document.querySelector('.map-memory-summary')")
    page.wait_for_function("document.querySelector('.map-memory-summary').textContent==='Birth at hospital'")
    assert page.evaluate("document.querySelector('.map-memory-summary').getAnimations({subtree:true}).length>0")
    assert page.evaluate("document.querySelector('.map-memory-card').getAnimations().length===0")
    page.wait_for_timeout(450)
    assert page.locator('.map-memory-location').inner_text()=='Chengde Hospital'
    assert '1984' in page.locator('.map-memory-date').inner_text()
    assert page.evaluate("originalCard===document.querySelector('.map-memory-card')")
    page.evaluate("mapControls.update({revision:3,title:'Birth in hospital',summary:'A happy childhood beside the river.'})")
    assert page.evaluate("[...document.querySelectorAll('.memory-text-change')].every(span=>!span.textContent.includes('Birth')&&!span.textContent.includes('happy childhood'))")
    page.evaluate("mapControls.update({revision:4,title:'Birth near hospital',summary:'A happy childhood beside the school.'})")
    page.wait_for_timeout(450)
    assert page.locator('.map-memory-summary').inner_text()=='Birth near hospital'
    assert page.locator('.map-memory-description').inner_text()=='A happy childhood beside the school.'
    assert page.locator('.memory-text-change').count()==0
    assert page.evaluate("originalText===originalTitle.querySelector('[data-memory-text]').firstChild")
    assert page.evaluate("document.activeElement===originalExplore")
    page.emulate_media(reduced_motion='reduce')
    page.evaluate("mapControls.update({revision:5,title:'Born here'})")
    assert page.locator('.map-memory-summary').inner_text()=='Born here'
    assert page.locator('.memory-text-change').count()==0
