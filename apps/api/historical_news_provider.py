"""Approved gateway native-search protocol and public-only source inspection.

No image query, photo flag, image licence validator, or fallback provider.
The collector never receives a gateway credential or executes this adapter.
"""
import asyncio
from datetime import datetime, timezone
from html.parser import HTMLParser
import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from .historical_news import PUBLIC_PLACES, canonical_url
from .prompt_artifact import load_prompt_artifact, prompt_path

MAX_BYTES=512_000
SOURCE_MAX_BYTES=2_000_000


def decode_discovery(data):
    # The gateway wraps response IDs in a longer opaque routing token.
    valid=lambda value:isinstance(value,str) and re.fullmatch(r'[A-Za-z0-9_-]{1,1024}',value)
    if (not isinstance(data,dict) or data.get('status')!='completed'
        or not valid(data.get('id')) or not isinstance(data.get('output'),list)):
        raise ValueError('Malformed search response')
    calls=[row for row in data['output'] if isinstance(row,dict) and row.get('type')=='web_search_call']
    if not 1<=len(calls)<=4 or any(row.get('status')!='completed' or not valid(row.get('id')) for row in calls):
        raise ValueError('Missing completed search receipt')
    origins={}
    for call in calls:
        for item in (call.get('action') or {}).get('sources',[])[:24]:
            if not isinstance(item,dict):continue
            try:url=canonical_url(item.get('url'))
            except (ValueError,TypeError):continue
            if len(origins)<24:origins.setdefault(url,call['id'])
    urls=list(origins)
    if not urls:raise ValueError('Missing returned source URLs')
    messages=[row for row in data['output'] if isinstance(row,dict) and row.get('type')=='message']
    if any(row.get('status')!='completed' for row in messages):
        raise ValueError('Incomplete historical leads')
    chunks=[c.get('text','') for row in messages
        for c in row.get('content',[]) if isinstance(c,dict) and c.get('type')=='output_text']
    try:
        output=json.loads(''.join(chunks))
        events=output['events']
        if not isinstance(events,list) or len(events)>20:raise ValueError()
    except (ValueError,KeyError,TypeError):raise ValueError('Malformed historical leads') from None
    return {'receipt':{'provider':'approved_gateway','response_id':data['id'],'tool_call_id':origins[urls[0]],
        'status':'completed','urls':urls,'source_tool_calls':origins},'events':events}


class _Text(HTMLParser):
    def __init__(self):
        super().__init__();self.parts=[];self.hidden=0;self.in_title=False;self.title=[];self.publisher=None;self.publication_date=None
    def handle_starttag(self,tag,attrs):
        if tag in {'script','style','noscript'}:self.hidden+=1
        if tag=='title':self.in_title=True
        if tag=='meta':
            attrs=dict(attrs);key=attrs.get('property') or attrs.get('name') or attrs.get('itemprop')
            if key in {'og:site_name','publisher'}:self.publisher=attrs.get('content')
            if key in {'article:published_time','datePublished'}:self.publication_date=attrs.get('content','')[:10] or None
    def handle_endtag(self,tag):
        if tag in {'script','style','noscript'}:self.hidden=max(0,self.hidden-1)
        if tag=='title':self.in_title=False
    def handle_data(self,data):
        if not self.hidden:self.parts.append(data)
        if self.in_title:self.title.append(data)


def inspect_public_source(url, timeout):
    from .place_photo_browser import _research
    helper=_research();parsed,host,_=helper.valid_url(url)
    try:
        status,final,headers,body=helper.Fetcher().fetch(url,SOURCE_MAX_BYTES,{host},deadline_seconds=timeout)
    except helper.ResearchError:
        raise ValueError('Historical source access blocked') from None
    if status!=200 or not headers.get('content-type','').lower().startswith(('text/html','text/plain')):
        raise ValueError('Historical source unavailable')
    if canonical_url(final)!=canonical_url(url):
        raise ValueError('Source redirect requires a separately returned canonical source')
    parser=_Text();parser.feed(body.decode('utf-8',errors='replace'))
    return {'url':final,'text':' '.join(parser.parts),'source_title':' '.join(parser.title).strip(),
            'publisher':parser.publisher or host,'publication_date':parser.publication_date,
            'retrieved_at':datetime.now(timezone.utc).isoformat()}


class GatewayHistoricalProvider:
    def __init__(self, *, client=None):
        self.client=client
        self.model=os.getenv('MEMORY_SPARK_HISTORICAL_NEWS_MODEL') or os.getenv('MEMORY_SPARK_LLM_MODEL','')
        self.identity='approved_gateway:'+self.model

    async def discover(self,query,*,timeout):
        labels={', '.join(p) for p in PUBLIC_PLACES}|{p[1] for p in PUBLIC_PLACES}
        match=re.fullmatch(r'(.+) (\d{1,4})–(\d{1,4}) civic culture sport public events',query)
        if not match or match[1] not in labels or not 1<=int(match[2])<=int(match[3]) or int(match[3])-int(match[2])>15:
            raise ValueError('Non-public query rejected')
        base=os.getenv('MEMORY_SPARK_LLM_BASE_URL','').rstrip('/')
        model=self.model;key=os.getenv('MEMORY_SPARK_LLM_API_KEY','')
        parsed=urlsplit(base)
        if (not key or not model or parsed.scheme not in {'https','http'} or not parsed.hostname
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
            raise ValueError('Historical search is not configured')
        prompt = load_prompt_artifact(prompt_path('memoir/skills/memoir-historical-news-research/discovery')).replace('{{query}}', query)
        body={'model':model,'input':prompt,'tools':[{'type':'web_search'}],'tool_choice':'required',
            'include':['web_search_call.action.sources'],'reasoning':{'effort':'low'},
            'max_output_tokens':3000,'store':False,
            'metadata':{'generation_name':'memoir-historical-news-research',
                'trace_name':'memoir-historical-news-research'}}
        async def request(client):
            try:
                async with client.stream('POST',base+'/responses',json=body,
                    headers={'Authorization':'Bearer '+key},timeout=timeout) as response:
                    response.raise_for_status();raw=bytearray()
                    async for chunk in response.aiter_bytes():
                        raw.extend(chunk)
                        if len(raw)>MAX_BYTES:raise ValueError('Search response exceeds limit')
                decoded=decode_discovery(json.loads(raw))
                if key in json.dumps(decoded):raise ValueError('Unsafe search receipt')
                return decoded
            except httpx.HTTPError:raise OSError('Historical provider unavailable') from None
        if self.client:return await request(self.client)
        async with httpx.AsyncClient(follow_redirects=False) as client:return await request(client)

    async def inspect(self,url,*,timeout):
        # DNS/robots/socket operations must not survive the job deadline.
        # A task-owned child process (not an uncancellable thread) reuses the
        # existing public-source protections and is reaped on timeout/cancel.
        import sys
        process=await asyncio.create_subprocess_exec(sys.executable,'-m','apps.api.historical_news_source',url,str(timeout),
            stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL)
        try:
            raw,_=await asyncio.wait_for(process.communicate(),timeout=timeout)
            if process.returncode or len(raw)>MAX_BYTES*2:raise ValueError('Historical source unavailable')
            return json.loads(raw)
        finally:
            if process.returncode is None:
                process.kill()
            await process.wait()
