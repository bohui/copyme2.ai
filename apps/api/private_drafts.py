"""Private incremental samples from host-authorized round checkpoints."""
import copy
import os
from types import SimpleNamespace
import httpx

from .codex_runtime import CodexRuntime, normalize_conversation_language
from .memoir_preview import compose_candidate, source_snapshot, incremental_index_request
from .private_draft_jobs import PrivateDraftJobs
from .recall import free_recall_rounds, private_draft_cadence


def enabled():
    return os.getenv('MEMORY_SPARK_PRIVATE_DRAFTS_ENABLED','true').strip().lower() in {'true','1','yes','on'}


def synchronize(storage, project, locale=None):
    path=os.getenv('MEMORY_SPARK_TASK_DB')
    reader=getattr(storage,'private_draft_rounds',None)
    if not path or not callable(reader) or not project:
        return {'status':'collecting','preview':None,'updating':False,'revision':0}
    rounds=reader(project)
    reader=getattr(storage,'composition_memories',None) or getattr(storage,'all_memories',storage.memories)
    rows=reader()
    # Legacy account-wide sources have no project assignment; do not count
    # them or silently assign them to a new interview.
    sources=source_snapshot([r for r in rows if r.get('project_id')==project],project)
    locale=normalize_conversation_language(locale or storage.profile().get('preferred_language'))
    return PrivateDraftJobs(path).synchronize(storage.user_id,project,locale,rounds,sources,
        completed=storage.recall_rounds_completed(),free_limit=free_recall_rounds(),
        cadence=private_draft_cadence(),enabled=enabled(),
        authorization_event_id=storage.private_draft_event(project))


async def validate_job(job_id):
    base=os.environ['MEMORY_SPARK_TASK_STORE_URL'].rstrip('/')
    async with httpx.AsyncClient(timeout=20) as client:
        result=await client.post(base+'/internal/private-drafts/validate/'+job_id,
            headers={'X-Codex-Worker-Secret':os.environ['MEMORY_SPARK_CODEX_WORKER_SECRET']})
        result.raise_for_status()


def request_for_job(job):
    payload=job['payload']
    previous=job['previous']
    key=job['source_key']
    if previous:
        request=copy.deepcopy(previous['request'])
        manuscript=previous['manuscript']
        request['prior_state']={'kind':manuscript['kind'],'revision':job['base_revision'],
            'chapters':[{'revision':job['base_revision'],'approved':False,'human_locked':job['human_locked'],
                         'chapter':c} for c in manuscript['chapters']],
            'last_snapshot_fingerprint':previous['draft']['input_fingerprint']}
    else:
        request={'schema_version':'1.0','project_id':job['project_id'],
            'target':{'locale':job['locale'],'audience':'storyteller','medium':'web'},
            'policy':{'max_chapter_words':7000,'soft_chapter_words':6000,'focus_threshold':0.65,
                      'max_followup_questions':0,'preview_preference':'auto'},
            'assets':[],'periods':[],'events':[],
            'prior_state':{'kind':'none','revision':0,'chapters':[],'last_snapshot_fingerprint':''},
            'authorised_retirements':[],'context':{'style':'plain, warm, faithful'}}
    request.update(request_id=key,event_id=key,sources=payload['sources'])
    request['target']={'locale':job['locale'],'audience':'storyteller','medium':'web'}
    request['trigger']={'type':'new_context' if previous else 'private_draft_checkpoint','confirmed':True,
        'free_rounds_completed':payload['completed'],'free_round_limit':payload['free_limit'],
        'storytelling_confirmation_ref':None,'composition_authorized':False,
        'private_draft_authorized':True,'private_rounds_completed':max(r['ordinal'] for r in payload['rounds']),
        'private_draft_cadence':payload['cadence']}
    if previous:
        # The canonical request remains complete for host-side validation and
        # saved evidence. Draft/review calls use the bounded packet selected by
        # memoir_preview.incremental_model_request instead of rescanning every
        # prior round at each checkpoint.
        request['context']['incremental_model_context'] = 'compact'
    request['snapshot']={'id':key,'policy_epoch':job['source_epoch'],'expected_manuscript_revision':job['base_revision'],
        'retrieval_complete':True,'glossary_version':'1','preferences_version':job['locale']}
    overlap=[r['memory_id'] for r in payload['rounds'] if max(0,job['previous_milestone']-2)<r['ordinal']<=job['previous_milestone'] and r.get('memory_id')]
    # Index only changed evidence and dependencies; all authorized originals
    # remain available for drafting and evidence review.
    index_request=incremental_index_request(request,previous['request'] if previous else None,overlap)
    return request,index_request


async def execute(job_id):
    queue=PrivateDraftJobs(os.environ['MEMORY_SPARK_TASK_DB'])
    job=queue.claim(job_id)
    if not job:
        return {'status':'deferred' if queue.status(job_id) in {'QUEUED','RUNNING'} else 'finished'}
    checkpoint=dict(job['checkpoint'])
    async def progress(phase):
        queue.checkpoint(job_id,job['lease_token'],phase,checkpoint)
    try:
        await validate_job(job_id)
        request,index_request=request_for_job(job)
        result=await compose_candidate(request,CodexRuntime(),SimpleNamespace(user_id=job['user_id']),
            job['project_id'],job['locale'],checkpoint=checkpoint,progress=progress,index_request=index_request)
        if result['status']!='ready':
            queue.finish(job,error='DRAFT_MORE_CONTEXT_NEEDED')
            return {'status':'failed'}
        await validate_job(job_id)
        saved=queue.finish(job,result=result)
        return {'status':'saved' if saved else 'stale'}
    except Exception as error:
        offline=isinstance(error,httpx.HTTPStatusError) and error.response.headers.get('X-Error-Code')=='COMPOSER_PROVIDER_UNAVAILABLE'
        transient=isinstance(error,(TimeoutError,httpx.TransportError)) or isinstance(error,httpx.HTTPStatusError) and error.response.status_code in {429,502,503,504}
        queue.finish(job,error='DRAFT_PROVIDER_UNAVAILABLE' if offline else 'DRAFT_UNAVAILABLE',retryable=transient and not offline)
        return {'status':'retry' if queue.status(job_id)=='QUEUED' else 'failed'}
