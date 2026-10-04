"""Offline URL-policy checks against Node's browser-equivalent WHATWG parser."""
import argparse
import json
import os
from pathlib import Path
import runpy
import subprocess
from urllib.parse import urlsplit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--node', default='node')
    args = parser.parse_args()
    base = 'http://127.0.0.1:52101/path/current'
    # These are parser inputs only. No sockets or requests are created.
    accepted = ['/memoir', './next', '../memoir', '?page=2', '#draft',
                'memoir/interview', 'http://127.0.0.1:52101/final',
                '//127.0.0.1:52999/sink', 'https://cdn.jsdelivr.net/example.js']
    rejected = ['///127.0.0.1:52999/sink', '////127.0.0.1:52999/sink',
                'http:///127.0.0.1:52999/sink', 'http:////127.0.0.1:52999/sink',
                'http:/127.0.0.1:52999/sink', 'http:127.0.0.1:52999/sink',
                chr(92) * 2 + '127.0.0.1:52999/sink',
                '\t//127.0.0.1:52999/sink', 'http://127.0.0.1:52999/a b',
                'http://[invalid', 'javascript:alert(1)']
    os.environ['MEMOIR_BROWSER_URL'] = base.rsplit('/path', 1)[0]
    os.environ.pop('MEMORY_SPARK_API_ORIGIN', None)
    guard = runpy.run_path(str(Path(__file__).with_name('browser_network_guard.py')))
    script = """const fs = require('fs');
        const {base, headers} = JSON.parse(fs.readFileSync(0, 'utf8'));
        process.stdout.write(JSON.stringify(headers.map(value => {
          try { return new URL(value, base).origin; } catch { return null; }
        })));"""
    origins = json.loads(subprocess.check_output([args.node, '-e', script],
        input=json.dumps({'base': base, 'headers': accepted + rejected}), text=True))
    failures = []
    for index, location in enumerate(accepted + rejected):
        target = guard['redirect_destination'](base, location, 'GET')
        if index < len(accepted):
            parts = urlsplit(target) if target is not None else None
            origin = f'{parts.scheme}://{parts.netloc}' if parts else None
            if origin != origins[index]:
                failures.append({'case': index, 'kind': 'accepted origin differs from WHATWG'})
        elif target is not None:
            failures.append({'case': index, 'kind': 'ambiguous/unsupported Location was not rejected'})
    print(json.dumps({'cases': len(origins), 'accepted': len(accepted),
                      'rejected': len(rejected), 'failures': failures,
                      'mode': 'offline parsers only, no network'}))
    assert not failures


if __name__ == '__main__':
    main()
