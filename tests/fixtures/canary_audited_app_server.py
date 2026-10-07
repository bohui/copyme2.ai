"""Controlled external protocol with safe routing/correlation observations."""
import json
import os
from pathlib import Path
import runpy
import sys

control = json.loads(Path(sys.argv[1]).read_text())
audit = Path(control['audit'])

def record(value):
    with audit.open('a') as stream:
        stream.write(json.dumps(value) + '\n')

record({'argv': sys.argv[2:],
        'key_is_synthetic': os.environ.get('MEMORY_SPARK_LLM_API_KEY') == 'synthetic-only'})
original = sys.stdin

class ObservedInput:
    def __iter__(self):
        for line in original:
            message = json.loads(line)
            params = message.get('params', {})
            if message.get('method') in {'thread/start', 'thread/resume'}:
                record({'method': message['method'], 'model': params.get('model')})
            if message.get('method') == 'turn/start':
                record({'method': message['method'],
                        'metadata': params.get('responsesapiClientMetadata'),
                        'effort': params.get('effort')})
            yield line

sys.stdin = ObservedInput()
runpy.run_path(str(Path(__file__).with_name('issue6_controlled_app_server.py')))
