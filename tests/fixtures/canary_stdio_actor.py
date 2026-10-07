"""Fixed controlled actor double. Never imports installed gateway or keys."""
import hashlib
import json
import os
from pathlib import Path
import sys

control = json.loads(Path(sys.argv[1]).read_text())
mode = control.get('mode')
count = 0
for line in sys.stdin:
    request = json.loads(line)
    op = request['op']
    if mode == 'eof' or (mode == 'response_eof' and op == 'responses'): break
    reply = {key: request[key] for key in ('version', 'id', 'op')}
    if mode == 'bad_id': reply['id'] = 'other'
    receipt = {'guarded_send_entries': count, 'control_auth_verified': True,
               'cleanup': {'closed': op == 'stop', 'active_finished': True}}
    if op == 'init':
        assert request['consumer_authorization'] == 'Bearer synthetic-consumer-only'
        reply.update({key: request[key] for key in ('challenge', 'run_id', 'source_revision', 'source_sha256', 'account_binding')})
        reply.update(actor_pid=os.getpid(), consumer_binding=hashlib.sha256(b'controlled-consumer').hexdigest(),
                     boundary_mode='controlled_fixture')
        if mode == 'bad_challenge': reply['challenge'] = 'wrong'
        if mode == 'wrong_account': reply['account_binding'] = 'c' * 64
    elif op == 'responses':
        assert request['headers']['authorization'] == 'Bearer synthetic-consumer-only'
        count += 1
        receipt['guarded_send_entries'] = count
        reply.update(status=200, headers={'content-type': 'text/event-stream'}, body='data: '+json.dumps({
            'type':'response.completed','response':{'id':'resp_controlled','model':'gpt-5.6-luna',
                'usage':{'input_tokens':1,'output_tokens':1}}})+'\n\n')
        if mode == 'response_bad_id': reply['id'] = 'wrong'
        if mode == 'response_secret': reply['body'] = 'synthetic-consumer-only'
        if mode == 'response_extra_field': reply['unapproved'] = True
        if mode == 'response_wrong_type': reply['status'] = '200'
    reply['receipt'] = receipt
    raw = json.dumps(reply)
    if mode == 'duplicate_json_key' and op == 'init': raw = raw[:-1] + ',"op":"init"}'
    print(raw, flush=True)
    if op == 'stop': break
