"""Host-owned browser replay for the isolated fictional NovelToGame experiment."""
import argparse
import hashlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import platform
import sys
import threading
from uuid import uuid4

from playwright.sync_api import sync_playwright, expect

PACKAGE = Path(__file__).resolve().parent
HERE = PACKAGE.parents[1] / 'var/novel-to-game-rpg-scroller'
CHECKS = ('launch', 'render', 'input', 'coreLoop', 'outcome', 'restart')


def hold_duration(step):
    value = step.get('duration_ms')
    if type(value) is not int or not 50 <= value <= 5000:
        raise ValueError('hold requires duration_ms from 50 to 5000')
    return value


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix('.next')
    pending.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    pending.replace(path)


def verify(stage, phone=False):
    app = HERE / 'build/app'
    plan = json.loads((HERE / 'build/playthrough.json').read_text())
    assert 4 <= len(plan['steps']) <= 100
    assert [s.get('checkpoint') for s in plan['steps'] if s.get('checkpoint')] == list(CHECKS[2:])
    assert all(s['action'] in ('click', 'press', 'hold', 'assert_text', 'assert_attr') for s in plan['steps'])
    for step in plan['steps']:
        if step['action'] == 'hold':
            hold_duration(step)
    qa = HERE / ('qa' if stage == 'production' else 'qa/whitebox')
    if phone:
        qa = qa / 'phone'
    evidence = qa / 'evidence'
    evidence.mkdir(parents=True, exist_ok=True)
    run_id = stage + ('-phone-' if phone else '-desktop-') + uuid4().hex[:12]
    observations, trace, errors, network = {}, [], [], []
    checks = {key: 'NOT_RUN' for key in CHECKS}
    current_check, failure = 'launch', None

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(app), **kwargs)

        def end_headers(self):
            self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src data:; connect-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
            super().end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = 'http://127.0.0.1:' + str(server.server_port)
    artifacts = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in app.iterdir() if p.is_file()}
    environment = {'runtime': 'Chromium', 'host': platform.system(), 'viewport': [390, 844] if phone else [1440, 1000], 'touch': phone, 'artifactFilesSha256': artifacts}

    def observe(page, key, inputs, state):
        filename = evidence / (key + '.png')
        page.screenshot(path=str(filename), full_page=True)
        observations[key] = {'id': key, 'inputs': inputs, 'state': state, 'visual': filename.relative_to(HERE).as_posix(), 'visibleText': page.locator('body').inner_text()[:16000]}
        checks[key] = 'PASS'

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            environment['runtimeVersion'] = browser.version
            context = browser.new_context(viewport={'width': environment['viewport'][0], 'height': environment['viewport'][1]}, has_touch=phone, is_mobile=phone, reduced_motion='reduce')
            page = context.new_page()
            page.set_default_timeout(6000)
            page.on('pageerror', lambda e: errors.append(str(e)))

            def route_request(route):
                if route.request.url.startswith(url + '/'):
                    route.continue_()
                else:
                    network.append(route.request.url)
                    route.abort()

            page.route('**/*', route_request)
            response = page.goto(url + '/', wait_until='networkidle')
            assert response.status == 200
            expect(page.locator(plan['initial']['selector'])).to_contain_text(plan['initial']['text'])
            initial_text = page.locator('body').inner_text()
            observe(page, 'launch', [{'action': 'navigate', 'url': '/'}], 'initial-state')
            current_check = 'render'
            assert page.locator('body').bounding_box()['height'] > 100
            assert len(initial_text.strip()) > 50
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'), 'Horizontal overflow'
            assert not errors, errors
            observe(page, 'render', [{'action': 'observe', 'viewport': environment['viewport']}], 'visible-initial-screen')
            actions = 0
            for step in plan['steps']:
                action = step['action']
                locator = page.locator(step['selector'])
                if action in ('click', 'press', 'hold'):
                    actions += 1
                    current_check = next((k for k in CHECKS[2:] if checks[k] == 'NOT_RUN'), 'restart')
                    if action == 'hold':
                        duration = hold_duration(step)
                        if phone:
                            locator.scroll_into_view_if_needed()
                            box = locator.bounding_box()
                            assert box, 'Held touch target is not visible'
                            session = context.new_cdp_session(page)
                            session.send('Input.dispatchTouchEvent', {'type': 'touchStart', 'touchPoints': [
                                {'x': box['x'] + box['width']/2, 'y': box['y'] + box['height']/2}]})
                            try:
                                page.wait_for_timeout(duration)
                            finally:
                                session.send('Input.dispatchTouchEvent', {'type': 'touchEnd', 'touchPoints': []})
                                session.detach()
                        else:
                            locator.press(step['value'], delay=duration)
                    elif action == 'press':
                        locator.press(step['value'])
                    elif phone:
                        locator.tap()
                    else:
                        locator.click()
                elif action == 'assert_text':
                    expect(locator).to_be_visible()
                    expect(locator).to_contain_text(step['value'])
                else:
                    expect(locator).to_be_visible()
                    expect(locator).to_have_attribute(step['attribute'], step['value'])
                trace.append(step)
                checkpoint = step.get('checkpoint')
                if checkpoint:
                    assert action.startswith('assert_') and actions > 0
                    assert not errors, errors
                    assert not network, network
                    if checkpoint == 'input':
                        assert page.locator('body').inner_text() != initial_text
                    if checkpoint == 'restart':
                        expect(page.locator(plan['initial']['selector'])).to_contain_text(plan['initial']['text'])
                    state = plan['terminal'] if checkpoint == 'outcome' else plan['restart'] if checkpoint == 'restart' else step['value']
                    observe(page, checkpoint, trace.copy(), state)
            assert actions >= 3
            assert all(v == 'PASS' for v in checks.values())
            assert artifacts == {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in app.iterdir() if p.is_file()}, 'Build changed during verification'
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'), 'Horizontal overflow'
            context.close()
            browser.close()
    except Exception as error:
        checks[current_check] = 'FAIL'
        failure = type(error).__name__ + ': ' + str(error)[:2500]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    evidence_path = evidence / 'run.json'
    atomic_json(evidence_path, {'schemaVersion': 1, 'runId': run_id, 'environment': environment, 'inputTrace': trace, 'observations': observations, 'pageErrors': errors, 'externalRequests': network, 'failure': failure})
    result = {'schemaVersion': 3, 'status': 'FAIL' if failure else 'PASS', 'verify': {'command': 'python3 experiments/novel-to-game/verify.py --output ' + str(HERE) + ' --stage ' + stage + (' --phone' if phone else ''), 'exitCode': 1 if failure else 0}, 'completeRun': {'id': run_id, 'cleanContext': True, 'terminal': plan['terminal'], 'restart': plan['restart'], 'evidence': evidence_path.relative_to(HERE).as_posix()}, 'checks': checks, 'limitations': [{'scope': 'human experience', 'reason': 'Informed scripted verification does not establish subjective fun, balance or discoverability.'}, {'scope': 'other browsers and physical devices', 'reason': 'Chromium emulation only; real phones, Safari and Firefox not exercised.'}]}
    atomic_json(qa / 'verification.json', result)
    return result, failure


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', choices=('whitebox', 'production'), required=True)
    parser.add_argument('--phone', action='store_true')
    parser.add_argument('--output', type=Path, default=HERE)
    args = parser.parse_args()
    HERE = args.output.resolve()
    result, error = verify(args.stage, args.phone)
    print(json.dumps({'status': result['status'], 'checks': result['checks'], 'failure': error}), flush=True)
    sys.exit(result['verify']['exitCode'])
