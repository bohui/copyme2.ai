"""Independent browser probes for linear movement, illustration blends and stock avatars."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

from playwright.sync_api import expect, sync_playwright

from game_assets import pack_catalog, write_json

PACKAGE = Path(__file__).resolve().parent


def run(workspace):
    result = dict(status='FAIL', observations=[], page_errors=[], external_requests=[])
    server = subprocess.Popen([sys.executable, '-B', str(PACKAGE / 'serve.py'), '--output', str(workspace), '--no-metadata'],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        url = json.loads(server.stdout.readline())['url']
        journey = json.loads((workspace / 'build/journey.json').read_text())
        source = json.loads((workspace / 'source/input.json').read_text())['input']
        passages = ['\n\n'.join(b['text'] for b in c['blocks']) for c in source['chapters']]
        passages_by_id = {'C' + str(i + 1): text for i, text in enumerate(passages)}
        segments = {s['id']: s for s in journey['segments']}
        evidence = workspace / 'qa/evidence'
        evidence.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            for width in (1280, 390, 320):
                context = browser.new_context(viewport=dict(width=width, height=960), reduced_motion='no-preference')
                page = context.new_page()
                page.set_default_timeout(6000)
                page.on('pageerror', lambda e: result['page_errors'].append(str(e)))
                page.on('response', lambda r: result['page_errors'].append('HTTP ' + str(r.status) + ': ' + r.url) if r.status >= 400 else None)

                def route(request):
                    if request.request.url.startswith(url):
                        request.continue_()
                    else:
                        result['external_requests'].append(request.request.url)
                        request.abort()

                page.route('**/*', route)
                page.goto(url, wait_until='networkidle')
                game, avatar = page.locator('#game'), page.locator('#player')
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
                assert page.locator('#memory-music').evaluate('(e)=>e.paused && e.currentTime===0')
                page.locator('#full-text').click()
                actual = page.locator('#source-passages > p')
                assert [actual.nth(i).text_content() for i in range(actual.count())] == passages
                page.keyboard.press('Escape')
                expect(game).to_have_attribute('data-visited', '0')

                def walk_to(target, capture_blend=False):
                    positions, cameras, blends = [], [], []
                    page.keyboard.down('ArrowRight')
                    try:
                        for _ in range(280):
                            state = game.evaluate('(e)=>({x:Number(e.dataset.x),camera:Number(e.dataset.camera),transition:e.dataset.transition,mix:Number(e.dataset.blend),opacities:[...document.querySelectorAll(".scene-panel")].map(p=>Number(getComputedStyle(p).opacity))})')
                            positions.append(state['x']); cameras.append(state['camera'])
                            if state['transition'] == 'blending' and .1 < state['mix'] < .9:
                                opacities = state['opacities']
                                assert sum(o > 0 for o in opacities) == 2
                                assert any(0 < o < 1 for o in opacities)
                                if not blends and width == 1280:
                                    page.screenshot(path=str(evidence / 'linear-transition.png'), full_page=True)
                                blends.append(state)
                            if state['x'] == target:
                                break
                            page.wait_for_timeout(25)
                        else:
                            raise AssertionError('Forward movement did not reach its next memory')
                    finally:
                        page.keyboard.up('ArrowRight')
                    assert positions == sorted(positions) and cameras == sorted(cameras)
                    if capture_blend:
                        assert blends, 'Normal-speed input never produced overlapping scene illustrations'
                    return len(blends)

                walk_to(journey['stops'][0]['x'])
                page.locator('#interact').click()
                assert page.locator('#passage').text_content() == passages_by_id[journey['stops'][0]['chapter']]
                paused_x = game.get_attribute('data-x')
                page.keyboard.down('ArrowRight'); page.wait_for_timeout(160); page.keyboard.up('ArrowRight')
                expect(game).to_have_attribute('data-x', paused_x)
                page.locator('#memory-dialog [data-audio-toggle]').click()
                for _ in range(40):
                    if page.locator('#memory-music').evaluate('(e)=>e.currentTime>.25 && !e.paused'):
                        break
                    page.wait_for_timeout(100)
                else:
                    raise AssertionError('Stock music did not advance after the user gesture')
                page.locator('#memory-dialog [data-audio-toggle]').click()
                assert page.locator('#memory-music').evaluate('(e)=>e.paused')
                page.locator('#continue').click()
                expect(game).to_have_attribute('data-visited', '1')
                page.keyboard.press('e')
                expect(game).to_have_attribute('data-visited', '1')
                first_segment = journey['stops'][0]['segment']
                probe_end = next((i for i, s in enumerate(journey['stops']) if s['segment'] != first_segment), min(1, len(journey['stops']) - 1))
                blend_samples, previous = 0, journey['stops'][0]
                for stop in journey['stops'][1:probe_end + 1]:
                    crossed = stop['segment'] != previous['segment']
                    blend_samples += walk_to(stop['x'], capture_blend=crossed)
                    expect(avatar).to_have_attribute('data-avatar', segments[stop['segment']]['avatar'])
                    page.locator('#interact').click(); page.locator('#continue').click()
                    previous = stop
                if width == 1280:
                    # Asset probes change only a DOM preview; source-bound selection is tested separately.
                    for variant in pack_catalog()['variants']:
                        avatar.evaluate('(e,id)=>{e.dataset.avatar=id;e.dataset.moving="true"}', variant['id'])
                        name = avatar.evaluate('(e)=>getComputedStyle(e,"::before").animationName')
                        assert name == ('memoir-walk' if variant['id'] == 'child-casual' else 'memoir-lifetime-walk')
                        first = avatar.evaluate('(e)=>getComputedStyle(e,"::before").backgroundPosition')
                        for _ in range(8):
                            page.wait_for_timeout(80)
                            if first != avatar.evaluate('(e)=>getComputedStyle(e,"::before").backgroundPosition'):
                                break
                        else:
                            raise AssertionError('Stock walk frame did not advance: ' + variant['id'])
                page.emulate_media(reduced_motion='reduce')
                page.wait_for_timeout(80)
                assert avatar.evaluate('(e)=>getComputedStyle(e,"::before").animationName') == 'none'
                assert page.locator('.scene-panel').evaluate_all('(els)=>els.every(e=>getComputedStyle(e).transform==="none")')
                if game.get_attribute('data-phase') == 'complete':
                    page.locator('#restart').click()
                before = int(game.get_attribute('data-x'))
                page.keyboard.down('ArrowRight'); page.wait_for_timeout(180); page.keyboard.up('ArrowRight')
                assert int(game.get_attribute('data-x')) > before
                if width == 320:
                    page.screenshot(path=str(evidence / 'linear-320.png'), full_page=True)
                result['observations'].append(dict(width=width, unchanged_passages=len(passages),
                    monotonic_player_and_camera=True, normal_motion_blend_samples=blend_samples,
                    reader_pause=True, no_duplicate_credit=True, opt_in_and_mute=True, reduced_motion_walk=True))
                context.close()
            browser.close()
        assert not result['page_errors'] and not result['external_requests'], result
        result.update(status='PASS', stock_variants=len(pack_catalog()['variants']),
            limitations=['Chromium emulation, informed scripted checks; physical devices, other browsers and subjective experience not evaluated.'])
        return result
    except Exception as error:
        result['failure'] = type(error).__name__ + ': ' + str(error)[:2000]
        raise
    finally:
        server.terminate(); server.wait(timeout=10)
        write_json(workspace, 'qa/journey-checks.json', result)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.output.resolve())))
