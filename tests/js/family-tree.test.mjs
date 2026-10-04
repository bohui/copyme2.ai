import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(new URL('../../apps/web/client/memoir/client.js', import.meta.url), 'utf8');
const messages = JSON.parse(fs.readFileSync(new URL('../../apps/web/messages/en-AU.json', import.meta.url))).Memoir.workspace;
const extract = name => source.match(new RegExp(`function ${name}\\([^]*?\\n\\}`))[0];
const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[char]));

function setup(overrides = {}) {
  const state = { project: {id:'project', profile:{name:'Avery'}}, selectedFamilyPerson:null, familyPhotoTask:null,
    people:[{id:'mum', name:'Mei', family_title:'mother', introduction:'She grew roses.', birth_date_expression:'around 1940'},
      {id:'me', name:'Avery', family_title:'self'}], relationships:[], ...overrides };
  const translate = key => messages[key.split('.').at(-1)] || key;
  const context = vm.createContext({state, URL, escapeHtml, formatText:escapeHtml, translate,
    translateWith:(key, values) => translate(key).replace(/\{(\w+)\}/g, (_, name) => values[name]),
    profile:() => state.project.profile, referencesWorkspace:() => '',
    document:{querySelector:() => null, querySelectorAll:() => []}});
  for (const name of ['familyAuthor','familyPhotoUrl','familyPersonPortrait','familyPersonCard','familyPersonDetail','familyWorkspace','selectFamilyPerson','closeFamilyPerson','familyChartData','applyPersistedFamilyContext']) {
    vm.runInContext(extract(name), context);
  }
  return context;
}

test('tree cards identify only the author and replace redundant lists', () => {
  const context = setup();
  const markup = context.familyWorkspace();
  assert.doesNotMatch(markup, /people-list|person-row|relationship-list|relationship-row/);
  assert.equal((markup.match(/class="family-author-badge"/g) || []).length, 1);
  assert.match(context.familyPersonCard(context.state.people[1]), /is-author|Me · Author/);
  assert.doesNotMatch(context.familyPersonCard(context.state.people[0]), /is-author|Me · Author/);
  assert.match(markup, /aria-controls="family-person-detail"/);
});

test('author identification supports exact aliases and refuses ambiguous identities', () => {
  let context = setup({people:[{id:'author', name:'陈文舟', aliases:['Avery']}, {id:'mum', name:'Mei'}]});
  assert.equal(context.familyAuthor().id, 'author');
  context = setup({people:[{id:'one',name:'Avery'}, {id:'two',name:'Avery'}]});
  assert.equal(context.familyAuthor(), null);
  context = setup({people:[{id:'mum',name:'Avery’s mother'}, {id:'uncle',name:'Avery Chen'}]});
  assert.equal(context.familyAuthor(), null);
});

test('selecting a person shows only their saved introduction and uncertain facts', () => {
  const context = setup();
  context.selectFamilyPerson('mum');
  assert.match(context.familyPersonDetail(), /She grew roses\.|around 1940/);
  assert.doesNotMatch(context.familyPersonDetail(), /Me · Author/);
  context.selectFamilyPerson('me');
  assert.match(context.familyPersonDetail(), /Me · Author|has not been recorded yet/);
  assert.doesNotMatch(context.familyPersonDetail(), /She grew roses/);
  context.selectFamilyPerson('missing');
  assert.equal(context.state.selectedFamilyPerson.id, 'me');
  context.state.project.id = 'another-project';
  assert.doesNotMatch(context.familyPersonDetail(), /family-person-name/);
  context.closeFamilyPerson();
  assert.equal(context.state.selectedFamilyPerson, null);
});

test('person names, titles and introductions are escaped in cards and details', () => {
  const context = setup({people:[{id:'unsafe', name:'<img src=x>', family_title:'<b>friend</b>', introduction:'<script>bad()</script>', aliases:['<svg>']} ]});
  context.selectFamilyPerson('unsafe');
  const markup = context.familyPersonCard(context.state.people[0]) + context.familyPersonDetail();
  assert.doesNotMatch(markup, /<img|<script|<svg|<b>/);
  assert.match(markup, /&lt;script&gt;bad\(\)&lt;\/script&gt;/);
});

test('tree adapter preserves saved parent, child and spouse connections', () => {
  const context = setup({relationships:[{from_person_id:'mum', to_person_id:'me', relationship_type:'parent'}]});
  const data = context.familyChartData();
  assert.deepEqual(Array.from(data.find(person => person.id === 'me').rels.parents), ['mum']);
  assert.deepEqual(Array.from(data.find(person => person.id === 'mum').rels.children), ['me']);
});

test('portraits use safe image URLs and editable saved photos retain controls', () => {
  const context = setup({familyFeaturesEnabled:true, supabase:{accessToken:'fixture'},
    people:[{id:'me',name:'Avery',photo_path:'private/portrait.jpg',photo_url:'https://photos.test/portrait.jpg?token=private'}]});
  context.selectFamilyPerson('me');
  assert.match(context.familyPersonCard(context.state.people[0]), /data-family-portrait/);
  assert.match(context.familyPersonDetail(), /Replace photo|Remove photo/);
  for (const photo_url of ['javascript:alert(1)', 'data:image/svg+xml,bad', '<img src=x>']) {
    assert.doesNotMatch(context.familyPersonPortrait({name:'Avery',photo_url}), /<img/);
  }
});

test('conversation updates retain a signed portrait only for the same saved asset', () => {
  const context = setup({familyContext:{project_id:'project'},
    people:[{id:'me',name:'Avery',photo_path:'saved.jpg',photo_url:'https://photos.test/signed'}]});
  context.applyPersistedFamilyContext({project_id:'project',people:[{id:'me',name:'Avery',photo_path:'saved.jpg',introduction:'A new memory.'}]});
  assert.equal(context.state.people[0].photo_url, 'https://photos.test/signed');
  assert.equal(context.state.people[0].introduction, 'A new memory.');
  context.applyPersistedFamilyContext({project_id:'project',people:[{id:'me',name:'Avery',photo_path:'replacement.jpg'}]});
  assert.equal(context.state.people[0].photo_url, undefined);
});

test('late conversation and photo responses cannot overwrite newer saved family context', async () => {
  const people = [{id:'me',name:'Avery',introduction:'A newer memory.',photo_path:'saved.jpg',photo_url:'https://photos.test/saved'}];
  const context = setup({familyFeaturesEnabled:true, supabase:{accessToken:'fixture',user:{id:'owner'}},
    familyContext:{project_id:'project',revision:5,people},people});
  context.applyPersistedFamilyContext({project_id:'project',revision:4,people:[{id:'me',name:'Avery'}]});
  assert.equal(context.state.people[0].photo_path, 'saved.jpg');
  assert.equal(context.state.familyContext.revision, 5);
  context.selectFamilyPerson('me');
  context.updateFamilyPersonViews = () => {};
  context.supabaseApi = async () => ({revision:4,person:{id:'me',name:'Avery',introduction:'An older memory.',photo_path:'uploaded.jpg'}});
  let refreshed = false;
  context.refreshFamilyContext = async () => { refreshed = true; };
  vm.runInContext('async ' + extract('saveFamilyPersonPhoto'), context);
  await context.saveFamilyPersonPhoto({type:'image/png',size:200});
  assert.equal(refreshed, true);
  assert.equal(context.state.people[0].introduction, 'A newer memory.');
  assert.equal(context.state.familyContext.revision, 5);
  assert.equal(context.state.familyPhotoTask.busy, false);
});
