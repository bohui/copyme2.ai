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
    assert 'photograph' not in captured[0]['input']


@pytest.mark.parametrize('output',[[],[{'type':'web_search_call','id':'ws_x','status':'pending'}],
    [{'type':'web_search_call','id':'ws_x','status':'completed','action':{'sources':[]}}]])
def test_missing_search_evidence_fails_closed(monkeypatch,output):
    from apps.api.historical_news_provider import decode_discovery
    with pytest.raises(ValueError):decode_discovery({'id':'resp_test','status':'completed','output':output})


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
