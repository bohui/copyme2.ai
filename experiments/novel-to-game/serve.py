"""Serve only the generated game on a loopback-only preview origin."""
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import argparse
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output',type=Path,default=Path(__file__).resolve().parents[2]/'var/novel-to-game-rpg-scroller')
parser.add_argument('--no-metadata',action='store_true',help='Keep an existing user preview receipt when serving a temporary QA origin')
parser.add_argument('--application',action='store_true',help='Preview a saved game-package.json through the actual Memoir iframe renderer')
args = parser.parse_args()
HERE = args.output.resolve()
APP = HERE / 'build/app'
assert (HERE/'game-package.json').is_file() if args.application else (APP / 'index.html').is_file()
ROOT=Path(__file__).resolve().parents[2]
if args.application:
    sys.path.insert(0,str(ROOT))
    from apps.api.novel_game_bundle import runtime_bundle,runtime_asset
    from apps.api.novel_game_art import hydrate_illustrations


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(APP), **kwargs)

    def do_GET(self):
        if not args.application:
            return super().do_GET()
        path=urlsplit(self.path).path
        try:
            if path=='/':
                data=b'''<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Fictional memoir RPG</title><style>body{margin:0;background:#faf6e9}iframe{border:0;width:100%;height:100vh}</style></head><body><div id="game-root"></div><script type="module">import {mountStoryGameWebpage} from '/client/memoir/story-game.mjs';const response=await fetch('/game.json');const saved=await response.json();const labels={title:'Fictional age-eight RPG',unavailable:'The game could not load.'};mountStoryGameWebpage(document.querySelector('#game-root'),saved.game,key=>labels[key]||key);</script></body></html>'''
                mime='text/html'
            elif path=='/game.json': data=json.dumps(hydrate_illustrations(json.loads((HERE/'game-package.json').read_text()))).encode();mime='application/json'
            elif path in ('/client/memoir/story-game.mjs','/client/memoir/dom.mjs'):
                data=(ROOT/'apps/web'/path.lstrip('/')).read_bytes();mime='text/javascript'
            elif path=='/api/v1/memoir/agent/story-game-runtime': data=json.dumps(runtime_bundle()).encode();mime='application/json'
            elif path.startswith('/api/v1/memoir/agent/story-game-assets/'):
                digest,name=path.rsplit('/',2)[-2:];file=runtime_asset(digest,name)
                data=file.read_bytes();mime='image/png' if file.suffix=='.png' else 'audio/mpeg'
            else: self.send_error(404);return
        except (ValueError,OSError): self.send_error(404);return
        self.send_response(200);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(data)))
        self.end_headers();self.wfile.write(data)

    def end_headers(self):
        self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; media-src 'self' data:; connect-src "+("'self'" if args.application else "'none'")+"; frame-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Cache-Control', 'no-store')
        super().end_headers()

    def log_message(self, *args):
        pass


server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
server.daemon_threads = True
info = {'url': 'http://127.0.0.1:' + str(server.server_port) + '/', 'pid': os.getpid(), 'root': str(APP), 'synthetic': True}
if not args.no_metadata:
    (HERE / 'preview-server.json').write_text(json.dumps(info, indent=2) + '\n')
print(json.dumps(info), flush=True)
try:
    server.serve_forever()
finally:
    server.server_close()
