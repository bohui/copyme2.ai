"""Independent source-fidelity, keyboard, narrow-layout and offline checks."""
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import json
from pathlib import Path
import threading

from playwright.sync_api import sync_playwright, expect

HERE = Path(__file__).resolve().parent


def check():
    app = HERE / 'build/app'
    packet = json.loads((HERE / 'source/input.json').read_text())['input']
    passages = ['\n\n'.join(b['text'] for b in c['blocks']) for c in packet['chapters']]
    plan = json.loads((HERE / 'build/playthrough.json').read_text())
    runtime = '\n'.join(p.read_text() for p in app.iterdir() if p.is_file())
    for item in packet['chapters']:
        assert item['chapter_id'] not in runtime, 'Internal provenance in public runtime'
    for item in packet['timeline']:
        assert item['id'] not in runtime, 'Internal timeline ID in public runtime'

    # Bundle only the model's existing local assets; do not rewrite its game rules.
    html = (app / 'index.html').read_text()
    css, js = (app / 'game.css').read_text(), (app / 'game.js').read_text()
    assert html.count('<link rel="stylesheet" href="game.css">') == 1
    assert html.count('<script src="game.js" defer></script>') == 1
    assert '</script' not in js.lower() and '</style' not in css.lower()
    html = html.replace('<link rel="stylesheet" href="game.css">', '<style>' + css + '</style>')
    html = html.replace('<script src="game.js" defer></script>', '')
    html = html.replace('</body>', '<script>' + js + '</script>\n</body>')
    export = HERE / 'export/age-eight.html'
    export.parent.mkdir(exist_ok=True)
    export.write_text(html)

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(app), **kwargs)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    url = f'http://127.0.0.1:{server.server_port}/'
    records, errors, external = [], [], []
    result = dict(status='FAIL')
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            for width, height in [(1280, 720), (320, 800)]:
                context = browser.new_context(viewport=dict(width=width, height=height), reduced_motion='reduce')
                page = context.new_page()
                page.set_default_timeout(6000)
                page.on('pageerror', lambda error: errors.append(str(error)))

                def intercept(route):
                    if route.request.url.startswith(url):
                        route.continue_()
                    else:
                        external.append(route.request.url)
                        route.abort()

                page.route('**/*', intercept)
                page.goto(url, wait_until='networkidle')
                for _ in range(12):
                    page.keyboard.press('Tab')
                    if page.locator('#start').evaluate('(el) => el === document.activeElement'):
                        break
                else:
                    raise AssertionError('Start is not reachable using Tab')
                for step in plan['steps']:
                    target = page.locator(step['selector'])
                    if step['action'] in ('click', 'press'):
                        target.press(step.get('value', 'Enter'))
                    elif step['action'] == 'assert_text':
                        expect(target).to_be_visible()
                        expect(target).to_contain_text(step['value'])
                    else:
                        expect(target).to_have_attribute(step['attribute'], step['value'])
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'), f'Overflow at {width}px: {step}'

                # One deliberately wrong and rushed attempt must expose both causes.
                for selector in ['#start', '#zone-left', '#observe', '#mark', '#glue', '#press', '#test']:
                    page.locator(selector).press('Enter')
                expect(page.locator('#app')).to_have_attribute('data-result', 'both')
                expect(page.locator('#feedback')).to_contain_text('patch missed the leak')
                expect(page.locator('#feedback')).to_contain_text('edge curls')
                expect(page.locator('#retry')).to_be_focused()
                before = page.locator('#feedback').inner_text()
                page.locator('#memory-open').press('Enter')
                expect(page.locator('#memory')).to_be_visible()
                assert page.locator('#memory-passages article').count() == 10
                for index, text in enumerate(passages, 1):
                    assert page.locator(f'#memory-chapter-{index} p').text_content() == text
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
                page.keyboard.press('Escape')
                expect(page.locator('#memory')).not_to_be_visible()
                expect(page.locator('#memory-open')).to_be_focused()
                assert page.locator('#feedback').inner_text() == before
                expect(page.locator('#app')).to_have_attribute('data-result', 'both')
                page.locator('#retry').press('Enter')
                expect(page.locator('#evidence-left')).to_contain_text('Look 1: no bubbles.')
                expect(page.locator('#app')).to_have_attribute('data-result', 'none')
                assert not errors and not external
                records.append(dict(viewport=[width, height], keyboardReplaySteps=len(plan['steps']), combinedFault='PASS', sourceChapters=10, dialogStateAndFocus='PASS', overflow='PASS'))
                context.close()

            offline = browser.new_context(offline=True)
            page = offline.new_page()
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(export.as_uri(), wait_until='load')
            page.locator('#start').click()
            expect(page.locator('#app')).to_have_attribute('data-screen', 'practice')
            for selector in ['#zone-middle', '#observe', '#observe', '#mark', '#glue', '#wait', '#wait', '#press', '#test']:
                page.locator(selector).click()
            expect(page.locator('#app')).to_have_attribute('data-result', 'flat')
            assert not errors
            offline.close()
            browser.close()
        result = dict(status='PASS', keyboardAndLayouts=records, offlineExport='PASS', publicProvenance='PASS', pageErrors=errors, externalRequests=external,
            artifactSha256=hashlib.sha256((app/'index.html').read_bytes()).hexdigest(), exportSha256=hashlib.sha256(export.read_bytes()).hexdigest())
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)
        target = HERE / 'qa/extra-checks.json'
        pending = target.with_suffix('.next')
        pending.write_text(json.dumps(result, indent=2) + '\n')
        pending.replace(target)
    print(json.dumps(result))


if __name__ == '__main__':
    check()
