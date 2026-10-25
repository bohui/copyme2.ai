// Actual canonical SQL/API output must not activate a relative's place on the client.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {applyDerivedWorkspace} from '../../../apps/web/client/memoir/derived-workspace.mjs';

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
  assert.equal(state.workspaceActivatedProjectId,null);
  assert.equal(state.placeWorkspaceMap,null);
}
