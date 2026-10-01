"""Check city map pins and new-place grouping while background requests are held."""
import argparse
import json

from playwright.sync_api import expect, sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:3010')
    args = parser.parse_args()
    # Deliberately synthetic coordinates: these are UI fixtures, not historical locations.
    city = {'place': '承德', 'hierarchy': ['Earth', '中国', '河北', '承德'],
            'granularity': 'city', 'latitude': 40.97, 'longitude': 117.93}
    locations = [city,
        {'place': '承德师范学校', 'hierarchy': [*city['hierarchy'], '承德师范学校'],
         'granularity': 'landmark', 'latitude': 40.93, 'longitude': 117.96},
        {'place': '大石庙镇', 'hierarchy': [*city['hierarchy'], '大石庙镇'],
         'granularity': 'suburb', 'latitude': 40.921, 'longitude': 117.962},
        {'place': '测试公园', 'hierarchy': [*city['hierarchy'], '测试公园'],
         'granularity': 'landmark', 'latitude': 40.925, 'longitude': 117.955},
        {'place': 'Sydney', 'hierarchy': ['Earth', 'Australia', 'Sydney'],
         'granularity': 'city', 'latitude': -33.8688, 'longitude': 151.2093}]
    errors = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1440, 'height': 960}, locale='en-AU', reduced_motion='reduce')
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.route('**/agent/config', lambda route: route.fulfill(json={
            'auth_mode': 'test', 'google_maps_browser_api_key': 'test-browser-key'}))
        page.route('**/place-photos?**', lambda route: route.fulfill(json={'items': [], 'status': 'NO_MATCH'}))

        def imagery(route):
            response = route.fetch()
            route.fulfill(response=response, body=response.text() + '''
                Cesium.Google2DImageryProvider.fromUrl = async () => new Cesium.GridImageryProvider();
            ''')
        page.route('**/Build/Cesium/Cesium.js', imagery)
        page.add_init_script('''
            let cesium;
            Object.defineProperty(window, 'Cesium', {configurable: true,
              get: () => cesium, set: value => {
                cesium = {...value};
                cesium.Viewer = new Proxy(value.Viewer, {construct(target, args) {
                  return window.__mapViewer = Reflect.construct(target, args);
                }});
              }});
        ''')
        page.add_init_script('window.__testPlaces = ' + json.dumps(locations, ensure_ascii=False) + ';')
        page.add_init_script('''
          const original = window.fetch.bind(window);
          window.__groupRequests = []; window.__holdGroups = true; window.__turnNumber = 0;
          window.fetch = async (url, options) => {
            if (String(url).endsWith('/place-groups')) {
              window.__groupRequests.push(JSON.parse(options.body));
              if (window.__holdGroups) await new Promise(resolve => {
                (window.__releaseGroups ||= []).push(resolve);
              });
              return original(url, options);
            }
            if (!String(url).endsWith('/agent/turn')) return original(url, options);
            const body = JSON.parse(options.body);
            const journey = window.__testPlaces.find(place => body.text?.split('\\n')[0].endsWith(place.place));
            const sequence = ++window.__turnNumber;
            const reply = journey ? 'I remember that place. What comes to mind?' : 'Where would you like to start?';
            if (!journey) return new Response(JSON.stringify({reply, conversation_saved: true}),
              {headers: {'Content-Type': 'application/json'}});
            const encoder = new TextEncoder();
            return new Response(new ReadableStream({start(controller) {
              const emit = event => controller.enqueue(encoder.encode(JSON.stringify(event) + '\\n'));
              emit({type: 'text_delta', text: 'I remember that place. '});
              emit({type: 'place_preview', data: {project_id: body.project_id,
                source_sequence: sequence, place_journey: {schema_version: 1, ...journey}}});
              window.__finishReply = () => {
                emit({type: 'text_delta', text: 'What comes to mind?'});
                emit({type: 'conversation_saved', data: {project_id: body.project_id, reply, conversation_saved: true}});
                emit({type: 'workspace_update', data: {project_id: body.project_id, source_sequence: sequence,
                  place_journey: {schema_version: 1, ...journey, status: 'active', revision: sequence},
                  place_journey_change: {changed: true, revision: sequence}}});
                emit({type: 'result', data: {reply}}); controller.close();
              };
            }}), {headers: {'Content-Type': 'application/x-ndjson'}});
          };
        ''')
        page.goto(args.base_url + '/memoir', wait_until='networkidle')
        page.locator("[data-action='start-story'][data-mode='self']").click()
        expect(page.locator('main.chat-main')).to_be_visible()
        expect(page.locator('.message-streaming')).to_have_count(0, timeout=15000)

        def mention(place):
            page.locator('#chat-input').fill('I remember ' + place)
            page.locator("#chat-form button[type='submit']").click()
            expect(page.locator('.message-streaming .message-text')).to_contain_text('I remember that place')
            page.wait_for_function('typeof window.__finishReply === "function"')
            page.evaluate('window.__finishReply(); window.__finishReply = null')
            expect(page.locator('.message-streaming')).to_have_count(0, timeout=15000)
            expect(page.locator("#chat-form button[type='submit']")).to_be_enabled()

        for place in locations[:3]:
            mention(place['place'])
        page.wait_for_function('window.__groupRequests.length >= 3')
        assert page.evaluate('window.__holdGroups'), 'background requests were released too soon'
        expect(page.locator('.place-journey-heading h2')).to_have_text('承德')
        expect(page.locator('[data-place-choice]')).to_have_count(0)
        expect(page.locator('.place-journey-scene.is-cesium-map')).to_be_visible(timeout=30000)
        page.wait_for_function('window.__mapViewer.entities.values.length === 2')
        assert page.evaluate('window.__mapViewer.entities.values.map(e => e.label.text.getValue())') == ['承德师范学校', '大石庙镇']
        assert float(page.locator('[data-cesium-height]').get_attribute('data-cesium-height')) < 24000
        page.locator('#chat-input').fill('Draft stays while grouping finishes')
        page.evaluate('window.__holdGroups = false; window.__releaseGroups.forEach(resolve => resolve())')
        expect(page.locator('#chat-input')).to_have_value('Draft stays while grouping finishes')
        for place in locations[3:]:
            mention(place['place'])
        expect(page.locator('[data-place-choice]')).to_have_count(2)
        page.locator('[data-place-choice]').filter(has_text='承德').click()
        expect(page.locator('.place-journey-heading h2')).to_have_text('承德')
        page.wait_for_function('window.__mapViewer.entities.values.length === 3')
        assert page.evaluate('window.__mapViewer.entities.values.map(e => e.label.text.getValue())') == ['承德师范学校', '大石庙镇', '测试公园']
        page.wait_for_function('window.__mapViewer.scene.mode === Cesium.SceneMode.SCENE2D')
        page.wait_for_function('''() => window.__mapViewer.entities.values.every(entity => {
          const v = window.__mapViewer;
          const pixel = Cesium.SceneTransforms.worldToWindowCoordinates(v.scene, entity.position.getValue());
          return pixel && pixel.x > 0 && pixel.x < v.scene.canvas.clientWidth &&
            pixel.y > 0 && pixel.y < v.scene.canvas.clientHeight;
        })''')
        assert not errors, errors
        browser.close()
    print('PASS: one city map, distinct visible child pins, automatic new-place membership, separate cities, conversation usable during held grouping')


if __name__ == '__main__':
    main()
