"""Measure the scenario paths shared by both harness arms at controlled boundaries."""
import json
import os
import time
from pathlib import Path

from scripts.memoir_skill_eval_application import ControlledApplication
from scripts.memoir_skill_eval_suite import run
from scripts.run_memoir_live_skills import LiveProvider, native_search, save


class Proposals:
    def __init__(self, items):
        self.items = items

    async def call(self, request):
        item = self.items[request['item_id']]
        if item['skill'] == 'memoir-family-tree':
            raise LookupError('canonical_family_runner_unwired')
        if item['skill'] == 'memoir-memory-context':
            from test_skill_eval_suite import profile_output
            output = profile_output(item)
        else:
            from test_skill_eval_review_regressions import timeline_output
            output = timeline_output(item) if item['gold']['facts']['min_events'] else {'events': []}
        return dict(output=output, response_id='fixture-proposal', model='synthetic-model', usage=None)


class Composer:
    async def call(self, request):
        from controlled_composer_review import controlled_review
        from test_progressive_composer import draft_all
        payload = request['input']['payload']
        phase = request['phase']
        if phase == 'prepare':
            partition = payload['partition']
            output = dict(event_id=partition['id'], context='Original bicycle memories.',
                          source_refs=partition['source_refs'])
        elif phase == 'draft':
            output = draft_all(payload)
        else:
            output = controlled_review(payload)
        return dict(output=output, response_id='fixture-composer', model='synthetic-model', usage=None)


class Photos:
    def __init__(self, items):
        self.items = items

    async def call(self, request):
        item = self.items[request['item_id']]
        case = item['case']
        if case == 'unavailable-provider':
            raise LookupError('photo_service_unavailable')
        place = item['task']['public_query']['place']
        sources = item['task'].get('ranking_fixture')
        if not sources:
            photo = dict(**{'@type': 'Photograph'},
                name=place + ' archive',
                contentLocation=dict(name='Paris' if case == 'wrong-place' else place),
                contentUrl='https://images.example/street.jpg',
                creator=dict(name='Synthetic Photographer'),
                license='https://creativecommons.org/licenses/by/4.0/')
            if case != 'unverified-lead':
                photo['dateCreated'] = '1971-10-01' if case == 'relaxed-match' else '1983-10-01'
            sources = [dict(url='https://archive.example/photo', photo=photo)]
        if request['kind'] == 'discovery':
            output = dict(provider='configured_catalogue', status='completed', urls=[s['url'] for s in sources])
        else:
            url = request['input']['url']
            source = next(s for s in sources if s['url'] == url)
            output = dict(url=url, html=f'<title>{place} street archive</title><script type="application/ld+json">'
                          + json.dumps(source['photo'], ensure_ascii=False) + '</script>')
        return dict(output=output, response_id=None, model=None, usage=None)


class LiveProposals:
    def __init__(self, provider, items):
        self.provider, self.items = provider, items

    async def call(self, request):
        item = self.items[request['item_id']]
        if item['skill'] == 'memoir-family-tree' and item['phase'] == 'integration':
            raise LookupError('canonical_family_runner_unwired')
        value, response = await self.provider.call(
            request['item_id'] + '/' + request.get('phase', 'proposal'), request['skill'],
            request['instructions'], request['input'], request['schema'])
        return dict(output=value, response_id=response['id'], model=response.get('model'), usage=response.get('usage'))


class StoryApplication(ControlledApplication):
    def supports(self, item):
        return item['skill'] == 'memoir-story-game'


async def run_skills(planned, destination, benchmark, *, discoveries, gateway, key, max_calls):
    from test_skill_eval_workflows import HistoryFixture
    items = {item['id']: item for item in planned['items']}
    browser = os.environ.get('MEMOIR_BROWSER_URL')
    application = StoryApplication(browser_url=browser,
        browser_executable=os.environ.get('MEMOIR_BROWSER_EXECUTABLE', '/usr/bin/chromium'),
        apple_fixture=os.getenv('MEMOIR_TEST_POSTGRES_BACKEND') == 'apple-container')
    directory = Path(destination).with_suffix('.skills')
    live = None
    if gateway:
        provider_root = Path(destination).with_suffix('.provider')
        provider_root.mkdir(mode=0o700)
        config = dict(MEMORY_SPARK_LLM_BASE_URL=gateway, MEMORY_SPARK_LLM_API_KEY=key,
                      MEMORY_SPARK_LLM_MODEL=benchmark['model'],
                      MEMORY_SPARK_LLM_REASONING_EFFORT=benchmark['effort'])
        live = LiveProvider(config, {'calls': []}, provider_root, timeout=120, max_calls=max_calls,
                            deadline=time.monotonic() + 3600, effort=benchmark['effort'])
    if items:
        # The same shared path is timed once. Production validators grade the
        # response, and service and application boundaries use explicit fixtures.
        result = await run(planned, directory, skill=LiveProposals(live, items) if live else Proposals(items),
            history_provider=HistoryFixture(), photo_provider=Photos(items),
            composer_provider=LiveProposals(live, items) if live else Composer(), application=application,
            max_skill_calls=640, seconds=3600, timeout=120)
        for row in result['results']:
            if live and row['skill'] == 'memoir-family-tree' and row['phase'] == 'proposal':
                row['evidence_mode'] = 'live_family_proposal_only'
            if live and row['skill'] in {'memoir-author-timeline', 'memoir-memory-context', 'memoir-composer'}:
                if row['evidence_mode'] != 'controlled_disposable_application':
                    row['evidence_mode'] = 'live_shared_model'
            benchmark['unchanged_skills'].append({key: row[key] for key in (
                'case_id', 'skill', 'locale', 'elapsed_ms', 'execution', 'reason', 'contract',
                'canonical_delivery', 'evidence_mode')})
    for case in discoveries:
        started = time.monotonic()
        row = dict(case_id=case['id'], skill=case['skill'], locale=case['locale'],
                   execution='unavailable', reason='live_public_search_required', canonical_delivery=False,
                   evidence_mode='native_public_search')
        if live:
            try:
                await native_search(live, case['skill'])
                row.update(execution='completed', reason='')
            except Exception as error:
                row['reason'] = type(error).__name__
                if isinstance(error, ValueError):
                    row['reason'] = str(error)[:100]
        row.update(elapsed_ms=round((time.monotonic() - started) * 1000, 2),
                   contract={'status': 'pass' if row['execution'] == 'completed' else 'unavailable'})
        benchmark['unchanged_skills'].append(row)
    if live:
        benchmark['shared_provider_calls'] = live.receipt['calls']
        benchmark['live_dispatches'] += len(live.receipt['calls'])
    save(destination, benchmark)
