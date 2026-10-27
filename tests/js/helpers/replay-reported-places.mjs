// Actual canonical SQL/API output must not activate a relative's place on the client.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {applyDerivedWorkspace} from '../../../apps/web/client/memoir/derived-workspace.mjs';
import {readMemoirClientSource} from './memoir-source.mjs';

const {ready,expected_places:expected,expect_no_research:noResearch} = JSON.parse(readFileSync(0,'utf8'));
const update = ready.derived_workspace;
const old = {place:'承德',hierarchy:['Earth','中国','承德'],granularity:'city',status:'active'};
const state = {project:{id:update.project_id,profile:{memory_places:[old]}},placeJourney:old,
  selectedPlace:'stale-father-place',workspaceActivatedProjectId:update.project_id,placeWorkspaceMap:{}};
assert.equal(applyDerivedWorkspace(state,update),true);
assert.deepEqual(state.project.profile.memory_places.map(p=>p.place),expected);
assert.equal(state.placeJourney?.place ?? null,expected.at(-1) ?? null);
if (noResearch) {
  assert.ok(state.project.profile.memory_places.every(p=>p.research == null));
  assert.equal(state.placeJourney?.research ?? null,null);
}
if (!expected.length) {
  assert.equal(state.selectedPlace,null);
  assert.equal(state.workspaceActivatedProjectId,update.project_id);
  assert.equal(state.placeWorkspaceMap,null);
}

const context = vm.createContext({state, composingWorkspaceActive:() => false, freeRecallFinished:() => false,
  placeWorkspaceSelection:() => state.placeJourney, placeMapTarget:place => place});
const source = readMemoirClientSource();
for (const name of ['workspaceContentAvailable', 'workspaceHasContent', 'workspaceIsVisible']) {
  vm.runInContext(source.match(new RegExp(`function ${name}\\([^]*?\\n\\}`))[0], context);
}
assert.equal(context.workspaceIsVisible(),true,'A background snapshot must not hide an activated workspace');
state.workspaceCollapsed = true;
assert.equal(context.workspaceIsVisible(),false,'The narrator can still collapse the workspace');
state.workspaceCollapsed = false;
state.project = {id:'another-project',profile:{}};
state.placeJourney = null;
assert.equal(context.workspaceIsVisible(),false,'Activation must stay scoped to the original project');
