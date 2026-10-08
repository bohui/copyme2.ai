import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(new URL('../../apps/web/client/memoir/client.js', import.meta.url), 'utf8');
const photo = {image_url:'https://images.example/street.jpg', title:'Street <script>', date_expression:'1983'};
const key = photo.image_url;
const saved = {favorites:[{...photo, key, place:'Chengde'}], selected:key};

function harness(api = async () => saved) {
  const state = {project:{id:'p', profile:{}}, navigationGeneration:0, supabase:{user:{id:'owner'}}};
  const notices = [];
  const context = vm.createContext({state, api, profile:() => state.project.profile, render() {},
    document:{querySelector:() => null, querySelectorAll:() => []},
    toast:message => notices.push(message), translate:key => key, translateWith:key => key,
    escapeHtml:value => String(value ?? '').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;'),
    referenceUrl:value => value, photoSearchPeriod:() => '1980s',
    pictureWall:photos => JSON.stringify(photos),
  });
  for (const name of ['captureProjectScope','isCurrentProjectScope','photoMemoryState','photoMemoryControls',
    'favoritePhotoWall','selectedPhotoCue','savePhotoMemory', 'mergeProfileUpdates', 'preserveConversationLocale', 'saveProfileUpdates', 'sendChatMessage']) {
    vm.runInContext(source.match(new RegExp(`(?:async )?function ${name}\\([^]*?\\n\\}`))[0], context);
  }
  return {context, state, notices};
}

test('photo selection saves reference metadata before exposing its favorite and conversation cue', async () => {
  let finish;
  const calls=[];
  const h = harness((url, options) => {calls.push({url, body:JSON.parse(options.body)}); return new Promise(resolve => {finish=resolve;});});
  const task = h.context.savePhotoMemory('select', photo);
  assert.ok(h.state.photoMemoryTask);
  assert.equal(h.context.selectedPhotoCue(), '');
  await h.context.savePhotoMemory('favorite', {...photo,image_url:'other'});
  assert.equal(calls.length, 1, 'duplicate interaction was accepted while saving');
  finish(saved);
  await task;
  assert.equal(calls[0].url, '/v1/projects/p/photo-memories');
  assert.equal(calls[0].body.action,'select');
  assert.equal(h.context.photoMemoryState().selected,key);
  assert.match(h.context.selectedPhotoCue(), /Street &lt;script>/);
  assert.match(h.context.favoritePhotoWall(), /street\.jpg/);
  assert.equal(h.state.photoMemoryTask,null);
});

test('failed photo saves preserve the previous cue and offer a retry', async () => {
  const h=harness(async () => {throw Object.assign(new Error('busy'),{status:409});});
  h.state.project.profile.photo_memories={p:saved};
  await h.context.savePhotoMemory('clear');
  assert.equal(h.context.photoMemoryState().selected,key);
  assert.match(h.notices[0], /photoSaveBusy/);
  assert.equal(h.state.photoMemoryTask,null);
});

test('late photo responses cannot select a photo in another project or principal', async () => {
  for (const change of [h => {h.state.project={id:'other',profile:{}};}, h => {h.state.supabase.user.id='another-owner';}]) {
    let finish;
    const h=harness(() => new Promise(resolve => {finish=resolve;}));
    const task=h.context.savePhotoMemory('select',photo);
    change(h);
    finish(saved);
    await task;
    assert.equal(h.state.project.profile.photo_memories,undefined);
  }
});

test('photo controls expose keyboard selection, pressed favorites and escaped metadata', () => {
  const h=harness();
  h.state.project.profile.photo_memories={p:saved, other:{favorites:[],selected:null}};
  const controls=h.context.photoMemoryControls(photo, {place:'Chengde'}, '<img>', true);
  assert.match(controls.media, /type="button"/);
  assert.match(controls.media, /aria-pressed="true"/);
  assert.match(controls.media, /Street &lt;script>/);
  assert.match(controls.favorite, /data-photo-memory="unfavorite"/);
  h.state.project.id='other';
  assert.doesNotMatch(h.context.photoMemoryControls(photo,null,'<img>',true).favorite, /aria-pressed="true"/);
  assert.equal(h.context.selectedPhotoCue(),'');
});

test('a delayed place/profile save cannot replace a newly committed photo cue', async () => {
  let finish;
  const h=harness(() => new Promise(resolve => {finish=resolve;}));
  const update=h.context.saveProfileUpdates({name:'New name'},'p');
  h.state.project.profile.photo_memories={p:saved};
  finish({id:'p',revision:2,profile:{name:'New name',photo_memories:{}}});
  await update;
  assert.equal(h.context.photoMemoryState().selected,key);
  assert.equal(h.state.project.profile.name,'New name');
});

test('a voice answer waits for photo persistence and respects cancellation while waiting', async () => {
  let finish;
  const h=harness(() => new Promise(resolve => {finish=resolve;}));
  h.state.voiceMode=true;
  const saving=h.context.savePhotoMemory('select',photo);
  let sent=false;
  const sending=h.context.sendChatMessage({voiceTurn:true}).then(() => {sent=true;});
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(sent,false);
  h.state.voiceMode=false;
  finish(saved);
  await Promise.all([saving,sending]);
  assert.equal(sent,true);
  assert.equal(h.context.photoMemoryState().selected,key);
});

function deferred() {
  let resolve;
  const promise = new Promise(done => {resolve = done;});
  return {promise, resolve};
}

function refreshHarness({snapshot, delayedAt, saveResult = saved, failSave = false}) {
  const pending = deferred();
  const reached = deferred();
  const h = harness(async (url, options) => {
    if (options?.method === 'PUT') {
      if (failSave) throw new Error('offline');
      return saveResult;
    }
    if (url.endsWith('/journey')) return {};
    if (delayedAt === 'project') {reached.resolve(); return pending.promise;}
    return {id:'p', profile:{photo_memories:{p:snapshot}}};
  });
  Object.assign(h.context, {
    mergePlaces:places => places, refreshStageReadiness() {}, refreshPrivateDraft() {},
    storyApi:async () => {
      if (delayedAt === 'profile') {reached.resolve(); return pending.promise;}
      return {photo_memories:{p:snapshot}};
    },
  });
  h.state.supabase.accessToken = 'synthetic';
  for (const name of ['refreshProject']) {
    vm.runInContext(source.match(new RegExp(`(?:async )?function ${name}\\([^]*?\\n\\}`))[0], h.context);
  }
  return {...h, pending, reached};
}

const empty = {favorites:[], selected:null};
const cleared = {favorites:saved.favorites, selected:null};
for (const delayedAt of ['project', 'profile']) {
  for (const [action, before, committed] of [
    ['select', empty, saved], ['clear', saved, cleared], ['unfavorite', saved, empty],
  ]) {
    test(`refresh paused at ${delayedAt} cannot undo acknowledged ${action}`, async () => {
      const h = refreshHarness({snapshot:before, delayedAt, saveResult:committed});
      h.state.project.profile.photo_memories = {p:before};
      const refreshing = h.context.refreshProject();
      await h.reached.promise;
      await h.context.savePhotoMemory(action, action === 'clear' ? null : photo);
      assert.equal(h.context.photoMemoryState().selected, committed.selected);
      h.pending.resolve(delayedAt === 'project'
        ? {id:'p', profile:{photo_memories:{p:before}}} : {photo_memories:{p:before}});
      await refreshing;
      assert.deepEqual(JSON.parse(JSON.stringify(h.context.photoMemoryState())), committed);
    });
  }
  test(`refresh paused at ${delayedAt} stays scoped to its project and principal`, async () => {
    for (const change of [h => {h.state.project={id:'other',profile:{name:'other'}};},
      h => {h.state.supabase.user.id='other'; h.state.project.profile={name:'other'};},
      h => {h.state.navigationGeneration++; h.state.project.profile={name:'other'};}]) {
      const h=refreshHarness({snapshot:saved, delayedAt});
      const refreshing=h.context.refreshProject();
      await h.reached.promise;
      change(h);
      const current=h.state.project.profile;
      h.pending.resolve(delayedAt === 'project' ? {id:'p',profile:{photo_memories:{p:saved}}} : {photo_memories:{p:saved}});
      await refreshing;
      assert.equal(h.state.project.profile,current);
    }
  });
}

test('failed photo commands do not prevent a later refresh from loading authoritative state', async () => {
  const h=refreshHarness({snapshot:saved, delayedAt:'profile', failSave:true});
  const refreshing=h.context.refreshProject();
  await h.reached.promise;
  await h.context.savePhotoMemory('clear');
  h.pending.resolve({photo_memories:{p:cleared}});
  await refreshing;
  assert.equal(h.context.photoMemoryState().selected,null);
});

test('a refresh started after a committed mutation can load a subsequent authoritative change', async () => {
  const h=refreshHarness({snapshot:empty, delayedAt:'profile'});
  await h.context.savePhotoMemory('select',photo);
  const refreshing=h.context.refreshProject();
  await h.reached.promise;
  h.pending.resolve({photo_memories:{p:cleared}});
  await refreshing;
  assert.equal(h.context.photoMemoryState().selected,null);
});
