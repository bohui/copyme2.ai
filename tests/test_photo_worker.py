import asyncio
import json

from fastapi import HTTPException
from fastapi.testclient import TestClient
import httpx
import pytest

from apps.api import place_photo_pages as pages
from apps.api import place_photo_transport as transport
from apps.api.photo_worker_service import create_photo_worker
from apps.api.main import create_app
from apps.api.store import MemoryStore
from apps.api.place_photo_repository import PhotoRepository
from test_llm_place_photos import search_world


@pytest.mark.parametrize('remote_worker',[False,True])
@pytest.mark.parametrize('stream',[False,True])
def test_failed_photo_job_is_reused_briefly_and_explicit_retry_can_recover(monkeypatch,remote_worker,stream):
    from types import SimpleNamespace
    now=[100.0];calls=[];healthy=[False]
    monkeypatch.setattr(pages,'time',SimpleNamespace(monotonic=lambda:now[0]))
    failures=[{'provider':'google','reason':'quota_exhausted'},{'provider':'commons','reason':'robots_denied'}]
    def search(place,period,**kwargs):
        calls.append((place,period))
        if not healthy[0]:raise pages.PhotoResearchUnavailable(failures=failures)
        return [{'asset_id':'recovered','date_expression':'1983','location_evidence':'Chengde',
            'image_url':'https://images.example/recovered.jpg','source_url':'https://archive.example/recovered'}]
    monkeypatch.setattr(pages,'search_place_photos',search)
    monkeypatch.delenv('MEMORY_SPARK_PHOTO_WORKER_URL',raising=False)
    cache=None
    if remote_worker:
        cache=pages.PhotoPages()
        worker=create_photo_worker(pages=cache)
        original=httpx.AsyncClient
        monkeypatch.setenv('MEMORY_SPARK_PHOTO_WORKER_URL','http://worker:8767')
        monkeypatch.setenv('MEMORY_SPARK_PHOTO_WORKER_SECRET','fixture-secret')
        monkeypatch.setattr(httpx,'AsyncClient',lambda **kwargs:original(transport=httpx.ASGITransport(app=worker),**kwargs))
    def result(response):
        assert response.status_code==200,response.text
        return json.loads(response.text.splitlines()[-1]) if stream else response.json()
    try:
        with TestClient(create_app(MemoryStore())) as client:
            headers={'X-Account-Id':'failure-owner','Accept':'application/x-ndjson' if stream else 'application/json'}
            project=client.post('/v1/projects',headers=headers,json={'mode':'self'}).json()
            url=f"/v1/projects/{project['id']}/place-photos"
            params={'place':'Chengde','period':'1980s'}
            first=result(client.get(url,params=params,headers=headers))
            assert first['status']=='UNAVAILABLE' and first['failures']==failures
            from pathlib import Path
            import subprocess
            replay=Path(__file__).parent/'js/helpers/replay-photo-provider-failure.mjs'
            client_result=subprocess.run(['node',str(replay)],input=json.dumps(first),text=True,capture_output=True,timeout=20)
            assert client_result.returncode==0,client_result.stdout+client_result.stderr
            count=len(calls)
            repeated=result(client.get(url,params=params,headers=headers))
            assert repeated['status']=='UNAVAILABLE' and repeated['job_id']==first['job_id']
            assert len(calls)==count, 'Repeated UI reads must not immediately restart failed research'
            now[0]+=61
            expired=result(client.get(url,params=params,headers=headers))
            assert expired['job_id']!=first['job_id'] and len(calls)>count
            healthy[0]=True
            recovered=result(client.get(url,params={**params,'refresh':'true'},headers=headers))
            assert recovered['items'][0]['asset_id']=='recovered'
    finally:
        if cache:cache.close()


def test_progress_forwarder_handles_split_unicode_without_changing_worker_credentials(monkeypatch):
    from apps.api.background_skills import photo_step
    monkeypatch.delenv('MEMOIR_PUBLICATION_DATABASE_URL',raising=False)
    monkeypatch.setenv('MEMORY_SPARK_PHOTO_WORKER_URL','http://controlled.invalid')
    monkeypatch.setenv('MEMORY_SPARK_PHOTO_WORKER_SECRET','synthetic-only')
    class Chunks(httpx.AsyncByteStream):
        async def __aiter__(self):
            data=json.dumps({'job_id':'opaque-job','items':[{'title':'承德市'}],'status':'READY','searching':False},ensure_ascii=False).encode()+b'\n'
            for value in data:yield bytes([value])
    def server(request):
        assert request.headers['X-Photo-Worker-Secret']=='synthetic-only'
        return httpx.Response(200,stream=Chunks())
    original=httpx.AsyncClient
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kwargs:original(transport=httpx.MockTransport(server),**kwargs))
    async def run():
        response=await transport.photo_response(None,'owner:project','承德市','1980s',None,stream=True,
            progress=lambda item:photo_step('owner','project',item))
        result=json.loads(''.join([chunk async for chunk in response.body_iterator]))
        assert result['items'][0]['title']=='承德市'
        assert result['skill_progress']['execution']=='provider' and result['skill_progress']['model_invoked'] is None
        assert 'synthetic-only' not in json.dumps(result)
    asyncio.run(run())


@pytest.mark.parametrize('remote_worker', [False, True])
@pytest.mark.parametrize('stream', [False, True])
def test_public_retry_refreshes_photo_research_in_both_response_formats(
        monkeypatch, search_world, remote_worker, stream):
    _, world = search_world
    worker_cache = None
    if remote_worker:
        rows = {}

        def server(request):
            if request.method == 'POST':
                record = json.loads(request.content)
                rows[record['search_key']] = record
                return httpx.Response(201)
            key = request.url.params['search_key'].removeprefix('eq.')
            return httpx.Response(200, json=[{'result': rows[key]['result']}] if key in rows else [])

        repository = PhotoRepository('https://example.supabase.co', 'server-secret',
                                     transport=httpx.MockTransport(server))
        repository.save('Chengde', '1980s', {'complete': True, 'items': [{
            'asset_id': 'persisted', 'date_expression': '1983',
            'image_url': 'https://images.example/street.jpg',
            'source_url': 'https://archive.example/photo'}]})
        worker_cache = pages.PhotoPages(repository=repository)
        worker = create_photo_worker(pages=worker_cache)
        original = httpx.AsyncClient
        monkeypatch.setenv('MEMORY_SPARK_PHOTO_WORKER_URL', 'http://worker:8767')
        monkeypatch.setenv('MEMORY_SPARK_PHOTO_WORKER_SECRET', 'test-secret')
        monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs:
                            original(transport=httpx.ASGITransport(app=worker), **kwargs))
    else:
        monkeypatch.delenv('MEMORY_SPARK_PHOTO_WORKER_URL', raising=False)

    def result(response):
        assert response.status_code == 200
        return json.loads(response.text.splitlines()[-1]) if stream else response.json()

    try:
        with TestClient(create_app(MemoryStore())) as client:
            headers = {'X-Account-Id': 'photo-owner',
                       'Accept': 'application/x-ndjson' if stream else 'application/json'}
            project = client.post('/v1/projects', headers=headers, json={'mode': 'self'}).json()
            url = f"/v1/projects/{project['id']}/place-photos"
            params = {'place': 'Chengde', 'period': '1980s'}
            assert result(client.get(url, headers=headers, params=params))['items'][0]['image_url'] == \
                'https://images.example/street.jpg'
            world['pages']['https://archive.example/photo'] = world['pages'][
                'https://archive.example/photo'].replace('street.jpg', 'refreshed.jpg')
            cached = result(client.get(url, headers=headers, params={**params, 'refresh': 'false'}))
            assert cached['items'][0]['image_url'] == 'https://images.example/street.jpg'
            refreshed = result(client.get(url, headers=headers, params={**params, 'refresh': 'true'}))
            assert refreshed['items'][0]['image_url'] == 'https://images.example/refreshed.jpg'
            assert not refreshed['searching']
    finally:
        if worker_cache is not None:
            worker_cache.close()


def test_worker_warms_once_authenticates_and_supports_both_response_formats(monkeypatch):
    starts, closes, searches = [], [], []
    class Browser:
        async def start(self):
            starts.append(self)
            return self
        async def close(self):
            closes.append(self)
    def search(place, period, **kwargs):
        searches.append((place, period))
        item = {'asset_id': 'one', 'image_url': 'https://images.example/one.jpg',
                'source_url': 'https://archive.example/one', 'date_expression': '1983',
                'latitude': 40.98, 'longitude': 117.94}
        kwargs['on_items']([item])
        return [item]
    monkeypatch.setattr(pages, 'search_place_photos', search)
    monkeypatch.setenv('MEMORY_SPARK_PHOTO_WORKER_SECRET', 'test-secret')
    app = create_photo_worker(browser_factory=Browser)
    payload = {'owner': 'alice', 'place': 'Chengde', 'period': '1980s', 'latitude': 40.98, 'longitude': 117.94}
    with TestClient(app) as client:
        assert client.get('/health').status_code == 200
        assert client.post('/internal/photos', json=payload).status_code == 401
        assert searches == []
        headers = {'X-Photo-Worker-Secret': 'test-secret', 'Accept': 'application/x-ndjson'}
        streamed = client.post('/internal/photos', json=payload, headers=headers)
        lines = [json.loads(line) for line in streamed.text.splitlines()]
        assert streamed.headers['content-type'].startswith('application/x-ndjson')
        assert lines[-1]['items'][0]['asset_id'] == 'one'
        assert not lines[-1]['searching']
        cached = client.post('/internal/photos', json={**payload, 'owner': 'bob'},
                             headers={'X-Photo-Worker-Secret': 'test-secret'})
        assert cached.json()['items'][0]['asset_id'] == 'one'
        assert len(searches) == len(starts) == 1
    assert len(closes) == 1


@pytest.mark.parametrize('center', [{}, {'latitude': 40.98, 'longitude': 117.94}])
def test_api_forwards_photo_batches_without_buffering_and_closes_connection(monkeypatch, center):
    original = httpx.AsyncClient
    release = asyncio.Event()
    closed = []
    class Chunks(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'{"items":[{"asset_id":"early"}],"searching":true}\n'
            await release.wait()
            yield b'{"items":[{"asset_id":"early"}],"searching":false}\n'
        async def aclose(self):
            closed.append(True)
    def handle(request):
        assert request.headers['x-photo-worker-secret'] == 'test-secret'
        assert json.loads(request.content) == {'owner': 'alice', 'place': 'Chengde', 'period': '1980s', 'cursor': None, **center}
        return httpx.Response(200, headers={'Content-Type': 'application/x-ndjson'}, stream=Chunks())
    monkeypatch.setenv('MEMORY_SPARK_PHOTO_WORKER_URL', 'http://worker:8767')
    monkeypatch.setenv('MEMORY_SPARK_PHOTO_WORKER_SECRET', 'test-secret')
    monkeypatch.setattr(transport.httpx, 'AsyncClient', lambda **kwargs:
                        original(transport=httpx.MockTransport(handle), **kwargs))
    async def check():
        response = await transport.photo_response(None, 'alice', 'Chengde', '1980s', None, stream=True, **center)
        reader = response.body_iterator
        early = await asyncio.wait_for(anext(reader), 1)
        assert json.loads(early)['items'][0]['asset_id'] == 'early'
        assert not release.is_set()
        release.set()
        remaining = [chunk async for chunk in reader]
        assert not json.loads(remaining[-1])['searching']
        assert closed
    asyncio.run(check())


@pytest.mark.parametrize('status', [410, 422])
def test_remote_cursor_errors_keep_their_status(monkeypatch, status):
    original = httpx.AsyncClient
    monkeypatch.setenv('MEMORY_SPARK_PHOTO_WORKER_URL', 'http://worker:8767')
    monkeypatch.setattr(transport.httpx, 'AsyncClient', lambda **kwargs:
        original(transport=httpx.MockTransport(lambda request: httpx.Response(status)), **kwargs))
    with pytest.raises(HTTPException) as error:
        asyncio.run(transport.photo_response(None, 'alice', 'Chengde', '1980s', 'expired:10', stream=True))
    assert error.value.status_code == status
