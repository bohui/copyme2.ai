"""Independent RPG state, original-passage, narrow-layout and offline checks."""
import argparse
import hashlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading

from playwright.sync_api import expect, sync_playwright


def run(workspace, stage):
    app = workspace / 'build/app'
    packet = json.loads((workspace / 'source/input.json').read_text())['input']
    passages = ['\n\n'.join(b['text'] for b in c['blocks']) for c in packet['chapters']]
    files = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in app.iterdir() if p.is_file()}
    code = '\n'.join(p.read_text() for p in app.iterdir() if p.is_file())
    for item in packet['chapters']:
        assert item['chapter_id'] not in code, 'Private chapter ID in playable files'
    for item in packet['timeline']:
        assert item['id'] not in code, 'Private timeline ID in playable files'

    html = (app / 'index.html').read_text()
    css, js = (app / 'game.css').read_text(), (app / 'game.js').read_text()
    assert html.count('<link rel="stylesheet" href="game.css">') == 1
    assert html.count('<script src="game.js" defer></script>') == 1
    assert '</style' not in css.lower() and '</script' not in js.lower()
    html = html.replace('<link rel="stylesheet" href="game.css">', '<style>' + css + '</style>')
    html = html.replace('<script src="game.js" defer></script>', '')
    html = html.replace('</body>', '<script>' + js + '</script>\n</body>')
    export = workspace / 'export' / ('age-eight-whitebox.html' if stage == 'whitebox' else 'age-eight.html')
    export.parent.mkdir(parents=True, exist_ok=True)
    export.write_text(html)
    qa = workspace / ('qa/whitebox' if stage == 'whitebox' else 'qa')
    qa.mkdir(parents=True, exist_ok=True)

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(app), **kwargs)

        def end_headers(self):
            self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src data:; connect-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
            super().end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f'http://127.0.0.1:{server.server_port}/'
    errors, external, observations = [], [], []
    result = {'status': 'FAIL'}
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
                game = page.locator('#game')
                expect(game).to_have_attribute('data-count', '0')
                expect(game).to_have_attribute('data-scene', 'hub')
                page.locator('#full-text').click()
                expect(page.locator('#full-source')).to_be_visible()
                entries = page.locator('#source-passages .source-entry')
                assert entries.count() == 10
                for index, text in enumerate(passages):
                    assert entries.nth(index).locator('p.passage').text_content() == text
                page.keyboard.press('ArrowRight', delay=200)
                expect(game).to_have_attribute('data-player-x', '80')
                page.keyboard.press('Escape')
                expect(page.locator('#full-source')).not_to_be_visible()
                expect(page.locator('#full-text')).to_be_focused()
                expect(game).to_have_attribute('data-count', '0')
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')

                page.locator('#interact').click()
                expect(page.locator('#dialogue')).to_be_visible()
                assert page.locator('#memory-text').text_content() == passages[0]
                page.keyboard.press('ArrowRight', delay=200)
                expect(game).to_have_attribute('data-player-x', '80')
                page.locator('#close').click()
                expect(game).to_have_attribute('data-count', '1')
                assert page.evaluate('document.activeElement.id') in ('viewport', 'interact')
                page.locator('#interact').click()
                page.keyboard.press('Escape')
                expect(game).to_have_attribute('data-count', '1')

                page.locator('#viewport').press('ArrowRight', delay=5000)
                expect(game).to_have_attribute('data-player-x', '1840')
                expect(game).to_have_attribute('data-camera-x', '1440')
                before = page.locator('#world').evaluate('(e) => getComputedStyle(e).transform')
                assert before not in ('none', 'matrix(1, 0, 0, 1, 0, 0)')
                page.locator('#viewport').press('Enter')
                expect(game).to_have_attribute('data-scene', 'hub')
                expect(game).to_have_attribute('data-count', '1')
                page.wait_for_timeout(200)
                expect(game).to_have_attribute('data-player-x', '1840')
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
                page.goto(url, wait_until='networkidle')
                page.locator('#right').press('Enter', delay=250)
                assert int(game.get_attribute('data-player-x')) > 80
                expect(page.locator('#dialogue')).not_to_be_visible()
                stopped = game.get_attribute('data-player-x')
                page.wait_for_timeout(200)
                expect(game).to_have_attribute('data-player-x', stopped)
                page.locator('#left').press('Space', delay=350)
                expect(game).to_have_attribute('data-player-x', '80')
                expect(game).to_have_attribute('data-count', '0')
                assert not errors and not external
                observations.append(dict(viewport=[width, height], originalPassages=10,
                    fullTextAddsNoCredit=True, memoryRevisitAddsNoCredit=True,
                    overlaysStopMovement=True, focusRestored=True,
                    movementBounds=[80, 1840], cameraEnd=1440,
                    prematureGardenEntryBlocked=True, keyboardMovementButtons=True, horizontalOverflow=False))
                context.close()

            context = browser.new_context(offline=True)
            page = context.new_page()
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(export.as_uri(), wait_until='load')
            page.locator('#interact').click()
            expect(page.locator('#dialogue')).to_be_visible()
            assert page.locator('#memory-text').text_content() == passages[0]
            page.locator('#close').click()
            expect(page.locator('#game')).to_have_attribute('data-count', '1')
            assert not errors
            context.close()
            browser.close()
        assert files == {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in app.iterdir() if p.is_file()}
        result = dict(status='PASS', observations=observations, offlineExport='PASS',
            artifactFilesSha256=files, export=export.relative_to(workspace).as_posix(),
            exportSha256=hashlib.sha256(export.read_bytes()).hexdigest(),
            pageErrors=errors, externalRequests=external)
    except Exception as error:
        result.update(error=type(error).__name__ + ': ' + str(error)[:1800])
        raise
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        pending = qa / 'extra-checks.next'
        pending.write_text(json.dumps(result, indent=2) + '\n')
        pending.replace(qa / 'extra-checks.json')
    print(json.dumps(result))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--stage', choices=['whitebox', 'production'], default='production')
    args = parser.parse_args()
    run(args.output.resolve(), args.stage)
