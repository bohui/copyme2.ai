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
  const s=state();s.workspaceActivatedProjectId='p';s.placeWorkspaceMap={projectId:'p',key:'old'};
  applyDerivedWorkspace(s,update([place('Hobart')],3));
  assert.equal(applyDerivedWorkspace(s,{...update([],4),policy_epoch:2}),true);
  assert.equal(s.placeJourney,null);
  assert.equal(s.project.profile.memory_places.length,0);
  assert.equal(s.recording,true);
  assert.equal(s.workspaceActivatedProjectId,'p');
  assert.equal(s.placeWorkspaceMap,null);
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
test('independent updates preserve photos and grouping on still-authorized places',()=>{
  const s=state();s.project.profile.memory_places[0].pictures=[{id:'photo-1',source_url:'https://synthetic.invalid/photo'}];
  s.project.profile.memory_places[0].map_city_key='saved-city';
  applyDerivedWorkspace(s,update([place('Hobart'),place('Sydney',2)]));
  const kept=s.project.profile.memory_places.find(p=>p.place==='Hobart');
  assert.equal(kept.pictures[0].id,'photo-1');
  assert.equal(kept.map_city_key,'saved-city');
});
test('a policy revision discards old photo and grouping decorations even for the same place',()=>{
  const s=state();s.project.profile.memory_places[0].pictures=[{id:'old-photo'}];
  applyDerivedWorkspace(s,update([place('Hobart')]));
  applyDerivedWorkspace(s,{...update([place('Hobart')],3),policy_epoch:2});
  assert.equal(s.project.profile.memory_places[0].pictures,undefined);
});

test('repeated background snapshots preserve photo search scope and completion',()=>{
  const s=state();
  const snapshot=update([place('Hobart')]);
  applyDerivedWorkspace(s,snapshot);
  Object.assign(s.project.profile.memory_places[0],{photo_search_period:'',photo_search_place:'Hobart',
    photo_search_policy:'place-source-rights-v13',photo_search_complete:true,photo_search_at:123,
    photo_next_cursor:null});
  assert.equal(applyDerivedWorkspace(s,snapshot),false);
  assert.equal(s.project.profile.memory_places[0].photo_search_complete,true);
});
