"""Canonical interview publication and real research with controlled public sources."""
import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest
from starlette.requests import ClientDisconnect

from apps.api.codex_runtime import CodexRuntime
from apps.api.historical_news import HistoricalResearch, public_clue
from apps.api.lifetime_memory_runtime import lifetime_http_turn
from test_historical_news import evidence, receipt, news_proposal
from test_lifetime_memory_engine import fixture, valid_reply
from test_lifetime_memory_transport import Publisher, SCOPE, no_disconnect
from test_lifetime_turn_progress import Storage, Lease


class NewsStorage(Storage):
    def __init__(self):
        super().__init__()
        self.source['text'] = 'I was born in Boston, USA, in 1960.'
        self.news = {'enabled': True, 'project_id': 'p', 'context_revision': 'rev-1', 'clues': []}
        self.claimed = False
        self.finished = None
        self.saved = 0
        self.closed = 0
        self.client = SimpleNamespace(close=self.close)

    def close(self):
        self.closed += 1

    def historical_news_basis(self, project):
        return {'sources': [deepcopy(self.source)], 'events': [],
                'news_snapshot': {'source_sequence': 1, 'context_revision': 'rev-1'}}

    def begin_historical_news(self, project, hypothesis, snapshot):
        assert (hypothesis['start'], hypothesis['end']) == (1968, 1975)
        assert snapshot['context_revision'] == 'rev-1'
        if self.claimed:
            return None
        self.claimed = True
        self.hypothesis = hypothesis
        return {'id': 'controlled-job'}

    def finish_historical_news(self, project, job, result):
        self.finished = deepcopy(result)
        self.news['clues'] = [{**clue, 'status': 'ready', 'project_id': project,
            'context_revision': 'rev-1', 'relevance': self.hypothesis} for clue in result['clues']]
        return True

    def lifetime_rpc(self, name, **kwargs):
        result = super().lifetime_rpc(name, **kwargs)
        if name == 'read_lifetime_interview_context':
            result['historical_news'] = deepcopy(self.news)
        if name == 'commit_lifetime_turn':
            self.saved += 1
            chosen = next(c for c in kwargs['p_plan']['candidates'] if c['id'] == kwargs['p_plan']['chosen_id'])
            if chosen['context'].get('historical_clue_id'):
                result['interview']['historical_context'] = public_clue(self.news['clues'][0])
        return result


@pytest.fixture
def interview(monkeypatch, tmp_path):
    monkeypatch.setenv('MEMORY_SPARK_COLLECTOR_MODEL', 'synthetic-byte-bpe')
    monkeypatch.setenv('MEMORY_SPARK_HISTORICAL_NEWS', '1')
    monkeypatch.setattr('apps.api.recall.storage_recall_status', lambda *args: {'payment_required': False})
    packet = json.loads(fixture()[0].packet)
    monkeypatch.setattr('apps.api.lifetime_memory_service.LifetimeMemoryService.assemble', lambda self, **kwargs: packet)
    monkeypatch.setattr('apps.api.lifetime_memory_publication.TransactionalPublication', lambda *a, **kw: Publisher())
    storage = NewsStorage()
    runtime = CodexRuntime(home_root=tmp_path, worker_url='http://controlled.invalid')
    state = SimpleNamespace(leased=False, final_sent=False, select_news=False)

    @asynccontextmanager
    async def lease(*args, **kwargs):
        assert not state.leased
        state.leased = True
        try:
            yield Lease()
        finally:
            state.leased = False

    async def collector(**kwargs):
        if state.select_news:
            assert kwargs['interview_context']['historical_news']['clues']
            output = news_proposal()
            output['plan']['candidates'][0]['context']['historical_clue_id'] = storage.news['clues'][0]['id']
            raw = json.dumps(output)
        else:
            raw = valid_reply()
        return {'thread_id': 'controlled-thread', 'reply': raw}

    monkeypatch.setattr(runtime, '_storage_lease', lease)
    monkeypatch.setattr(runtime, '_worker_turn', collector)

    async def respond(streaming, *, fail=None):
        messages = []
        response = await lifetime_http_turn(runtime, storage, storage.source['text'],
            accept='application/x-ndjson' if streaming else 'application/json', options={'project_id': 'p'})

        async def send(message):
            if message['type'] == 'http.response.body' and (
                fail == 'terminal' and (not streaming or b'"type":"result"' in message.get('body', b''))
                or fail == 'final' and not message.get('more_body', False)):
                raise OSError('controlled response delivery failure')
            messages.append(message)
            if message['type'] == 'http.response.body' and not message.get('more_body', False):
                state.final_sent = True

        await response(SCOPE, no_disconnect, send)
        raw = b''.join(m.get('body', b'') for m in messages)
        if streaming:
            return next(json.loads(line)['data'] for line in raw.splitlines() if json.loads(line)['type'] == 'result')
        return json.loads(raw)

    return runtime, storage, state, respond


@pytest.mark.parametrize('streaming', [False, True])
def test_saved_reply_releases_lease_before_research_and_later_turn_consumes_clue(interview, streaming):
    runtime, storage, state, respond = interview

    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()

        class Provider:
            async def discover(self, query, *, timeout):
                assert state.final_sent and storage.saved and not state.leased
                if not entered.is_set():
                    assert storage.closed == 0
                assert '1968–1975' in query and storage.source['id'] not in query
                entered.set()
                await release.wait()
                return {'receipt': receipt(), 'events': [evidence()]}

            async def inspect(self, url, *, timeout):
                return {'url': url, 'text': evidence()['excerpt'], 'source_title': 'Town archive',
                    'publisher': 'Town library', 'publication_date': '2020-01-01',
                    'retrieved_at': '2026-10-15T00:00:00Z'}

        runtime._news_engine = HistoricalResearch(Provider())
        first = asyncio.create_task(respond(streaming))
        try:
            await asyncio.wait_for(entered.wait(), 1)
            assert not first.done() and storage.finished is None
            # Research holds neither the conversation lease nor runtime lock.
            second = await asyncio.wait_for(respond(streaming), 1)
            assert second['conversation_saved'] and 'historical_context' not in second
            release.set()
            result = await first
            assert result['conversation_saved'] and 'historical_context' not in result
            assert storage.finished['status'] == 'ready' and len(storage.news['clues']) == 1
            state.select_news = True
            later = await respond(streaming)
            assert later['historical_context']['source_url'] == evidence()['source_url']
            assert later['historical_context']['event_start'] == 1970
            assert storage.closed == 3
        finally:
            release.set()
            await asyncio.gather(first, return_exceptions=True)

    asyncio.run(scenario())


@pytest.mark.parametrize('situation', ['disabled', 'missing_context', 'provider_failure', 'storage_failure', 'revalidation_failure'])
def test_optional_research_never_breaks_a_saved_reply(interview, monkeypatch, situation):
    runtime, storage, state, respond = interview
    calls = []

    class Provider:
        async def discover(self, *args, **kwargs):
            calls.append(True)
            raise OSError('controlled provider failure')

    runtime._news_engine = HistoricalResearch(Provider())
    if situation == 'disabled':
        monkeypatch.setenv('MEMORY_SPARK_HISTORICAL_NEWS', '0')
    elif situation == 'missing_context':
        monkeypatch.setattr(storage, 'historical_news_basis', lambda *args: {'sources': [], 'events': []})
    elif situation == 'storage_failure':
        def failed(*args):
            raise OSError('private storage exception must not be published')
        monkeypatch.setattr(storage, 'historical_news_basis', failed)
    elif situation == 'revalidation_failure':
        storage.news['needs_revalidation'] = True
        def failed(*args):
            raise OSError('optional revalidation failed')
        monkeypatch.setattr(storage, 'revalidate_historical_news', failed, raising=False)
    result = asyncio.run(respond(True))
    assert result['conversation_saved'] and result['reply']
    assert not state.leased and storage.closed == 1
    assert len(calls) == (2 if situation in {'provider_failure', 'revalidation_failure'} else 0)


@pytest.mark.parametrize('streaming', [False, True])
@pytest.mark.parametrize('failure', ['terminal', 'final'])
def test_failed_delivery_releases_resources_without_external_research(interview, streaming, failure):
    runtime, storage, state, respond = interview
    calls = []

    class Provider:
        async def discover(self, *args, **kwargs):
            calls.append(True)
            raise OSError('must not perform external research')

    runtime._news_engine = HistoricalResearch(Provider())
    with pytest.raises(ClientDisconnect if streaming else OSError):
        asyncio.run(respond(streaming, fail=failure))
    assert storage.saved == 1
    assert not state.leased and storage.closed == 1
    assert calls == []
