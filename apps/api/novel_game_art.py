"""Reuse stock/cached scene backgrounds, generating only missing private PNGs."""
import asyncio
import base64
import hashlib
from importlib import import_module
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

import httpx

assets = import_module('experiments.novel-to-game.game_assets')
MAX_IMAGE_BYTES = 20_000_000
MAX_GAME_IMAGE_BYTES = 24_000_000


def cache_root():
    return Path(os.getenv('MEMORY_SPARK_OBJECT_STORE_PATH', str(assets.PACKAGE.parents[1]/'var/memory-spark/objects')))/'story-game-scenes'


def validate_bindings(bindings, needed, library):
    if not isinstance(bindings,dict) or set(bindings)!=needed:
        raise ValueError('game_scene_bindings_invalid')
    for value in bindings.values():
        if isinstance(value,str) and value in library['cells']:
            continue
        if (not isinstance(value,dict) or set(value)!={'prompt'} or not isinstance(value['prompt'],str)
                or not 1<=len(value['prompt'].strip())<=12000):
            raise ValueError('game_scene_bindings_invalid')
    return bindings


def validate_illustration(item):
    if (not isinstance(item,dict) or set(item)!={'cache_key','sha256','width','height','scenes'}
            or not re.fullmatch(r'[a-f0-9]{64}/[a-f0-9]{64}',str(item['cache_key']))
            or not re.fullmatch(r'[a-f0-9]{64}',str(item['sha256']))
            or any(type(item[k]) is not int or not 256<=item[k]<=3840 for k in ('width','height'))
            or item['width']*item['height']>8_294_400
            or not isinstance(item['scenes'],list) or not 1<=len(item['scenes'])<=128
            or any(not isinstance(s,str) or not re.fullmatch(r'[a-z][a-z0-9-]{0,47}',s) for s in item['scenes'])
            or len(set(item['scenes']))!=len(item['scenes'])):
        raise ValueError('game_scene_illustration_invalid')
    return item


def read_illustration(item):
    validate_illustration(item)
    path=cache_root()/(item['cache_key']+'.png')
    if path.is_symlink() or not path.resolve().is_relative_to(cache_root().resolve()):
        raise ValueError('game_scene_cache_path_invalid')
    info=assets.png_info(path,dict(columns=1,rows=1))
    if any(info[k]!=item[k] for k in ('width','height')) or assets.sha256(path)!=item['sha256']:
        raise ValueError('game_scene_cache_integrity')
    return path.read_bytes()


def hydrate_illustrations(value):
    """Called only after the normal SQL owner/share/source authorization succeeds."""
    game=(value.get('game') or {}).get('novel_game') or {}
    total=0
    for item in game.get('illustrations',[]):
        data=read_illustration(item);total+=len(data)
        if total>MAX_GAME_IMAGE_BYTES:
            raise ValueError('game_scene_image_limit')
        item['data_url']='data:image/png;base64,'+base64.b64encode(data).decode('ascii')
    return value


async def generate_background(prompt,fence,*,transport=None,issue14_admission=None):
    from .issue14_execution_admission import check_issue14_dispatch
    from .lifetime_memory_lane_engine import check_lane_generation
    from .llm_tracing import trace_llm_call,update_llm_trace,gateway_trace_headers
    from .model_request import instruction_manifest
    from .prompt_artifact import load_prompt_artifact,prompt_path
    from .story_game_runtime import GamePublication,GameRequestBody
    check_issue14_dispatch(issue14_admission,role='tool_loop');check_lane_generation()
    base=(os.getenv('MEMOIR_GAME_IMAGE_BASE_URL') or os.getenv('MEMORY_SPARK_LLM_BASE_URL','')).rstrip('/')
    key=os.getenv('MEMOIR_GAME_IMAGE_API_KEY') or os.getenv('MEMORY_SPARK_LLM_API_KEY','')
    model=os.getenv('MEMOIR_GAME_IMAGE_MODEL','').strip()
    endpoint=urlsplit(base)
    if (not key or not model or endpoint.scheme not in {'http','https'} or not endpoint.hostname
            or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment):
        raise ValueError('game_image_provider_unavailable')
    instructions=load_prompt_artifact(prompt_path('memoir/skills/memoir-story-game/novel-to-game/illustration'))
    manifest=instruction_manifest(instructions,{},variant='novel-game-illustration')
    body=dict(model=model,prompt=prompt,n=1,size='1536x1024',
        quality='medium',background='opaque',output_format='png')
    encoded=json.dumps(body,ensure_ascii=False).encode()
    request=GameRequestBody(encoded,publisher=GamePublication(os.getenv('MEMOIR_PUBLICATION_DATABASE_URL')),
        fence=fence.model_dump(mode='json'))
    try:
        with trace_llm_call('story.game.novel.illustration',model,metadata={'prompt_manifest':manifest},
                gateway=base==os.getenv('MEMORY_SPARK_LLM_BASE_URL','').rstrip('/')) as trace:
            async with asyncio.timeout(600),httpx.AsyncClient(trust_env=False,follow_redirects=False,timeout=590,
                    **({'transport':transport} if transport is not None else {})) as client:
                async with client.stream('POST',base+'/images/generations',content=request,
                        headers={'Authorization':'Bearer '+key,'Content-Type':'application/json','Content-Length':str(len(encoded)),
                            **gateway_trace_headers()}) as response:
                    response.raise_for_status();chunks=[];size=0
                    async for chunk in response.aiter_bytes():
                        size+=len(chunk)
                        if size>MAX_IMAGE_BYTES*4//3+65536:raise ValueError('game_image_response_limit')
                        chunks.append(chunk)
            result=json.loads(b''.join(chunks))
            if (not isinstance(result,dict) or not isinstance(result.get('data'),list) or len(result['data'])!=1
                    or not isinstance(result['data'][0],dict) or not isinstance(result['data'][0].get('b64_json'),str)):
                raise ValueError('game_image_response_invalid')
            data=base64.b64decode(result['data'][0]['b64_json'],validate=True)
            if not data or len(data)>MAX_IMAGE_BYTES:raise ValueError('game_image_response_limit')
            receipt=dict(model=model,created=result.get('created'),usage=result.get('usage'),prompt_manifest=manifest)
            update_llm_trace(trace,metadata=receipt)
            return data,receipt
    finally:
        await request.aclose()


async def prepare_backgrounds(workspace,bindings,library,fence,*,generator=None):
    """An exact style/prompt cache survives retries; memoir-derived art stays scoped."""
    scope=hashlib.sha256(str(fence.authority.get('conversation_id') or fence.game_id).encode()).hexdigest()
    cache=cache_root()/scope
    custom={}
    for scene,value in bindings.items():
        if isinstance(value,dict):
            from .prompt_artifact import load_prompt_artifact,prompt_path
            instructions=load_prompt_artifact(prompt_path('memoir/skills/memoir-story-game/novel-to-game/illustration'))
            prompt=instructions+'\n\n'+assets.pack_catalog()['scene_style']['description']+'\n\n'+value['prompt'].strip()
            art=dict(id='background',kind='scene-background',prompt=prompt,columns=1,rows=1,scenes=['background'])
            plan=dict(style=assets.pack_catalog()['scene_style']['id'],illustrations=[art])
            key=assets.scene_key(plan,art)
            entry=custom.setdefault(key,dict(plan=plan,scenes=[]))
            entry['scenes'].append(scene)
    if len(custom)>24:raise ValueError('game_scene_image_limit')
    references=[];catalog=[];receipts=[];total=0
    for key,entry in custom.items():
        work=workspace/'scene-assets'/key
        art=entry['plan']['illustrations'][0]
        item=assets.cached_scene(entry['plan'],art,cache)
        original=cache/(key+'.png')
        if item is None and original.is_file():
            # An interrupted receipt write must not pay to replace a completed atomic PNG.
            item=assets.cache_scene(entry['plan'],art,original,cache)
        reused=item is not None
        if item is None:
            data,receipt=await (generator or generate_background)(entry['plan']['illustrations'][0]['prompt'],fence)
            path=assets.write_bytes(work,'generated.png',data)
            info=assets.png_info(path,dict(columns=1,rows=1))
            validate_illustration(dict(cache_key=scope+'/'+key,sha256=assets.sha256(path),
                width=info['width'],height=info['height'],scenes=entry['scenes']))
            item=assets.cache_scene(entry['plan'],art,path,cache)
            assets.write_json(cache,key+'-provider.json',receipt)
        reference=validate_illustration(dict(cache_key=scope+'/'+key,sha256=item['sha256'],
            width=item['width'],height=item['height'],scenes=entry['scenes']))
        data=read_illustration(reference);total+=len(data)
        if total>MAX_GAME_IMAGE_BYTES:raise ValueError('game_scene_image_limit')
        url='assets/scenes/'+key+'.png';assets.write_bytes(workspace,'build/app/'+url,data,immutable=True)
        references.append(reference)
        catalog.append(dict(reference,url=url,status='ready',columns=1,rows=1,cells={scene:0 for scene in entry['scenes']}))
        receipts.append(dict(cache_key=reference['cache_key'],sha256=item['sha256'],reused=reused,
            provider=json.loads((cache/(key+'-provider.json')).read_text()) if (cache/(key+'-provider.json')).exists() else None))
    pack=assets.pack_catalog()
    for item in pack['files']:assets.write_bytes(workspace,'build/app/'+item['url'],assets.stock_source(item).read_bytes())
    stock={scene:cell for scene,cell in bindings.items() if isinstance(cell,str)}
    if stock:
        assets.write_bytes(workspace,'build/app/assets/scenes/places.png',(assets.PACKAGE/'assets/illustrated-places-v1/places.png').read_bytes())
        catalog.insert(0,dict(url='assets/scenes/places.png',status='ready',width=library['width'],height=library['height'],
            columns=library['columns'],rows=library['rows'],scenes=list(stock),cells={s:library['cells'].index(c) for s,c in stock.items()}))
    assets.write_json(workspace,'build/asset-catalog.json',dict(stock=pack,scenes=catalog))
    return stock,references,receipts
