import { readMemoirClientSource } from './helpers/memoir-source.mjs';
import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';

const source = readMemoirClientSource();
const tick = () => new Promise(resolve => setImmediate(resolve));
async function settled(state) {
  const deadline = Date.now() + 1000;
  while (state.privateDraftStream && Date.now() < deadline) await new Promise(resolve=>setTimeout(resolve,5));
  assert.equal(state.privateDraftStream,null);
}
function setup(overrides = {}) {
  let requests = 0, reads = 0;
  const state = {project:{id:'p'}, supabase:{user:{id:'owner'},accessToken:'token'}, chat:[],
    showThinkingSteps:true, showDraftUpdates:true, ...overrides};
  const context = vm.createContext({state, AbortController, TextDecoder, setTimeout, clearTimeout,
    profile:()=>({preferred_language:'zh-CN'}), currentUiLocale:()=> 'zh-CN', currentSectionRework:()=>null,
    memoirApiPath:path=>path, freeRecallFinished:()=>false, render(){}, persistChatHistory(){},
    updateBackgroundComposerProgress(){}, updateStreamingAssistantMessage(){}, translate:String,
    storyApi:async()=>{reads++;return {updating:true};},
    fetch:async(_path, options)=>{requests++;assert.equal(options.headers.Accept,'application/x-ndjson');
      assert.equal(options.headers.Authorization,'Bearer token');return response([
        {type:'draft_update',data:{updating:true,preview:{text:'童年'}}},
        {type:'draft_update',data:{updating:false,preview:{text:'童年回忆'}}}, {type:'complete'}]);}});
  for (const name of ['captureProjectScope','isCurrentProjectScope','consumePrivateDraftStream','applyPrivateDraftUpdate','refreshPrivateDraft']) {
    const match = source.match(new RegExp(`(?:async )?function ${name}\\([^]*?\\n\\}`));
    assert.ok(match, `missing ${name}`);vm.runInContext(match[0], context);
  }
  return {context, state, requests:()=>requests, reads:()=>reads};
}
function response(events, split = false) {
  const bytes = new TextEncoder().encode(events.map(e=>JSON.stringify(e)).join('\n')+'\n');
  return {ok:true,headers:{get:()=> 'application/x-ndjson'},body:new ReadableStream({start(controller){
    if(split) for (const byte of bytes) controller.enqueue(Uint8Array.of(byte));
    else controller.enqueue(bytes);
    controller.close();
  }})};
}

for (const rounds of [5, 20]) {
  test(`restored ${rounds}-round entitlement rechecks the saved draft with debugging off`, async () => {
    const s = setup({showDraftUpdates:false, showThinkingSteps:false});
    const paths = [];
    s.context.storyApi = async path => {
      paths.push(path);
      if (path === '/v1/story/state') return {
        family_features_enabled:false,
        recall_status:{rounds_completed:rounds, free_rounds:20, paid:true, payment_required:false},
      };
      assert.equal(path, '/v1/story/private-draft?project_id=p&language=zh-CN');
      return {status:'ready', updating:false, preview:{title:'Saved garden', text:'Saved synthetic testimony'}};
    };
    for (const name of ['freeRecallFinished', 'refreshFamilyEntitlement']) {
      vm.runInContext(source.match(new RegExp(`(?:async )?function ${name}\\([^]*?\\n\\}`))[0], s.context);
    }
    // Reload starts project hydration before the entitlement request completes.
    await s.context.refreshPrivateDraft();
    assert.deepEqual(paths, []);
    await s.context.refreshFamilyEntitlement();
    await tick();
    assert.deepEqual(paths, ['/v1/story/state', ...(rounds === 20
      ? ['/v1/story/private-draft?project_id=p&language=zh-CN'] : [])]);
    assert.equal(s.state.privateDraft?.preview?.text, rounds === 20 ? 'Saved synthetic testimony' : undefined);
    assert.equal(s.requests(), 0, 'Debug-off restoration must not open a draft stream');
  });
}

test('one request delivers draft changes without scheduling HTTP polling', async()=>{
  const s=setup();
  await s.context.refreshPrivateDraft();
  await tick();
  assert.equal(s.requests(),1);assert.equal(s.reads(),0);
  assert.equal(s.state.privateDraft.preview.text,'童年回忆');
  assert.equal(s.state.privateDraft.updating,false);
});

test('NDJSON handles split Unicode, multiple frames and heartbeat', async()=>{
  const s=setup();const seen=[];
  await s.context.consumePrivateDraftStream(response([{type:'heartbeat'},
    {type:'draft_update',data:{updating:false,preview:{text:'童年回忆'}}},{type:'complete'}],true),
    value=>seen.push(value),new AbortController().signal);
  assert.equal(seen.length,1);assert.equal(seen[0].preview.text,'童年回忆');
});

test('truncated pending stream is interrupted rather than treated as completed', async()=>{
  const s=setup();
  await assert.rejects(s.context.consumePrivateDraftStream(response([
    {type:'draft_update',data:{updating:true}}]),()=>{},new AbortController().signal),
    error=>error.retryable===true);
});

test('transport interruption reconnects with backoff and a fresh snapshot', async()=>{
  const s=setup();let requests=0;const waits=[];
  s.context.setTimeout=(fn,ms)=>{waits.push(ms);return setTimeout(fn,0);};
  s.context.fetch=async()=>++requests === 1
    ? response([{type:'draft_update',data:{updating:true,preview:{text:'Earlier'}}}])
    : response([{type:'draft_update',data:{updating:false,preview:{text:'Latest'}}},{type:'complete'}]);
  await s.context.refreshPrivateDraft();
  await settled(s.state);
  assert.equal(requests,2);assert.deepEqual(waits,[1000]);
  assert.equal(s.state.privateDraft.preview.text,'Latest');
});

test('reconnect attempts are bounded and an HTTP error does not loop', async()=>{
  const s=setup();let requests=0;const waits=[];
  s.context.setTimeout=(fn,ms)=>{waits.push(ms);return setTimeout(fn,0);};
  s.context.fetch=async()=>{requests++;return response([{type:'draft_update',data:{updating:true}}]);};
  await s.context.refreshPrivateDraft();await settled(s.state);
  assert.equal(requests,3);assert.deepEqual(waits,[1000,2000]);assert.equal(s.state.privateDraft.updating,false);
  requests=0;s.context.fetch=async()=>{requests++;return {ok:false,status:500};};
  await s.context.refreshPrivateDraft();await tick();
  assert.equal(requests,1);assert.equal(s.state.privateDraft.error,'PRIVATE_DRAFT_UNAVAILABLE');
});

test('server failure preserves the saved preview and shows retry instead of updating forever', async()=>{
  const s=setup({privateDraft:{preview:{text:'Saved memory'},updating:true}});
  s.context.fetch=async()=>response([{type:'error',code:'PRIVATE_DRAFT_UNAVAILABLE'}]);
  await s.context.refreshPrivateDraft();await tick();
  assert.equal(s.state.privateDraft.preview.text,'Saved memory');
  assert.equal(s.state.privateDraft.updating,false);
  assert.equal(s.state.privateDraft.error,'PRIVATE_DRAFT_UNAVAILABLE');
});

test('duplicate refreshes share an active stream and navigation aborts its reader', async()=>{
  const s=setup();let controller, requestSignal, requests=0;
  s.context.fetch=async(_path,options)=>{
    requests++;requestSignal=options.signal;
    return {ok:true,headers:{get:()=> 'application/x-ndjson'},body:new ReadableStream({
      start(value){controller=value;value.enqueue(new TextEncoder().encode('{"type":"draft_update","data":{"updating":true}}\n'));},
      cancel(){controller=null;}
    })};
  };
  await s.context.refreshPrivateDraft();await s.context.refreshPrivateDraft();
  assert.equal(requests,1);
  s.state.privateDraftStream.controller.abort();
  s.state.navigationGeneration=1;s.state.project={id:'other'};
  await tick();
  assert.equal(requestSignal.aborted,true);assert.equal(controller,null);
  assert.equal(s.state.privateDraft.error,undefined);
});

test('debug disabled makes no early draft requests; final Chapters still load once', async()=>{
  const s=setup({showDraftUpdates:false,showThinkingSteps:false});await s.context.refreshPrivateDraft();
  assert.equal(s.requests(),0);assert.equal(s.reads(),0);
  s.context.freeRecallFinished=()=>true;
  await s.context.refreshPrivateDraft();
  assert.equal(s.requests(),0);assert.equal(s.reads(),1);
});

test('thinking steps alone stream progressive drafts without the draft-update flag', async()=>{
  const s=setup({showDraftUpdates:false});
  await s.context.refreshPrivateDraft();await settled(s.state);
  assert.equal(s.requests(),1);assert.equal(s.reads(),0);
  assert.equal(s.state.privateDraft.preview.text,'童年回忆');
});

test('draft streaming works with thinking steps disabled',async()=>{
  const s=setup({showThinkingSteps:false});
  await s.context.refreshPrivateDraft();await settled(s.state);
  assert.equal(s.requests(),1);assert.equal(s.reads(),0);
  assert.equal(s.state.privateDraft.preview.text,'童年回忆');
});

test('an update preserves an opened preview before the toggle callback has run',async()=>{
  const s=setup();s.context.document={querySelector:()=>({open:true})};
  await s.context.refreshPrivateDraft();await settled(s.state);
  assert.equal(s.state.privateDraftExpanded,true);
});

test('locale switch aborts the old subscription and rejects its late updates', async()=>{
  const s=setup();let oldSignal;
  s.context.fetch=async(_path,options)=>{
    oldSignal ||= options.signal;
    return response([{type:'draft_update',data:{updating:false,locale:s.state.privateDraftLocale||'zh-CN'}},{type:'complete'}]);
  };
  await s.context.refreshPrivateDraft();s.state.privateDraftLocale='en-AU';
  await s.context.refreshPrivateDraft();await tick();
  assert.equal(oldSignal.aborted,true);assert.equal(s.state.privateDraft.locale,'en-AU');
});
