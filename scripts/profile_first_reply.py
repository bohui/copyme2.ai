"""Plan paired sequence profiles offline, or ingest their existing evidence.

The explicit legacy first-turn mode creates an anonymous account/project and
saves one synthetic turn. It is a dispatching diagnostic, never the default.
"""
import argparse
import asyncio
import json
import time
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from uuid import uuid4


TEST_TEXT = '我叫韩凤江'
TEST_CASES = {
    'zh-CN': {
        'name': TEST_TEXT,
        'story': '我叫韩凤江。小时候我和姐姐一起住在河边，父亲修自行车，母亲在院子里种豆子。我最记得放学后和姐姐一起给豆子浇水。',
    },
    'en-AU': {
        'name': 'My name is Avery.',
        'story': 'My name is Avery. As a child I lived beside a river with my sister. Dad repaired bicycles and Mum grew beans in the yard. I remember watering the beans with my sister after school.',
    },
}


def report(**values):
    print(json.dumps(values, ensure_ascii=False), flush=True)


async def first_turn(origin, timeout, *, language='zh-CN', case='name'):
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
            json={'mode': 'self', 'language': language})
        report(kind='synthetic_test_identity', user_id=auth['user']['id'], project_id=project['id'])
        stage = 'first_turn'
        started = time.perf_counter()
        seen = {}
        async with asyncio.timeout(timeout), client.stream('POST', api + '/agent/turn',
            headers={**headers, 'Accept': 'application/x-ndjson'},
            json={'project_id': project['id'], 'client_turn_id': str(uuid4()),
                  'text': TEST_CASES[language][case], 'first_reply_localization': True}) as response:
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
                    report(kind='first_turn_summary', language=language, case=case, timings=seen,
                        measurement='HTTP events received; browser paint is not measured')
                    return
        raise RuntimeError('Stream ended before conversation_saved')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', nargs='?', default='plan', choices=['plan', 'blind', 'compare', 'first-turn'])
    parser.add_argument('--plan-file', type=str)
    parser.add_argument('--results', type=str)
    parser.add_argument('--receipts', type=str)
    parser.add_argument('--reviews', type=str)
    parser.add_argument('--scenario', action='append')
    parser.add_argument('--samples', type=int, default=1)
    parser.add_argument('--variants', type=str)
    parser.add_argument('--origin', default='http://localhost:3010')
    parser.add_argument('--language', choices=sorted(TEST_CASES), default='zh-CN',
        help='Language of the synthetic first-turn project and narration')
    parser.add_argument('--case', choices=['name', 'story'], default='name',
        help='Synthetic name-only introduction or introduction with a childhood memory')
    parser.add_argument('--timeout', type=float, default=120,
        help='HTTP timeout and total first-turn deadline in seconds')
    args = parser.parse_args(argv)
    if args.mode != 'first-turn':
        from pathlib import Path
        from scripts import issue53_profile_sequences as sequences
        def read(path, default):
            return json.loads(Path(path).read_text()) if path else default
        if args.mode == 'plan':
            result = sequences.plan(samples=args.samples, scenario=args.scenario, variants=read(args.variants, None))
        else:
            if not args.plan_file:
                parser.error('--plan-file is required for ingestion')
            planned = read(args.plan_file, None)
            results = read(args.results, [])
            if args.mode == 'blind':
                result = sequences.blind_packets(planned, results, read(args.receipts, {}))
            else:
                result = sequences.compare(planned, results, read(args.receipts, {}), read(args.reviews, {}),
                    directory=Path(args.receipts).parent if args.receipts else Path.cwd())
        report(**result)
        return 0 if args.mode != 'compare' else 1
    if not 0 < args.timeout < float('inf'):
        parser.error('--timeout must be a positive finite number')
    try:
        asyncio.run(first_turn(args.origin, args.timeout, language=args.language, case=args.case))
    except Exception as error:
        # Provider/auth exception text can include private headers or output.
        report(kind='profile_failed', failure_class=type(error).__name__)
        raise SystemExit(1) from None


if __name__ == '__main__':
    # Direct script execution and module imports share the same offline-first CLI.
    raise SystemExit(main())
