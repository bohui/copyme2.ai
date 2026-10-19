"""Production orchestration with injected external boundaries and isolated state."""
from contextlib import asynccontextmanager
from copy import deepcopy
import json
from types import SimpleNamespace

import httpx


async def photo(item, adapter, budget, max_bytes):
    """Configured discovery leads + inspected HTML through production photo parsing.

    The provider boundary may be catalogue/browser/native search. Native model
    search is never required when the configured provider supplied the leads.
    """
    from apps.api.place_photo_browser import _source_items
    from apps.api import place_photos
    from apps.api.historical_news import canonical_url
    query = item['task']['public_query']
    witnesses = dict(provider=None, discovery=None, inspected_sources=[])
    reply = await budget.dispatch(adapter, dict(item_id=item['id'], skill=item['skill'], kind='discovery',
        input=query), require_completion=False)
    discovery = reply['output']
    if (not isinstance(discovery, dict) or discovery.get('status') != 'completed'
        or not discovery.get('provider') or not isinstance(discovery.get('urls'), list)):
        raise LookupError('photo_discovery_receipt_unavailable')
    witnesses.update(provider=discovery['provider'], discovery=deepcopy(discovery))
    candidates = []
    for url in list(dict.fromkeys(discovery['urls']))[:8]:
        url = canonical_url(url)
        inspected = await budget.dispatch(adapter, dict(item_id=item['id'], skill=item['skill'], kind='inspect',
            input=dict(url=url)), require_completion=False)
        page = inspected['output']
        if (not isinstance(page, dict) or canonical_url(page.get('url')) != url
            or not isinstance(page.get('html'), str) or len(page['html'].encode()) > max_bytes):
            raise LookupError('photo_inspected_source_unavailable')
        witnesses['inspected_sources'].append(deepcopy(page))
        candidates += _source_items(page['html'], url, query['place'], query['period'])
        if item['case'] == 'relaxed-match' and not candidates:
            relaxed = _source_items(page['html'], url, query['place'], place_photos.ANY_PHOTO_DATE)
            candidates += [{**c, 'requested_period': query['period'], 'period_match': 'any_time'} for c in relaxed]
    result = place_photos.filter_place_photos(candidates,
        place_photos.ANY_PHOTO_DATE if item['case'] == 'relaxed-match' else query['period'])
    if item['case'] == 'ranking':
        rank = getattr(place_photos, 'rank_place_photos', None)
        if rank is None: raise LookupError('photo_ranking_dependency_pr88')
        result = rank(result, query['period'], None, 1983)
    return dict(items=result), witnesses


async def history(item, adapter, budget):
    from apps.api.historical_news import HistoricalResearch, public_queries
    from apps.api.prompt_artifact import load_prompt_artifact, prompt_path
    hypothesis = dict(start=2000, end=2000, place='Sydney, Australia', country='Australia', tentative=False)
    witnesses = dict(queries=[], source_reads=[], completed_source_reads=[], inspected_pages=[])

    class Boundary:
        async def discover(self, query, **kwargs):
            if query not in public_queries(hypothesis): raise ValueError('private_query_rejected')
            witnesses['queries'].append(query)
            instructions = load_prompt_artifact(prompt_path('memoir/skills/memoir-historical-news-research/discovery'))
            instructions = instructions.replace('{{query}}', query)
            request = dict(item_id=item['id'], skill=item['skill'], kind='discovery',
                           instructions=instructions, input=dict(public_query=query))
            try:
                reply = await budget.dispatch(adapter, request, require_completion=False)
                return reply['output']
            except Exception:
                raise OSError('controlled_discovery_unavailable') from None

        async def inspect(self, url, **kwargs):
            witnesses['source_reads'].append(url)
            try:
                reply = await budget.dispatch(adapter, dict(item_id=item['id'], skill=item['skill'],
                    kind='inspect', input=dict(url=url)), require_completion=False)
                witnesses['completed_source_reads'].append(url)
                witnesses['inspected_pages'].append(reply['output'])
                return reply['output']
            except Exception:
                raise OSError('controlled_source_unavailable') from None

    result = await HistoricalResearch(Boundary()).run(hypothesis)
    return result, witnesses


async def composer(item, adapter, budget):
    """Real progressive orchestration; in-memory checkpoint I/O is explicit scope."""
    from apps.api.lifetime_memory_composer import _compose
    from apps.api.lifetime_memory_lane_engine import BoundedLaneInput, lane_contract
    from scripts.memoir_skill_scenarios import composer_page
    checkpoints, phases, outputs = {}, [], []
    page = deepcopy(item['task']['page'])
    # The controlled orchestration uses the application's synthetic byte model
    # budget. No environment, provider settings or persisted project is changed.
    from unittest.mock import patch
    from apps.api.lifetime_memory_contracts import ContextBudget
    controlled_budget = ContextBudget(model='synthetic-byte-bpe', context_window=131072,
        input_budget=98304, output_headroom=16384, framing_headroom=2048)

    class Broker:
        async def rpc(self, name, **payload):
            if name == 'read_memoir_checkpoint': return deepcopy(checkpoints.get(payload['p_key']))
            if name == 'save_memoir_checkpoint':
                checkpoints[payload['p_key']] = deepcopy(payload['p_value'])
                return True
            if name == 'record_lifetime_lane_output': return True
            raise ValueError('unexpected_isolated_composer_rpc')

    class Publisher:
        @asynccontextmanager
        async def guard(self, fence):
            yield

    async def external(request):
        bounded = BoundedLaneInput.model_validate(json.loads(request.content)['bounded_lane'])
        instructions, schema = lane_contract(bounded.phase, item['locale'], batch=True)
        phases.append(bounded.phase)
        reply = await budget.dispatch(adapter, dict(item_id=item['id'], skill=item['skill'],
            phase=bounded.phase, instructions=instructions, schema=schema, input=json.loads(bounded.packet)))
        return httpx.Response(200, json=dict(reply=json.dumps(reply['output'], ensure_ascii=False)))

    worker = SimpleNamespace(broker=Broker(), worker_url='https://controlled.invalid', worker_secret='synthetic',
        worker_transport=httpx.MockTransport(external), lane_publisher=Publisher())
    # Select a supported production budget without changing process settings.
    with patch('apps.api.lifetime_memory_composer.lane_model_budget', return_value=controlled_budget):
        original = deepcopy(page)
        first = await _compose(page, worker)
        if original != page: raise ValueError('composer_mutated_input')
        outputs.append(first)
        if item['case'] == 'empty-checkpoint':
            if first['status'] not in {'collecting', 'no_authorized_evidence', 'insufficient_context'}:
                raise ValueError('empty_checkpoint_invented_prose')
        else:
            if first['status'] != 'ready': raise ValueError('composer_checkpoint_incomplete')
            if item['case'] in {'new-evidence', 'preserve-unchanged', 'corrected-event', 'withdrawal'}:
                unchanged_event = page['batch']['events'][1]['id']
                preserved = [s for s in first['sections'] if 'block' in s and s['event_ids'] == [unchanged_event]]
                if not preserved: raise ValueError('independent_passage_required')
                second_page = composer_page(item['locale'], first)
                if item['case'] == 'corrected-event':
                    original = second_page['batch']['new_messages'][0]
                    correction = item['task']['next_checkpoint']['correction']
                    original.update(text=correction, char_start=0, char_end=len(correction), original_length=len(correction))
                    second_page['batch']['new_messages'] = [original]
                    second_page['batch']['sources'] = [*page['batch']['sources'], original]
                    second_page['batch']['events'][0]['source_refs'] = [dict(source_id=original['id'], version=1,
                        quote=correction, char_start=0, char_end=len(correction))]
                if item['case'] == 'withdrawal':
                    second_page['batch']['events'] = [page['batch']['events'][1]]
                    retained = {r['source_id'] for r in page['batch']['events'][1]['source_refs']}
                    second_page['batch']['sources'] = [s for s in page['batch']['sources'] if s['id'] in retained]
                    second_page['batch']['new_messages'] = []
                second = await _compose(second_page, worker)
                outputs.append(second)
                if second['status'] != 'ready': raise ValueError('composer_update_incomplete')
                blocks = {s['id']: s for s in second['sections'] if 'block' in s}
                if any(s['id'] not in blocks or s['block'] != blocks[s['id']]['block'] for s in preserved):
                    raise ValueError('composer_rewrote_supported_passage')
                if item['case'] == 'withdrawal':
                    allowed_sources = {s['id'] for s in second_page['batch']['sources']}
                    if any(ref['source_id'] not in allowed_sources for s in second['sections'] for ref in s['source_refs']):
                        raise ValueError('composer_retained_withdrawn_evidence')
                else:
                    new_sources = {s['id'] for s in second_page['batch']['new_messages']}
                    if not any(ref['source_id'] in new_sources for s in second['sections'] for ref in s['source_refs']):
                        raise ValueError('composer_lost_new_evidence')
    return dict(checkpoints=outputs), dict(phases=phases, checkpoint_count=len(outputs),
        source_pages=[page] + ([second_page] if item['case'] in {'new-evidence', 'preserve-unchanged', 'corrected-event', 'withdrawal'} else []),
        storage='isolated_in_memory', persisted_canonical_state=False, browser_observed=False)
