"""Serve only the fictional generated game on a loopback-only preview origin."""
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP = HERE / 'build/app'
assert (APP / 'index.html').is_file()


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(APP), **kwargs)

    def end_headers(self):
        self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src data:; connect-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Cache-Control', 'no-store')
        super().end_headers()

    def log_message(self, *args):
        pass


server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
server.daemon_threads = True
info = {'url': 'http://127.0.0.1:' + str(server.server_port) + '/', 'pid': os.getpid(), 'root': str(APP), 'synthetic': True}
(HERE / 'preview-server.json').write_text(json.dumps(info, indent=2) + '\n')
print(json.dumps(info), flush=True)
try:
    server.serve_forever()
finally:
    server.server_close()
