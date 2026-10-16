import test from 'node:test';
import assert from 'node:assert/strict';
import {applyDerivedWorkspace} from '../../apps/web/client/memoir/derived-workspace.mjs';

const place=(name,sequence=1)=>({schema_version:1,place:name,hierarchy:['Earth','Australia',name],granularity:'city',source_sequence:sequence,status:'active',revision:1});
const state=()=>({project:{id:'p',profile:{preferred_language:'zh-CN',memory_places:[place('Hobart')]}},placeJourney:place('Hobart'),selectedPlace:'selected',lifeStage:'childhood',workspaceCollapsed:true,recording:true,workspaceTab:'memoir'});
const update=(places,revision=2)=>({project_id:'p',source_revision:revision,policy_epoch:1,places,authoritative:true});
test('background places retain selection, recording, language and activated workspace',()=>{
  const s=state();
  assert.equal(applyDerivedWorkspace(s,update([place('Hobart'),place('Sydney',2)])),true);
  assert.equal(s.project.profile.memory_places.length,2);
  assert.equal(s.project.profile.preferred_language,'zh-CN');
  assert.equal(s.selectedPlace,'selected');
  assert.equal(s.recording,true);
  assert.equal(s.workspaceCollapsed,true);
  assert.equal(s.lifeStage,'childhood');
  assert.equal(s.placeJourney.place,'Hobart');
});
test('failed, empty delta, stale and other-project results cannot clear the last valid workspace',()=>{
  const s=state();const before=structuredClone(s);
  for(const value of [null,{}, {...update([]),authoritative:false}, {...update([place('Sydney')]),project_id:'other'}]) {
    assert.equal(applyDerivedWorkspace(s,value),false);
    assert.deepEqual(s,before);
  }
  applyDerivedWorkspace(s,update([place('Hobart')],4));
  assert.equal(applyDerivedWorkspace(s,update([place('Sydney')],3)),false);
  assert.equal(s.project.profile.memory_places[0].place,'Hobart');
});
test('an authoritative privacy revocation removes inaccessible places',()=>{
  const s=state();applyDerivedWorkspace(s,update([place('Hobart')],3));
  assert.equal(applyDerivedWorkspace(s,{...update([],4),policy_epoch:2}),true);
  assert.equal(s.placeJourney,null);
  assert.equal(s.project.profile.memory_places.length,0);
  assert.equal(s.recording,true);
});
test('a first accepted background place activates only the place state',()=>{
  const s=state();s.project.profile.memory_places=[];s.placeJourney=null;s.selectedPlace=null;
  applyDerivedWorkspace(s,update([place('Sydney')]));
  assert.equal(s.placeJourney.place,'Sydney');
  assert.equal(s.recording,true);
  assert.equal(s.workspaceCollapsed,true);
});
test('a revoked transient place is removed even when profile history was already empty',()=>{
  const s=state();s.project.profile.memory_places=[];
  assert.equal(applyDerivedWorkspace(s,{...update([],5),policy_epoch:2}),true);
  assert.equal(s.placeJourney,null);
});
