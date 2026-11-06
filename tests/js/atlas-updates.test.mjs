import test from 'node:test';
import assert from 'node:assert/strict';
import {createAtlasUpdates} from '../../apps/web/client/memoir/atlas-updates.mjs';

test('one Atlas connection receives fragmented updates, ignores heartbeats and closes on navigation', async t => {
  t.mock.timers.enable({apis:['setTimeout']});
  const settle = () => new Promise(resolve => setImmediate(resolve));
  const requests = [], snapshots = [], encoder = new TextEncoder();
  let projectId = 'project';
  const atlas = createAtlasUpdates({scope:()=>({projectId}), current:captured=>captured.projectId===projectId,
    token:()=> 'fixture', url:id=>`/atlas-events?project_id=${id}`, onUpdate:snapshot=>snapshots.push(snapshot),
    request:async (path,options)=>new Response(new ReadableStream({start(controller){
      requests.push({path,options,controller});
      options.signal.addEventListener('abort',()=>controller.close(),{once:true});
    }}),{headers:{'Content-Type':'text/event-stream'}})});
  t.after(()=>atlas.stop());
  assert.equal(atlas.start(),true);
  assert.equal(atlas.start(),false);
  const [{controller,options}]=requests;
  assert.equal(options.headers.Authorization,'Bearer fixture');
  controller.enqueue(encoder.encode('event: atlas-'));
  controller.enqueue(encoder.encode('update\ndata: {"project_id":"project","stages":{}}\n\n'));
  await settle();
  assert.deepEqual(snapshots,[{project_id:'project',stages:{}}]);
  controller.enqueue(encoder.encode(': heartbeat\n\n'));
  t.mock.timers.tick(240_000);
  await settle();
  assert.equal(snapshots.length,1);
  assert.equal(requests.length,1);
  controller.enqueue(encoder.encode('event: atlas-update\ndata: {"project_id":"project","map_events":{"events":[{"id":"memory"}]}}\n\n'));
  await settle();
  assert.equal(snapshots[1].map_events.events[0].id,'memory');
  projectId = 'other';
  atlas.start();
  assert.equal(options.signal.aborted,true);
  assert.equal(requests[1].path,'/atlas-events?project_id=other');
  await settle();
  assert.equal(snapshots.length,2);
});

test('a connection that repeatedly opens and closes cannot create an idle retry loop', async t => {
  t.mock.timers.enable({apis:['setTimeout']});
  const settle = () => new Promise(resolve => setImmediate(resolve));
  let requests = 0;
  const atlas = createAtlasUpdates({scope:()=>({projectId:'project'}), current:()=>true, token:()=> 'fixture',
    url:()=>'/atlas-events',onUpdate(){},request:async()=>{
      requests++;
      return new Response('event: atlas-update\ndata: {"project_id":"project"}\n\n',{headers:{'Content-Type':'text/event-stream'}});
    }});
  t.after(()=>atlas.stop());
  atlas.start();
  await settle();
  for (let tick=0; tick<4; tick++) { t.mock.timers.tick(5_000); await settle(); }
  assert.equal(requests,3);
});
