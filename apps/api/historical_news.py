"""Bounded external historical context. Nothing here creates personal evidence.

Only public gazetteer labels reach discovery. Inputs are private, versioned
accepted context; outputs are optional question cues, never MemoryEvents.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import re
from urllib.parse import urlsplit, urlunsplit, parse_qsl

from pydantic import BaseModel, ConfigDict, Field


class PublicHistoricalContext(BaseModel):
    model_config=ConfigDict(extra='forbid')
    id:str=Field(pattern=r'^news-[a-f0-9]{24}$')
    title:str=Field(min_length=1,max_length=200)
    summary:str=Field(min_length=1,max_length=500)
    event_start:int=Field(ge=1,le=9999)
    event_end:int=Field(ge=1,le=9999)
    precision:str
    place:str
    source_url:str=Field(pattern=r'^https?://')
    source_title:str=Field(min_length=1,max_length=300)
    publisher:str=Field(min_length=1,max_length=200)
    publication_date:str|None=None


VERSION = 'historical-news-v1'
# A deliberately small, reviewed public vocabulary. Unknown/ambiguous unqualified
# places wait for ordinary clarification; raw profile/source text is never used
# as a query. Expand this catalog with reviewed public labels, not user text.
PUBLIC_PLACES = {
    ('New York', 'USA'): 'unresolved', ('New York City', 'USA'): 'city',
    ('New York State', 'USA'): 'region', ('Boston', 'USA'): 'city',
    ('Sydney', 'Australia'): 'city', ('Perth', 'Australia'): 'city',
    ('Melbourne', 'Australia'): 'city', ('Chengdu', 'China'): 'city',
    ('Chengde', 'China'): 'city', ('承德', '中国'): 'city',
    ('Kunming', 'China'): 'city', ('Beijing', 'China'): 'city',
    ('成都', '中国'): 'city', ('昆明', '中国'): 'city', ('北京', '中国'): 'city',
    ('纽约', '美国'): 'unresolved', ('悉尼', '澳大利亚'): 'city',
}
CATEGORIES = {'civic', 'culture', 'sport'}

SENSITIVE_CONTENT = re.compile(
    r'\b(war|battle|attack|massacre|kill(?:ed|ing)?|murder|assassin\w*|terror\w*|bomb\w*|shoot\w*|'
    r'riot\w*|violence|rape|abuse|discrimination|racis\w*|slavery|genocide|election|campaign|politic\w*|'
    r'protest|coup|revolution|communis\w*|nazi|holocaust|famine|disaster)\b|'
    r'灾|战争|屠杀|杀害|袭击|枪击|炸弹|骚乱|暴力|强奸|虐待|歧视|种族|奴隶|选举|政治|抗议|政变|革命|文革|饥荒|死亡', re.I)


def _window(value, *, max_width=15):
    if not isinstance(value, dict) or value.get('conflicting'):
        return None
    a, b = value.get('start'), value.get('end')
    if type(a) is not int or type(b) is not int or not 1 <= a <= b <= 9999 or b-a > max_width:
        return None
    return a, b


def derive_hypothesis(context, *, current_year=None, ages=(8, 15)):
    current_year = current_year or datetime.now(timezone.utc).year
    explicit = context.get('period')
    if explicit is not None:
        window = _window(explicit)
        basis = 'explicit_period'
    else:
        birth = context.get('birth_year')
        window = _window(birth, max_width=3)
        if not window or birth.get('confirmed') is not True:
            return None
        if not (0 <= ages[0] <= ages[1] <= 20):
            raise ValueError('Invalid discovery ages')
        window = window[0] + ages[0], window[1] + ages[1]
        basis = 'approximate_age_hypothesis'
    if not window or window[0] > current_year:
        return None
    start, end = window[0], min(window[1], current_year)
    locations = context.get('locations') or []
    confirmed = [p for p in locations if p.get('confirmed') is True]
    # A move during the proposed range is ambiguous: wait for a narrower
    # narrator period instead of extending either residence across the move.
    matching = [p for p in confirmed if type(p.get('start')) is int and type(p.get('end')) is int
                and p['start'] <= start <= end <= p['end']]
    if confirmed and len(matching) != 1:
        return None
    place = matching[0] if matching else context.get('birthplace')
    if not isinstance(place, dict):
        return None
    pair = place.get('name'), place.get('country')
    if pair not in PUBLIC_PLACES:
        return None
    return {'start':start, 'end':end, 'place':', '.join(pair), 'country':pair[1],
            'granularity':PUBLIC_PLACES[pair], 'tentative':not bool(matching),
            'time_basis':basis, 'age_interval':list(ages) if explicit is None else None}


def public_queries(hypothesis):
    # Revalidate even internal callers. No arbitrary query suffix, story text,
    # account ID, or provider-generated expansion can cross this boundary.
    allowed = {', '.join(p) for p in PUBLIC_PLACES}
    if hypothesis.get('place') not in allowed or not _window(hypothesis):
        raise ValueError('Unsupported public query')
    country = next(p[1] for p in PUBLIC_PLACES if ', '.join(p)==hypothesis['place'])
    if country != hypothesis.get('country'):
        raise ValueError('Conflicting public geography')
    suffix = f" {hypothesis['start']}–{hypothesis['end']} civic culture sport public events"
    return [hypothesis['place']+suffix, country+suffix]


def canonical_url(value):
    from .place_photo_browser import _research
    helper=_research()
    try:
        parsed, _, _ = helper.valid_url(value)
    except helper.ResearchError:
        raise ValueError('Unsafe historical source URL') from None
    import ipaddress
    try:address=ipaddress.ip_address(parsed.hostname)
    except ValueError:address=None
    if address is not None and not address.is_global:
        raise ValueError('Private historical source URL')
    if any(re.search(r'key|token|secret|signature|password|credential', key, re.I)
           for key, _ in parse_qsl(parsed.query)):
        raise ValueError('Credential-bearing source URL')
    return urlunsplit((parsed.scheme.lower(),parsed.netloc.lower(),parsed.path or '/',parsed.query,''))


def _bounded(value, maximum):
    if not isinstance(value, str) or not value.strip() or len(value)>maximum:
        raise ValueError('Malformed historical evidence')
    return value.strip()


def validate_evidence(proposal, receipt, page, hypothesis):
    """Discovery/model text is a lead. Require inspected verbatim support.

    These deterministic checks cannot establish historical truth. The provider
    must identify provenance and conflicts; unsupported/ambiguous records are
    excluded. No search snippet is passed in as an inspected page.
    """
    if (receipt.get('status')!='completed' or not receipt.get('response_id') or not receipt.get('tool_call_id')
        or not receipt.get('provider') or proposal.get('conflicting') or proposal.get('category') not in CATEGORIES):
        raise ValueError('Historical evidence unavailable')
    url=canonical_url(proposal.get('source_url'))
    if url not in {canonical_url(u) for u in receipt.get('urls',[])} or canonical_url(page.get('url'))!=url:
        raise ValueError('Unobserved historical source')
    receipt=deepcopy(receipt)
    origins=receipt.pop('source_tool_calls',None)
    if origins is not None:
        if not isinstance(origins,dict) or not isinstance(origins.get(url),str) or not origins[url]:
            raise ValueError('Unobserved historical source receipt')
        receipt.update(tool_call_id=origins[url],urls=[url])
    title=_bounded(proposal.get('title'),200)
    excerpt=_bounded(proposal.get('excerpt'),800)
    summary=_bounded(proposal.get('summary'),500)
    if SENSITIVE_CONTENT.search(' '.join([title,summary,excerpt])):
        raise ValueError('Sensitive historical context is not eligible for proactive selection')
    # Keep the assertion verifiable instead of accepting a plausible generated
    # paraphrase unrelated to the page. Whitespace is the only normalization.
    normalized=lambda s:' '.join(s.split())
    if normalized(excerpt) not in normalized(page.get('text','')) or normalized(summary) not in normalized(excerpt):
        raise ValueError('Uninspected historical claim')
    dates=_window({'start':proposal.get('event_start'),'end':proposal.get('event_end')})
    if not dates or not hypothesis['start']<=dates[0]<=dates[1]<=hypothesis['end']:
        raise ValueError('Unsupported historical date')
    if any(not re.search(rf'(?<!\d){y}(?!\d)',summary) for y in set(dates)) or any(
        not dates[0] <= int(y) <= dates[1] for y in re.findall(r'(?<!\d)((?:18|19|20)\d{2})(?!\d)',summary)):
        raise ValueError('Event date is not source supported')
    if (normalized(title).casefold() not in normalized(excerpt).casefold()
        or proposal.get('source_title') != page.get('source_title')
        or proposal.get('publisher') != page.get('publisher')
        or proposal.get('publication_date') != page.get('publication_date')):
        raise ValueError('Unsupported event or source identity')
    if re.search(r'published|publication|copyright|发表于|出版',summary,re.I):
        raise ValueError('Publication metadata is not event evidence')
    place=proposal.get('place')
    if place not in {hypothesis['place'],hypothesis['country']} or place.split(',')[0].casefold() not in excerpt.casefold():
        raise ValueError('Unsupported historical place')
    if proposal.get('precision') not in {'year','range'}:
        raise ValueError('Unsupported historical precision')
    observed=_bounded(page.get('retrieved_at'),40)
    if datetime.fromisoformat(observed.replace('Z','+00:00')).tzinfo is None:
        raise ValueError('Retrieval timestamp needs a timezone')
    publication=proposal.get('publication_date')
    if publication is not None:
        from datetime import date
        if not isinstance(publication,str) or len(publication)!=10 or date.fromisoformat(publication).isoformat()!=publication:
            raise ValueError('Malformed source publication date')
    identity='|'.join([normalized(title).casefold(),str(dates[0]),str(dates[1]),place.casefold()])
    return {'id':'news-'+hashlib.sha256(identity.encode()).hexdigest()[:24],
        'title':title,'summary':summary,'event_start':dates[0],'event_end':dates[1],
        'precision':proposal['precision'],'place':place,'category':proposal['category'],
        'source_url':url,'source_title':_bounded(proposal.get('source_title'),300),
        'publisher':_bounded(proposal.get('publisher'),200),'excerpt':excerpt,
        'locator':'text offset '+str(normalized(page['text']).index(normalized(excerpt))),'publication_date':proposal.get('publication_date'),
        'retrieved_at':observed,'receipt':deepcopy(receipt),'evidence_status':'inspected'}


def authorized_clue(context, clue_id):
    state=context.get('historical_news') or {}
    if state.get('enabled') is not True:
        raise ValueError('Historical clues are disabled')
    clue=next((c for c in state.get('clues',[]) if c.get('id')==clue_id),None)
    if (not clue or clue.get('status')!='ready' or clue.get('evidence_status')!='inspected'
        or clue.get('context_revision')!=state.get('context_revision')
        or clue.get('project_id')!=state.get('project_id') or not clue.get('source_url')
        or not clue.get('receipt') or clue.get('category') not in CATEGORIES):
        raise ValueError('Historical clue unavailable')
    return clue


def public_clue(clue):
    keys={'id','title','summary','event_start','event_end','precision','place','source_url',
          'source_title','publisher','publication_date'}
    return {k:deepcopy(v) for k,v in clue.items() if k in keys}


HISTORICAL_INVITATIONS = {
    'en-AU': ('Does this bring any memory of that time to mind?',
              'An optional public-history clue; it is fine to skip.'),
    'zh-CN': ('这条公开历史线索会让您想起当时的什么吗？',
              '这是一条可选的公开历史线索，不记得也没关系。'),
}


def question_hints(context):
    """Expose inspected public clues as optional questions, never narrator evidence."""
    question, bridge = HISTORICAL_INVITATIONS.get(context.get('interview_language'), HISTORICAL_INVITATIONS['en-AU'])
    hints = []
    for clue in (context.get('historical_news') or {}).get('clues', [])[:5]:
        try:
            authorized_clue(context, clue.get('id'))
        except ValueError:
            continue
        hints.append(dict(id=clue['id'], question=question, bridge=bridge,
            historical_clue_id=clue['id'], purpose='historical_news', public_context=public_clue(clue)))
    return hints


class HistoricalResearch:
    """Public-only process cache; private relevance is never cached/shared."""
    def __init__(self, provider, *, clock=None):
        import time
        self.provider=provider
        self.clock=clock or time.monotonic
        self.cache={}

    async def run(self, hypothesis):
        import asyncio
        queries=public_queries(hypothesis)
        key=hashlib.sha256(json.dumps([VERSION, getattr(self.provider,'identity','approved_gateway'), queries],ensure_ascii=False).encode()).hexdigest()
        start=self.clock()
        account={'discovery_requests':0,'source_reads':0,'cache':'miss','cost':None,'cost_status':'unavailable'}
        cached=self.cache.get(key)
        if cached and 0 <= start-cached[0]<86400:
            return {'status':'ready','clues':deepcopy(cached[1]),'accounting':{**account,'cache':'hit'}}
        clues={};pages={};failures=[]
        async def bounded(coroutine):
            remaining=45-(self.clock()-start)
            if remaining<=0:
                coroutine.close()
                raise TimeoutError()
            return await asyncio.wait_for(coroutine,timeout=remaining)
        for query in queries:
            if account['discovery_requests']>=2 or len(clues)>=5:break
            try:
                account['discovery_requests']+=1
                discovery=await bounded(self.provider.discover(query,timeout=max(.01,45-(self.clock()-start))))
            except (TimeoutError,OSError,ValueError):
                failures.append('provider_unavailable')
                # At most one retry of the SAME minimized query, never an
                # expansion or another provider. It consumes the global cap.
                if account['discovery_requests']>=2:break
                account['discovery_requests']+=1
                try:discovery=await bounded(self.provider.discover(query,timeout=max(.01,45-(self.clock()-start))))
                except (TimeoutError,OSError,ValueError):break
            r=discovery.get('receipt') or {}
            if r.get('status')!='completed' or not r.get('response_id') or not r.get('tool_call_id'):
                failures.append('missing_search_receipt');break
            for proposal in discovery.get('events',[])[:20]:
                if len(clues)>=5:break
                try:
                    url=canonical_url(proposal.get('source_url'))
                    if url not in {canonical_url(u) for u in r.get('urls',[])}:continue
                    if url not in pages:
                        if account['source_reads']>=6:continue
                        account['source_reads']+=1
                        pages[url]=None # failures count too and are not retried
                        pages[url]=await bounded(self.provider.inspect(url,timeout=max(.01,45-(self.clock()-start))))
                    if not pages[url]:continue
                    clue=validate_evidence(proposal,r,pages[url],hypothesis)
                    if clue['id'] in clues:
                        old=clues[clue['id']]
                        old.setdefault('supporting_sources',[])
                        if clue['source_url']!=old['source_url'] and clue['source_url'] not in [s['source_url'] for s in old['supporting_sources']]:
                            old['supporting_sources'].append(public_clue(clue))
                    else:clues[clue['id']]=clue
                except (TimeoutError,OSError,ValueError,TypeError,KeyError):
                    failures.append('source_unavailable')
            if self.clock()-start>=45:break
        result=list(clues.values())
        if result and not failures:
            if len(self.cache)>=128:self.cache.pop(next(iter(self.cache)))
            self.cache[key]=(self.clock(),deepcopy(result))
        return {'status':'ready' if result else 'unavailable' if failures else 'empty',
                'clues':result,'accounting':account,'failures':sorted(set(failures))}


def accepted_hypothesis(view, *, current_year=None, selection=None):
    """Conservative local adapter for accepted first-person life context.

    Narrow explicit forms are intentional. Unknown forms wait for normal
    interviewing; there is no extra classifier, name inference, or raw query.
    """
    current_year=current_year or datetime.now(timezone.utc).year
    if 'places' in view:
        from .place_research import research_places, research_hypothesis
        places = research_places(view['places'], view.get('sources', []))
        return research_hypothesis(places, selection=selection, current_year=current_year)
    if selection is not None:
        return None
    births=[];birthplaces=[];locations=[];birth_clauses=[];unresolved_move=False
    for source in view.get('sources',[]):
        if source.get('status')!='active':continue
        text=source.get('text','')
        # Clause scope prevents a relative's birth or a denied date from
        # becoming the storyteller's search basis.
        for clause in re.split(r'[.!?。！？;；\n]',text):
            if re.search(r'\bnot\b|never|不是|并非|不想|不要|忘记|incorrect|wrong',clause,re.I):continue
            birth=re.search(r'\bI was born\b[^.!?]{0,100}?\b((?:18|19|20)\d{2})\b|我[^。]{0,12}?((?:18|19|20)\d{2})年[^。]{0,35}?出生',clause,re.I)
            if birth:
                if len(set(re.findall(r'(?<!\d)(?:18|19|20)\d{2}(?!\d)',clause))) != 1 or re.search(
                    r'\bor\b|about|around|approximately|maybe|perhaps|大约|约|可能|或',clause,re.I):
                    return None
                year=int(birth.group(1) or birth.group(2));births.append(year)
                birth_clauses.append((source.get('id'),source.get('version'),clause.strip()))
                matches=[(name,country,granularity) for (name,country),granularity in PUBLIC_PLACES.items()
                         if name in clause and country in clause]
                matches=[m for m in matches if not any(m[0]!=n[0] and m[0] in n[0] for n in matches)]
                if len(matches)!=1:return None
                name,country,granularity=matches[0]
                birthplaces.append({'name':name,'country':country,'granularity':granularity})
            matches=[(name,country,granularity) for (name,country),granularity in PUBLIC_PLACES.items()
                     if name in clause and country in clause]
            matches=[m for m in matches if not any(m[0]!=n[0] and m[0] in n[0] for n in matches)]
            move_marker=bool(re.search(r'\bI moved\b|我.*搬',clause,re.I))
            parsed_move=False
            if move_marker and len(matches)!=1:unresolved_move=True
            for name,country,granularity in matches:
                residence=re.search(r'\bI (?:lived|was living) in\b.*?\bfrom (\d{4}) to (\d{4})\b',clause,re.I)
                move=re.search(r'\bI moved to\b.*?\bin (\d{4})\b|我((?:18|19|20)\d{2})年.*搬到',clause,re.I)
                if move:
                    parsed_move=True
                    locations.append({'name':name,'country':country,'granularity':granularity,
                        'start':int(move[1] or move[2]),'end':current_year,'confirmed':True})
                if residence:
                    locations.append({'name':name,'country':country,'granularity':granularity,
                        'start':int(residence[1]),'end':int(residence[2]),'confirmed':True})
            if move_marker and not parsed_move:unresolved_move=True
    if len(set(births))>1 or unresolved_move:return None
    places={json.dumps(p,sort_keys=True):p for p in birthplaces}
    if len(places)>1:return None
    def birth_only(event):
        refs=event.get('temporal',{}).get('basis') or event.get('source_refs') or []
        return bool(refs) and all(any(ref.get('source_id')==sid and ref.get('version')==version
            and ref.get('quote','').strip().rstrip('.。') in clause.rstrip('.。')
            for sid,version,clause in birth_clauses) for ref in refs)
    periods=[e.get('temporal') for e in view.get('events',[]) if e.get('status')=='active'
        and e.get('temporal',{}).get('precision') in {'year','range','approximate','day','month'}
        and not birth_only(e)]
    latest=periods[-1] if periods else None
    period={'start':latest.get('year_start'),'end':latest.get('year_end')} if latest else None
    return derive_hypothesis({'birth_year':{'start':births[0],'end':births[0],'confirmed':True} if births else None,
        'birthplace':next(iter(places.values()),None),'period':period,'locations':locations},current_year=current_year)


def ready_projection(state, *, enabled):
    state=deepcopy(state or {})
    if not enabled:return {**state,'enabled':False,'clues':[]}
    return state


async def enrich(storage, project_id, engine, *, selection=None):
    import asyncio
    from .background_skills import ServiceWork, SkillUnavailable, admit
    try:
        admit('memoir-historical-news-research','place_selection')
    except SkillUnavailable:
        return
    view=await asyncio.to_thread(storage.historical_news_basis,project_id)
    if not view:return
    hypothesis=accepted_hypothesis(view, selection=selection)
    if not hypothesis:return
    job=await asyncio.to_thread(storage.begin_historical_news,project_id,hypothesis,view['news_snapshot'])
    if not job:return
    work=ServiceWork('memoir-historical-news-research','place_selection',storage.user_id,project_id,job['id'],research_job_id=job['id'])
    await work.update('running')
    try:
        result=await engine.run(hypothesis)
    except asyncio.CancelledError:
        # A cancelled execution cannot publish. The bounded durable claim
        # expires and a later authenticated request can recover it.
        await work.update('failed')
        raise
    except Exception:
        result={'status':'unavailable','clues':[],'failures':['research_unavailable']}
    try:
        saved=await asyncio.to_thread(storage.finish_historical_news,project_id,job['id'],result)
    except BaseException:
        await work.update('failed')
        raise
    cached=(result.get('accounting') or {}).get('cache')=='hit'
    await work.update('failed' if not saved or result['status']=='unavailable' else 'cached' if cached else 'saved',cached=cached)
