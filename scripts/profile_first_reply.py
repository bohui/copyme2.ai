"""Measure first-response latency through the current HTTP conversation API.

Creates a fresh anonymous test account/project and saves one synthetic turn.
Output contains timings and test identifiers, never credentials or reply text.
"""
import argparse
import asyncio
import json
import time
from uuid import uuid4


TEST_TEXT = '我叫韩凤江'


def report(**values):
    print(json.dumps(values, ensure_ascii=False), flush=True)


async def first_turn(origin, timeout):
    import httpx

    stage = 'config'
    async with httpx.AsyncClient(timeout=timeout) as client:
        async def request(method, url, **kwargs):
            response = await client.request(method, url, **kwargs)
            if not response.is_success:
                report(stage=stage, http_status=response.status_code)
                raise RuntimeError('Profiling request failed')
            return response.json()

        api = origin.rstrip('/') + '/api/v1/memoir'
        config = await request('GET', api + '/agent/config')
        stage = 'anonymous_signup'
        auth = await request('POST', config['supabase_url'] + '/auth/v1/signup',
            headers={'apikey': config['supabase_publishable_key']}, json={'data': {}})
        headers = {'Authorization': 'Bearer ' + auth['access_token']}
        stage = 'create_project'
        project = await request('POST', api + '/projects', headers=headers,
            json={'mode': 'self', 'language': 'zh-CN'})
        report(kind='synthetic_test_identity', user_id=auth['user']['id'], project_id=project['id'])
        stage = 'first_turn'
        started = time.perf_counter()
        seen = {}
        async with asyncio.timeout(timeout), client.stream('POST', api + '/agent/turn',
            headers={**headers, 'Accept': 'application/x-ndjson'},
            json={'project_id': project['id'], 'client_turn_id': str(uuid4()),
                  'text': TEST_TEXT, 'first_reply_localization': True}) as response:
            if not response.is_success:
                report(stage=stage, http_status=response.status_code)
                raise RuntimeError('First turn failed')
            seen['headers_s'] = round(time.perf_counter() - started, 3)
            async for line in response.aiter_lines():
                if not line:
                    continue
                event = json.loads(line)
                kind = event.get('type')
                seconds = round(time.perf_counter() - started, 3)
                if kind == 'text_delta' and event.get('text'):
                    seen.setdefault('first_visible_text_s', seconds)
                label = kind
                if kind == 'progress':
                    data = event.get('data') or {}
                    label = 'progress:' + str(data.get('id')) + ':' + str(data.get('status'))
                if label not in seen:
                    seen[label] = seconds
                    report(kind='http_event', event=label, elapsed_s=seconds)
                if kind == 'error':
                    raise RuntimeError('First turn stream failed')
                if kind == 'conversation_saved':
                    report(kind='first_turn_summary', timings=seen,
                        measurement='HTTP events received; browser paint is not measured')
                    return
        raise RuntimeError('Stream ended before conversation_saved')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['first-turn'])
    parser.add_argument('--origin', default='http://localhost:3010')
    parser.add_argument('--timeout', type=float, default=120,
        help='HTTP timeout and total first-turn deadline in seconds')
    args = parser.parse_args()
    if not 0 < args.timeout < float('inf'):
        parser.error('--timeout must be a positive finite number')
    try:
        asyncio.run(first_turn(args.origin, args.timeout))
    except Exception as error:
        # Provider/auth exception text can include private headers or output.
        report(kind='profile_failed', failure_class=type(error).__name__)
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
