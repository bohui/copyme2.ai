import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
const source=fs.readFileSync(new URL('../../apps/web/client/memoir/client.js',import.meta.url),'utf8');
function extract(name){
  const start=source.search(new RegExp(`^(?:async )?function ${name}\\(`,'m'));
  assert.ok(start>=0);
  const tail=source.slice(start+1),next=tail.search(/^(?:async )?function /m);
  return ['captureProjectScope', 'isCurrentProjectScope'].map(helper => source.match(new RegExp(`function ${helper}\\([^]*?\\n\}`))[0]).join('\n') + '\n' + source.slice(start,next<0?undefined:start+1+next);
}
const record=(locale,revision=1,kind='first_reply')=>({version:1,initialized:true,locale,revision,source:kind});
function harness(profile){
  const state={project:{id:'fixture',profile},supabase:{user:{id:'owner'},accessToken:'fixture-only'}};
  const applied=[];
  const context=vm.createContext({state,applyProfileUiLocale:async language=>applied.push(language)});
  vm.runInContext(['profile','conversationLanguage','mergeProfileUpdates','applyCommittedConversationLocale','preserveConversationLocale'].map(extract).join('\n'),context);
  return {context,state,applied};
}
test('saved first-reply locale blocks later model and stale background changes',()=>{
  const {context}=harness({preferred_language:'zh-CN',conversation_language:record('zh-CN',2,'explicit')});
  assert.equal(context.mergeProfileUpdates({preferred_language:'en-AU'}),null);
  assert.equal(context.mergeProfileUpdates({preferred_language:'en-AU',conversation_language:record('en-AU')}),null);
  assert.equal(context.conversationLanguage(),'zh-CN');
});
test('late hydration and project conflict reload retain a newer explicit decision',()=>{
  const {context,state}=harness({preferred_language:'en-AU',conversation_language:record('en-AU',2,'explicit')});
  const result=context.preserveConversationLocale({name:'Fixture',preferred_language:'zh-CN',conversation_language:record('zh-CN')},state.project.profile);
  assert.equal(result.preferred_language,'en-AU');
  assert.equal(result.name,'Fixture');
  assert.equal(result.conversation_language.revision,2);
  const legacy=context.preserveConversationLocale({preferred_language:'zh-CN'},state.project.profile);
  assert.equal(legacy.preferred_language,'en-AU');
});
test('automatic reset restores the recorded first language instead of keeping the manual override',()=>{
  const {context}=harness({preferred_language:'en-AU',conversation_language:record('en-AU',2,'explicit')});
  const next=context.mergeProfileUpdates({conversation_language:record('zh-CN',3),preferred_language:null});
  assert.equal(next.preferred_language,'zh-CN');
});
for (const race of ['manual choice', 'account switch']) {
  test(`delayed private hydration cannot undo ${race}`, async()=>{
    const {context,state}=harness({preferred_language:'zh-CN',conversation_language:record('zh-CN')});
    let release, started;
    const pending=new Promise(resolve=>{release=resolve;});
    const requested=new Promise(resolve=>{started=resolve;});
    context.api=async path=>path.endsWith('/journey')?{active_session:null}:{id:'fixture',profile:{}};
    context.storyApi=async()=>{started();return pending;};
    context.mergePlaces=places=>places;
    context.refreshStageReadiness=()=>{};
    context.refreshPrivateDraft=()=>{};
    vm.runInContext(extract('refreshProject'),context);
    const refresh=context.refreshProject();
    await requested;
    await context.applyCommittedConversationLocale({preferred_language:'en-AU',conversation_language:record('en-AU',2,'explicit')});
    if(race==='account switch') state.supabase.user={id:'other-owner'};
    release({preferred_language:'zh-CN',conversation_language:record('zh-CN')});
    await refresh;
    assert.equal(state.project.profile.preferred_language,'en-AU');
    assert.equal(state.project.profile.conversation_language.revision,2);
  });
}
test('committed first-reply locale updates state before optional workspace, explicit override wins',async()=>{
  const {context,state,applied}=harness({});
  await context.applyCommittedConversationLocale({preferred_language:'zh-CN',conversation_language:record('zh-CN')});
  assert.equal(state.project.profile.preferred_language,'zh-CN');
  await context.applyCommittedConversationLocale({preferred_language:'en-AU',conversation_language:record('en-AU',2,'explicit')});
  await context.applyCommittedConversationLocale({preferred_language:'zh-CN',conversation_language:record('zh-CN')});
  assert.equal(state.project.profile.preferred_language,'en-AU');
  assert.deepEqual(applied,['zh-CN','en-AU','en-AU']);
});
