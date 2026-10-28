"""Missing backgrounds generate once, stay private and obey the source-send fence."""
import asyncio
import base64
from contextlib import asynccontextmanager
import copy
from io import BytesIO
import json
import os
from pathlib import Path
import shutil
import subprocess
import struct
import zlib

import httpx
from PIL import Image
import pytest

from apps.api import novel_game_art as art
from apps.api.novel_game_bundle import scene_library,runtime_asset
from apps.api.story_game_runtime import GameFence,GamePublication
from test_story_game_runtime import GAME,TOKEN


def png():
    buffer=BytesIO();Image.new('RGB',(768,512),'#517769').save(buffer,format='PNG')
    return buffer.getvalue()


def broken_pixel_png():
    data=png();result=data[:8];offset=8
    while offset<len(data):
        length=struct.unpack('>I',data[offset:offset+4])[0]
        kind=data[offset+4:offset+8];content=data[offset+8:offset+8+length]
        if kind==b'IDAT':content=b'broken compressed pixels'
        result+=struct.pack('>I',len(content))+kind+content+struct.pack('>I',zlib.crc32(kind+content))
        offset+=length+12
    return result


def short_scanline_png():
    def chunk(kind,content):
        return struct.pack('>I',len(content))+kind+content+struct.pack('>I',zlib.crc32(kind+content))
    header=struct.pack('>IIBBBBB',768,512,8,6,0,0,0)
    row=b'\x00'+bytes((81,119,105,255))*768
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',header)+chunk(b'IDAT',zlib.compress(row))+chunk(b'IEND',b'')


@pytest.fixture
def fence(tmp_path,monkeypatch):
    monkeypatch.setenv('MEMORY_SPARK_OBJECT_STORE_PATH',str(tmp_path/'objects'))
    return GameFence(game_id=GAME,token=TOKEN,authority={'conversation_id':'controlled-conversation'})


def test_stock_is_free_and_matching_custom_backgrounds_reuse_across_retries(tmp_path,fence):
    calls=[]
    async def generate(prompt,_):calls.append(prompt);return png(),{'model':'controlled-image'}
    bindings={'home':'home','observatory':{'prompt':'A quiet hilltop observatory, side-on.'},
        'observatory-later':{'prompt':'A quiet hilltop observatory, side-on.'}}
    def run(b=bindings):return asyncio.run(art.prepare_backgrounds(tmp_path/'game',b,scene_library(),fence,generator=generate))
    stock,images,receipts=run({'home':'home'})
    assert stock=={'home':'home'} and images==[] and calls==[]
    stock,images,receipts=run()
    assert len(calls)==len(images)==1 and receipts[0]['reused'] is False
    assert images[0]['scenes']==['observatory','observatory-later'] and len(images[0]['sha256'])==64
    assert art.read_illustration(images[0])==png()
    _,again,receipts=run()
    assert again==images and len(calls)==1 and receipts[0]['reused'] is True
    (art.cache_root()/(images[0]['cache_key']+'.json')).unlink()
    _,again,receipts=run()
    assert again==images and len(calls)==1, 'Recover a missing receipt after an atomic PNG save without regenerating'
    hydrated=art.hydrate_illustrations({'game':{'novel_game':{'illustrations':copy.deepcopy(images)}}})
    assert base64.b64decode(hydrated['game']['novel_game']['illustrations'][0]['data_url'].split(',')[1])==png()
    with pytest.raises(ValueError):runtime_asset(images[0]['sha256'],'places.png')
    changed=copy.deepcopy(bindings);changed['observatory']={'prompt':'A hilltop observatory in rain.'}
    run(changed);assert len(calls)==2
    other=GameFence(game_id=GAME,token=TOKEN,authority={'conversation_id':'another-owner'})
    asyncio.run(art.prepare_backgrounds(tmp_path/'other',bindings,scene_library(),other,generator=generate))
    assert len(calls)==3, 'Private memoir-derived illustrations must not cross conversation scopes'


def test_partial_image_failure_restores_completed_images_without_regenerating(tmp_path,fence):
    calls=[];fail=True
    async def generate(prompt,_):
        calls.append(prompt)
        if fail and 'night' in prompt:raise httpx.ReadTimeout('controlled image failure')
        return png(),{'model':'controlled-image'}
    bindings={'hill':{'prompt':'Hilltop observatory.'},'night':{'prompt':'Observatory at night.'}}
    def run():return asyncio.run(art.prepare_backgrounds(tmp_path/'game',bindings,scene_library(),fence,generator=generate))
    with pytest.raises(httpx.ReadTimeout):run()
    assert len(calls)==2 and len(list(art.cache_root().rglob('*.png')))==1
    fail=False
    _,images,receipts=run()
    assert len(calls)==3 and len(images)==2 and [r['reused'] for r in receipts]==[True,False]


def test_bad_png_and_corrupt_cache_fail_without_publishing_or_paid_replacement(tmp_path,fence):
    bindings={'hill':{'prompt':'Hilltop observatory.'}}
    async def bad(*_):return b'<svg>untrusted</svg>',{}
    with pytest.raises(OSError):asyncio.run(art.prepare_backgrounds(tmp_path/'game',bindings,scene_library(),fence,generator=bad))
    assert not list(art.cache_root().rglob('*.png'))
    async def good(*_):return png(),{}
    _,images,_=asyncio.run(art.prepare_backgrounds(tmp_path/'game',bindings,scene_library(),fence,generator=good))
    (art.cache_root()/(images[0]['cache_key']+'.png')).write_bytes(b'corrupt')
    async def forbidden(*_):raise AssertionError('Do not silently pay to replace corrupt cached bytes')
    with pytest.raises(ValueError,match='integrity'):
        asyncio.run(art.prepare_backgrounds(tmp_path/'game',bindings,scene_library(),fence,generator=forbidden))


@pytest.mark.parametrize('bad_png',[broken_pixel_png,short_scanline_png],ids=['invalid_zlib','short_scanlines'])
def test_broken_compressed_pixels_are_rejected_before_immutable_cache_write(tmp_path,fence,bad_png):
    async def generate(*_):return bad_png(),{}
    with pytest.raises(OSError):
        asyncio.run(art.prepare_backgrounds(tmp_path/'game',{'hill':{'prompt':'A hilltop.'}},
            scene_library(),fence,generator=generate))
    assert not list(art.cache_root().rglob('*.png'))
    assert not list(art.cache_root().rglob('*.json'))


@pytest.mark.parametrize('bad_png',[broken_pixel_png,short_scanline_png],ids=['invalid_zlib','short_scanlines'])
def test_previously_cached_broken_pixels_are_rejected_without_paid_replacement(tmp_path,fence,bad_png):
    async def generate(*_):return png(),{}
    bindings={'hill':{'prompt':'A hilltop.'}}
    _,images,_=asyncio.run(art.prepare_backgrounds(tmp_path/'game',bindings,scene_library(),fence,generator=generate))
    path=art.cache_root()/(images[0]['cache_key']+'.png');path.write_bytes(bad_png())
    receipt_path=path.with_suffix('.json');receipt=json.loads(receipt_path.read_text())
    receipt['sha256']=art.assets.sha256(path);receipt_path.write_text(json.dumps(receipt))
    async def forbidden(*_):raise AssertionError('Corrupt cached pixels must fail without another paid image call')
    with pytest.raises(OSError):
        asyncio.run(art.prepare_backgrounds(tmp_path/'resumed-game',bindings,scene_library(),fence,generator=forbidden))
    with pytest.raises(OSError):art.read_illustration({**images[0],'sha256':receipt['sha256']})


@pytest.mark.parametrize('revoked',[False,True])
@pytest.mark.parametrize('override',[False,True])
def test_image_transport_uses_the_real_body_send_fence_and_only_png_results(fence,monkeypatch,revoked,override):
    calls=[];admissions=[]
    @asynccontextmanager
    async def guard(self,value):
        admissions.append(value)
        if revoked:raise ValueError('game_authority_changed')
        yield
    monkeypatch.setattr(GamePublication,'guard',guard)
    for key,value in {'MEMOIR_PUBLICATION_DATABASE_URL':'controlled','MEMOIR_GAME_IMAGE_BASE_URL':'https://images.test/v1' if override else '',
        'MEMOIR_GAME_IMAGE_API_KEY':'controlled-image-key' if override else '',
        'MEMORY_SPARK_LLM_BASE_URL':'https://images.test/v1','MEMORY_SPARK_LLM_API_KEY':'controlled-image-key',
        'MEMOIR_GAME_IMAGE_MODEL':'controlled-image'}.items():monkeypatch.setenv(key,value)
    def transport(request):
        body=json.loads(request.content);calls.append(body)
        assert request.url.path=='/v1/images/generations' and request.headers['Authorization']=='Bearer controlled-image-key'
        assert body['model']=='controlled-image' and body['n']==1 and body['output_format']=='png'
        return httpx.Response(200,json={'created':1,'data':[{'b64_json':base64.b64encode(png()).decode()}]})
    def run():return asyncio.run(art.generate_background('A generic observatory.',fence,transport=httpx.MockTransport(transport)))
    if revoked:
        with pytest.raises(ValueError,match='authority_changed'):run()
        assert calls==[]
    else:
        data,receipt=run();assert data==png() and receipt['model']=='controlled-image'
        assert receipt['prompt_manifest']['artifacts'][0]['name'].endswith('/illustration')
    assert admissions[0]['authority']==fence.authority


@pytest.mark.parametrize('value',[{'url':'https://outside.test/a.png'},{'prompt':''},'missing-cell',{'prompt':'x','script':'bad'}])
def test_art_handoff_accepts_only_existing_cells_or_bounded_generation_requests(value):
    with pytest.raises(ValueError):art.validate_bindings({'hill':value},{'hill'},scene_library())


def test_private_cache_reference_cannot_read_an_arbitrary_path():
    with pytest.raises(ValueError):art.read_illustration(dict(cache_key='../../secret',sha256='a'*64,width=768,height=512,scenes=['hill']))


@pytest.mark.skipif(shutil.which('mocker') is None,reason='Mocker is not installed')
@pytest.mark.parametrize('override',[False,True])
def test_compose_keeps_optional_image_overrides_empty_or_explicit(tmp_path,override):
    compose=tmp_path/'compose.yml';compose.write_text((Path(__file__).parents[1]/'compose.yml').read_text())
    environment={k:v for k,v in os.environ.items() if not k.startswith(('MEMOIR_GAME_IMAGE','MEMORY_SPARK_LLM'))}
    environment.update(MEMORY_SPARK_LLM_BASE_URL='https://controlled-gateway.test/v1',MEMORY_SPARK_LLM_API_KEY='controlled-placeholder')
    if override:environment.update(MEMOIR_GAME_IMAGE_BASE_URL='https://controlled-image.test/v1',
        MEMOIR_GAME_IMAGE_API_KEY='controlled-image-placeholder',MEMOIR_GAME_IMAGE_MODEL='configured-image-model')
    result=subprocess.run(['mocker','compose','config','-f',str(compose)],cwd=tmp_path,env=environment,capture_output=True,text=True,timeout=20)
    assert result.returncode==0
    lines=[s.strip().removeprefix('- ').strip('"') for s in result.stdout.splitlines()]
    assert 'MEMOIR_GAME_IMAGE_BASE_URL='+('https://controlled-image.test/v1' if override else '') in lines
    assert 'MEMOIR_GAME_IMAGE_API_KEY='+('controlled-image-placeholder' if override else '') in lines
    assert 'MEMOIR_GAME_IMAGE_MODEL='+('configured-image-model' if override else '') in lines
