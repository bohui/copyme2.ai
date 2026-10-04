"""Exercise the guard with only task-owned loopback redirect and sink servers."""
import argparse
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import runpy
import threading

from playwright.sync_api import sync_playwright


@contextmanager
def server(handler):
    http = ThreadingHTTPServer(('127.0.0.1', 0), handler)
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{http.server_port}'
    finally:
        http.shutdown()
        http.server_close()
        thread.join(timeout=5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', choices=['get', 'post', 'get-chain', 'allowed-get',
                        'allowed-post', 'allowed-navigation', 'stream'], required=True)
    args = parser.parse_args()
    sink_requests = []
    final_methods = []
    stream_release = threading.Event()

    class Sink(BaseHTTPRequestHandler):
        def receive(self):
            self.rfile.read(int(self.headers.get('Content-Length', '0')))
            sink_requests.append(self.command)
            self.send_response(200)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(b'task-owned unapproved sink')

        do_GET = receive
        do_POST = receive

        def log_message(self, *args):
            pass

    with server(Sink) as sink_origin:
        class Source(BaseHTTPRequestHandler):
            def receive(self):
                self.rfile.read(int(self.headers.get('Content-Length', '0')))
                if self.path == '/redirect':
                    self.send_response(307 if self.command == 'POST' else 302)
                    self.send_header('Location', sink_origin + '/sink')
                elif self.path in {'/allowed', '/chain'}:
                    self.send_response(307 if self.command == 'POST' else 302)
                    self.send_header('Location', '/final' if self.path == '/allowed' else '/redirect')
                elif self.path == '/stream':
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/x-ndjson')
                    self.end_headers()
                    self.wfile.write(b'first\n')
                    self.wfile.flush()
                    if stream_release.wait(timeout=25):
                        self.wfile.write(b'last\n')
                    return
                else:
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/html')
                self.end_headers()
                if self.path == '/final':
                    final_methods.append(self.command)
                    self.wfile.write(b'owned-final')
                elif self.path not in {'/redirect', '/allowed', '/chain'}:
                    self.wfile.write(b'<html><body>Owned redirect canary</body></html>')

            do_GET = receive
            do_POST = receive

            def log_message(self, *args):
                pass

        with server(Source) as source_origin:
            os.environ['MEMOIR_BROWSER_URL'] = source_origin
            os.environ.pop('MEMORY_SPARK_API_ORIGIN', None)
            guard = runpy.run_path(str(Path(__file__).with_name('browser_network_guard.py')))
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                try:
                    method = 'POST' if args.case in {'post', 'allowed-post'} else 'GET'
                    # Cover both entry points used by the task browser tests.
                    page = (browser.new_context().new_page() if method == 'POST'
                            or args.case == 'stream' else browser.new_page())
                    page.goto(source_origin)
                    if args.case == 'stream':
                        first = page.evaluate("""async () => {
                            const response = await fetch('/stream');
                            window.canaryReader = response.body.getReader();
                            const chunk = await window.canaryReader.read();
                            return new TextDecoder().decode(chunk.value);
                        }""")
                        assert first == 'first\n', 'First chunk must arrive before the server releases the last'
                        stream_release.set()
                        last = page.evaluate("""async () => {
                            const chunk = await window.canaryReader.read();
                            return new TextDecoder().decode(chunk.value);
                        }""")
                        assert last == 'last\n'
                        outcome = 'streamed'
                    elif args.case == 'allowed-navigation':
                        response = page.goto(source_origin + '/allowed')
                        assert page.url == source_origin + '/final' and response.status == 200
                        assert page.locator('body').inner_text() == 'owned-final'
                        outcome = 'allowed'
                    else:
                        path = '/allowed' if args.case.startswith('allowed-') else (
                            '/chain' if args.case == 'get-chain' else '/redirect')
                        outcome = page.evaluate("""async ({method, path}) => {
                        try {
                            const response = await fetch(path, {method,
                                body: method === 'POST' ? 'synthetic-canary' : undefined});
                            if (path === '/allowed') {
                                return response.url.endsWith('/final') &&
                                    await response.text() === 'owned-final' ? 'allowed' : 'invalid';
                            }
                            return 'reached';
                        }
                        catch { return 'blocked'; }
                    }""", {'method': method, 'path': path})
                finally:
                    stream_release.set()
                    browser.close()
            result = {'case': args.case, 'outcome': outcome,
                      'sink_requests': sink_requests, 'blocked': guard['blocked'],
                      'final_methods': final_methods}
            print(json.dumps(result))
            assert sink_requests == [], 'Redirect reached the task-owned unapproved sink'
            if args.case.startswith('allowed-'):
                assert outcome == 'allowed' and final_methods == [method]
                assert guard['blocked'] == []
            elif args.case == 'stream':
                assert outcome == 'streamed' and guard['blocked'] == []
            else:
                assert outcome == 'blocked'
                assert guard['blocked'] == [{'origin': sink_origin, 'path': '/sink', 'method': method}]


if __name__ == '__main__':
    main()
