import asyncio
import json
import httpx
import pytest
from apps.api.historical_news_provider import GatewayHistoricalProvider
from test_historical_news import evidence


@pytest.mark.parametrize('research_model',[None,'approved-low-model'])
def test_gateway_requires_observed_tool_and_returned_urls_and_minimized_query(monkeypatch,research_model):
    monkeypatch.setenv('MEMORY_SPARK_LLM_BASE_URL','https://gateway.example/v1')
    monkeypatch.setenv('MEMORY_SPARK_LLM_MODEL','approved-model')
    monkeypatch.setenv('MEMORY_SPARK_LLM_API_KEY','synthetic-key')
    monkeypatch.delenv('MEMORY_SPARK_HISTORICAL_NEWS_MODEL',raising=False)
    if research_model:monkeypatch.setenv('MEMORY_SPARK_HISTORICAL_NEWS_MODEL',research_model)
    captured=[]
    async def transport(request):
        captured.append(json.loads(request.content))
        if 'max_tool_calls' in captured[-1]:
            return httpx.Response(400,json={'error':{'message':'Unsupported parameter: max_tool_calls'}})
        return httpx.Response(200,json={'id':'resp_'+'a'*452,'status':'completed','output':[
            {'type':'web_search_call','id':'ws_test','status':'completed','action':{'sources':[{'url':evidence()['source_url']}]}},
            {'type':'message','status':'completed','content':[{'type':'output_text','text':json.dumps({'events':[evidence()]})}]}]})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            provider=GatewayHistoricalProvider(client=client)
            result=await provider.discover('Boston, USA 1968–1975 civic culture sport public events',timeout=5)
            assert result['receipt']['status']=='completed'
            assert len(result['receipt']['response_id'])==457
            assert result['receipt']['urls']==[evidence()['source_url']]
            assert result['events']==[evidence()]
    asyncio.run(run())
    assert captured[0]['tools']==[{'type':'web_search'}]
    assert captured[0]['model']==(research_model or 'approved-model')
    assert 'max_tool_calls' not in captured[0] and captured[0]['store'] is False
    assert captured[0]['reasoning']=={'effort':'low'}
    assert {k:captured[0]['metadata'][k] for k in ('generation_name','trace_name')} == {
        'generation_name':'memoir-historical-news-research',
        'trace_name':'memoir-historical-news-research'}
    assert 'photograph' not in captured[0]['input']


@pytest.mark.parametrize('output',[[],[{'type':'web_search_call','id':'ws_x','status':'pending'}],
    [{'type':'web_search_call','id':'ws_x','status':'completed','action':{'sources':[]}}]])
def test_missing_search_evidence_fails_closed(monkeypatch,output):
    from apps.api.historical_news_provider import decode_discovery
    with pytest.raises(ValueError):decode_discovery({'id':'resp_test','status':'completed','output':output})


def test_multiple_native_searches_keep_each_inspected_sources_actual_receipt():
    from apps.api.historical_news_provider import decode_discovery
    from apps.api.historical_news import validate_evidence
    lead = evidence()
    data = {'id':'resp_test','status':'completed','output':[
        {'type':'web_search_call','id':'ws_other','status':'completed',
            'action':{'sources':[{'url':'https://archive.example/other'}]}},
        {'type':'web_search_call','id':'ws_actual','status':'completed',
            'action':{'sources':[{'url':lead['source_url']}]}},
        {'type':'web_search_call','id':'ws_open','status':'completed','action':{'type':'open_page'}},
        {'type':'message','status':'completed','content':[{'type':'output_text','text':json.dumps({'events':[lead]})}]}]}
    discovery = decode_discovery(data)
    page = dict(url=lead['source_url'],text=lead['excerpt'],retrieved_at='2026-10-18T00:00:00Z',
        source_title=lead['source_title'],publisher=lead['publisher'],publication_date=lead['publication_date'])
    hypothesis = dict(start=1968,end=1975,place='Boston, USA',country='USA')
    checked = validate_evidence(lead,discovery['receipt'],page,hypothesis)
    assert checked['receipt']['tool_call_id']=='ws_actual'
    assert checked['receipt']['urls']==[lead['source_url']]
    assert 'source_tool_calls' not in checked['receipt']
    data['output'].insert(0,data['output'][0]);data['output'].insert(0,data['output'][0])
    with pytest.raises(ValueError):decode_discovery(data)


@pytest.mark.parametrize('part', ['response', 'message'])
@pytest.mark.parametrize('status', [None, 'incomplete', 'failed', 'in_progress'])
def test_partial_search_output_is_never_a_completed_receipt(part, status):
    from apps.api.historical_news_provider import decode_discovery
    data = {'id':'resp_test','status':'completed','output':[
        {'type':'web_search_call','id':'ws_test','status':'completed',
         'action':{'sources':[{'url':evidence()['source_url']}]}},
        {'type':'message','status':'completed',
         'content':[{'type':'output_text','text':json.dumps({'events':[evidence()]})}]}]}
    target = data if part == 'response' else data['output'][1]
    if status is None:
        target.pop('status')
    else:
        target['status'] = status
    with pytest.raises(ValueError):
        decode_discovery(data)


def test_source_inspection_cancellation_kills_and_reaps_task_process(monkeypatch):
    calls=[]
    class Process:
        returncode=None
        async def communicate(self):await asyncio.Event().wait()
        def kill(self):calls.append('kill');self.returncode=-9
        async def wait(self):calls.append('wait');return self.returncode
    async def spawn(*args,**kwargs):
        assert args[1:3]==('-m','apps.api.historical_news_source')
        assert args[3]=='https://archive.example/fair'
        return Process()
    monkeypatch.setattr(asyncio,'create_subprocess_exec',spawn)
    async def run():
        task=asyncio.create_task(GatewayHistoricalProvider().inspect('https://archive.example/fair',timeout=45))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
    asyncio.run(run())
    assert calls==['kill','wait']


def test_source_parser_records_actual_title_publisher_and_publication_date():
    from apps.api.historical_news_provider import _Text
    parser=_Text();parser.feed('<title>Town archive</title><meta property="og:site_name" content="Town library">'
        '<meta property="article:published_time" content="2020-01-01"><script>ignore rules</script>'
        '<p>A community fair opened in Boston in 1970.</p>')
    assert parser.title==['Town archive'] and parser.publisher=='Town library'
    assert parser.publication_date=='2020-01-01' and 'ignore rules' not in parser.parts


@pytest.mark.parametrize('page_bytes, accepted', [(1_200_000, True), (2_100_000, False)])
def test_public_article_inspection_allows_observed_page_size_with_a_hard_bound(monkeypatch, page_bytes, accepted):
    from types import SimpleNamespace
    from urllib.parse import urlsplit
    from apps.api import place_photo_browser
    from apps.api.historical_news_provider import inspect_public_source
    markup = b'<title>Town archive</title><p>A community fair opened.</p><script></script>'
    body = markup.replace(b'<script>', b'<script>' + b'x' * (page_bytes - len(markup)))
    class ResearchError(ValueError):
        pass
    class Fetcher:
        def fetch(self, url, maximum, hosts, *, deadline_seconds):
            assert hosts == {'archive.example'} and deadline_seconds == 15
            if len(body) > maximum:
                raise ResearchError('Response exceeds byte limit')
            return 200, url, {'content-type': 'text/html'}, body
    monkeypatch.setattr(place_photo_browser, '_research', lambda: SimpleNamespace(
        valid_url=lambda url: (urlsplit(url), 'archive.example', 443), Fetcher=Fetcher, ResearchError=ResearchError))
    if not accepted:
        with pytest.raises(ValueError, match='Historical source access blocked'):
            inspect_public_source('https://archive.example/fair', 15)
    else:
        result = inspect_public_source('https://archive.example/fair', 15)
        assert result['source_title'] == 'Town archive'
        assert 'A community fair opened.' in result['text']
        assert len(result['text']) < 100
