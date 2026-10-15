"""Issue 53 acknowledgement experiment, retained for review only.

Not installed by import or enabled in the normal API/private-worker stack.
Explicit install() adds one max-effort acknowledgement request to streamed turns.
This is an isolated prototype, not a production rollout or a latency guarantee.
"""
import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
from uuid import uuid4
from apps.api import lifetime_memory_engine as engine
from apps.api.codex_agent import CodexConnection, provider_config
from apps.api.codex_worker_files import write_config
from apps.api.interview_plan import CollectorVisibleStream, historical_acknowledgement_allowed
from apps.api.lifetime_memory_continuity import validate_governed_collector_result
from apps.api.lifetime_memory_publication import ProviderPublication
from apps.api.lifetime_memory_context import serialize_packet
from apps.api.lifetime_memory_lane_engine import _admission
from apps.api.lifetime_memory_execution import open_execution

original_run = engine.run_governed_collector
ACK_PROMPT = (
    'This is an acknowledgement-only task. Read the ENTIRE current narrator source and all '
    'pinned privacy, language and safety constraints. Return one brief genuine natural '
    'acknowledgement, appropriate to this narrator and their current words. Follow all '
    'acknowledgement rules, including historical-news restrictions. Do not choose or plan '
    'questions, enumerate candidates, extract continuity, count source characters, research, '
    'or compute places. That work is independently handled by the full collector. '
    'No question, invented detail, processing narration, save claim, boilerplate typing text '
    'or private planning. Return only the supplied acknowledgement JSON schema.'
)

async def run_with_parallel_ack(**options):
    emit = options.get('on_delta')
    if emit is None:
        return await original_run(**options)
    shown = None
    async def publish(chunk):
        nonlocal shown
        acknowledgement = json.loads(chunk)['acknowledgement']
        if shown is None:
            shown = acknowledgement
            await emit(json.dumps({'acknowledgement': shown}, ensure_ascii=False))
    context = deepcopy(options['interview_context'])
    async def acknowledge():
        packet = engine.validate_governed_context(options['governed'], context, model=options['model'])
        schema = engine.governed_collector_schema(context)
        schema = {'type':'object', 'additionalProperties':False, 'required':['acknowledgement'],
            'properties':{'acknowledgement':schema['properties']['acknowledgement']}}
        total = options['governed'].budget.count(options['governed'].packet) + options['governed'].budget.count(ACK_PROMPT) + options['governed'].budget.count(serialize_packet(schema)) + options['governed'].budget.framing_headroom
        if total > options['governed'].budget.input_budget: return
        root = Path(options['home_root']).resolve()
        home = root / ('governed-ack-probe-' + str(uuid4()))
        home.mkdir(mode=0o700,parents=True)
        write_config(home, root, os.getuid(), provider_config(options['base_url'], options['model'], governed=True), apply_owner=False)
        publisher = ProviderPublication(os.getenv('MEMOIR_PUBLICATION_DATABASE_URL'),authenticated_owner=packet.identity.owner_id)
        fence = packet.fence.model_dump(mode='json')
        def admission():return _admission(publisher, deepcopy(fence))
        visible = CollectorVisibleStream()
        async def delta(chunk):
            acknowledgement = visible.feed(chunk)
            if acknowledgement and historical_acknowledgement_allowed(acknowledgement, context):
                await publish(json.dumps({'acknowledgement':acknowledgement},ensure_ascii=False))
        try:
            async with asyncio.timeout(25):
                async with CodexConnection(options['command'],home,provider_env={'MEMORY_SPARK_LLM_API_KEY':options['api_key']},timeout=25,request_admission=admission) as connection:
                    opened = await open_execution(connection,thread_id=None,compatible=False,
                        start_params={'cwd':str(home),'ephemeral':True,'modelProvider':'llm_provider','model':options['model'],
                            'approvalPolicy':'never','sandbox':'read-only','baseInstructions':options['governed'].packet},identity=packet.identity.model_dump(mode='json'))
                    await connection.turn(opened['thread_id'],ACK_PROMPT,output_schema=schema,on_delta=delta,effort=options.get('effort'))
        except Exception as error:
            print(json.dumps({'parallel_ack_probe':'unavailable','exception_type':type(error).__name__}),flush=True)
    completed = None
    async def events(event):
        nonlocal completed
        if event.get('type') == 'provider_complete': completed = event
        elif options.get('on_event'): await options['on_event'](event)
    early = asyncio.create_task(acknowledge())
    try:
        result = await original_run(**{**options,'on_delta':publish,'on_event':events})
        if shown is not None:
            value=json.loads(result['reply']);value['acknowledgement']=shown
            validate_governed_collector_result(value,context)
            result={**result,'reply':json.dumps(value,ensure_ascii=False,separators=(',',':'))}
        if completed and options.get('on_event'):
            await options['on_event']({**completed,'data':{**completed['data'],'reply':result['reply']}})
        return result
    finally:
        early.cancel()
        await asyncio.gather(early,return_exceptions=True)
def install():
    engine.run_governed_collector = run_with_parallel_ack
