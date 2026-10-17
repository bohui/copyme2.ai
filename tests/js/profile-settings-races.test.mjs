import { readMemoirClientSource } from './helpers/memoir-source.mjs';
import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';

const source = readMemoirClientSource();
const automation = revision => ({schema_version:1, revision, auto_enabled:true, stopped:false,
  manual_complete:false, field_locks:{avatar_style:'manual', name:'manual'}});
const extract = name => source.match(new RegExp(`(?:async )?function ${name}\\([^]*?\\n\\}`))[0];
function harness(profile) {
  const state = {project:{id:'profile-test', revision:1, profile}, supabase:{user:{id:'owner'}, accessToken:'fixture'}};
  const context = vm.createContext({state, toast() {}, translateWith: String});
  for (const name of ['captureProjectScope', 'isCurrentProjectScope', 'profile', 'preserveConversationLocale',
    'mergeProfileUpdates', 'saveProfileUpdates']) vm.runInContext(extract(name), context);
  return {state, context};
}

test('stale profile and reply hints cannot override chosen artwork or refill a confirmed blank', () => {
  const {state, context} = harness({avatar_style:'female', profile_automation:automation(7)});
  for (const stale of [{avatar_style:'male', name:'Guessed'},
    {avatar_style:'male', name:'Guessed', profile_automation:automation(6)}]) {
    const next = context.preserveConversationLocale(stale, state.project.profile);
    assert.equal(next.avatar_style, 'female');
    assert.equal(Object.hasOwn(next, 'name'), false);
    assert.equal(next.profile_automation.revision, 7);
    assert.equal(context.mergeProfileUpdates(stale), null);
  }
  const newer = context.preserveConversationLocale({avatar_style:'male', profile_automation:automation(8)}, state.project.profile);
  assert.equal(newer.avatar_style, 'male');
});

test('a pending workspace save cannot erase settings confirmed after it started', async () => {
  const {state, context} = harness({avatar_style:'male'});
  let finish, patch;
  context.api = async (_path, options) => {
    patch = JSON.parse(options.body);
    return new Promise(resolve => { finish = resolve; });
  };
  const pending = context.saveProfileUpdates({birth_place:'Sydney'});
  state.project.profile = {avatar_style:'female', name:null, birth_place:'Sydney', profile_automation:automation(2)};
  finish({id:'profile-test', revision:2, profile:patch.profile});
  await pending;
  assert.equal(state.project.profile.avatar_style, 'female');
  assert.equal(state.project.profile.name, null);
  assert.equal(state.project.profile.profile_automation.revision, 2);
});

test('read-only automation is never included in generic workspace profile writes', async () => {
  const {context} = harness({avatar_style:'female', profile_automation:automation(2)});
  let patch;
  context.api = async (_path, options) => {
    patch = JSON.parse(options.body);
    return {id:'profile-test', revision:2, profile:patch.profile};
  };
  await context.saveProfileUpdates({memory_places:[]});
  assert.equal(Object.hasOwn(patch.profile, 'profile_automation'), false);
  assert.equal(patch.profile.avatar_style, 'female');
});

function settingsHandler(recording = false) {
  const h = harness({avatar_style:'male'});
  h.state.recording = recording;
  let settings, open, renders = 0, menuUpdates = 0, writes = 0;
  const settingsButton = {addEventListener: (_event, handler) => {open = handler;}};
  const menu = {querySelector: selector => selector === '[data-profile-trigger]' ? {addEventListener() {}}
    : selector === '.profile-dropdown' ? {} : selector === "[data-profile-action='settings']" ? settingsButton : null};
  Object.assign(h.context, {$: () => menu, closeProfileMenu() {}, openProfileSettings: options => {settings = options;},
    storyApi() {}, applyProfileUiLocale: async () => {}, persistCommittedFirstReplyUiLocale: async () => {},
    conversationLanguage: () => 'en-AU', render: () => renders++, refreshProfileMenu: () => menuUpdates++,
    signOut() {}, reviewCollection() {}, api: async () => {writes++;}});
  vm.runInContext(extract('bindProfileMenu'), h.context);
  h.context.bindProfileMenu();
  open();
  return {...h, settings, counts: () => ({renders, menuUpdates, writes})};
}

test('a settings callback opened under another account cannot change the current project', async () => {
  const h = settingsHandler();
  h.state.supabase.user.id = 'other-owner';
  assert.equal(h.settings.isCurrent(), false);
  await h.settings.onSave({avatar_style:'female', profile_automation:automation(2)});
  assert.equal(h.state.project.profile.avatar_style, 'male');
  assert.deepEqual(h.counts(), {renders:0, menuUpdates:0, writes:0});
});

for (const recording of [false, true]) test(`canonical settings save preserves recording=${recording} and avoids a second profile write`, async () => {
  const h = settingsHandler(recording);
  await h.settings.onSave({avatar_style:'female', profile_automation:automation(2)});
  assert.equal(h.state.project.profile.avatar_style, 'female');
  assert.deepEqual(h.counts(), {renders:recording ? 0 : 1, menuUpdates:recording ? 1 : 0, writes:0});
});
