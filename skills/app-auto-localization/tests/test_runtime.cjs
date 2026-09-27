const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const {UI_LOCALES, IDLE, isUiLocale, matchSupportedLocale, resolveUiLocale,
  newAutoState, observeLanguage, flushPending, commitAutomaticSwitch, manualSwitchPlan,
  isBusy} = require(path.join(process.env.BUILD_DIR, 'locale-policy.js'));
const {detectDirectUiText} = require(path.join(process.env.BUILD_DIR, 'text-signal.js'));
const NOW = 1_000_000;
const context = (overrides = {}) => ({now: NOW, locked: false, inputDetectionEnabled: true,
  busy: {...IDLE}, ...overrides});
const event = (overrides = {}) => ({id: 'e1', languageTag: 'zh-Hans', quality: 'strong',
  origin: 'direct-ui-text', actor: 'current-viewer', final: true, mixed: false,
  evidenceUnits: 40, observedAt: NOW - 1000, revision: 0, ...overrides});
const first = () => observeLanguage(newAutoState('en-AU'), event(), context()).state;
const second = (ctx = context()) => observeLanguage(first(), event({id:'e2', observedAt: NOW}), ctx);

for (const [input, expected] of [
  ['en', 'en-AU'], ['en-US', 'en-AU'], ['en-GB', 'en-AU'], ['en-au', 'en-AU'],
  ['zh', 'zh-CN'], ['zh-CN', 'zh-CN'], ['zh-SG', 'zh-CN'], ['zh-Hans', 'zh-CN'],
  ['zh-Hans-HK', 'zh-CN'], ['zh-Hant', null], ['zh-TW', null], ['zh-HK', null],
  ['zh-MO', null], ['zh-Latn', null], ['ja-JP', null], ['fr-FR', null],
  ['ar', null], ['../zh-CN', null], ['zh_CN', null], ['*', null], ['', null], [null, null]
]) test(`locale match ${String(input)}`, () => assert.equal(matchSupportedLocale(input), expected));

test('only exact supported values can be persisted as explicit prefs', () => {
  assert.ok(isUiLocale('zh-CN')); assert.equal(isUiLocale('zh'), false);
  assert.deepEqual(UI_LOCALES, ['en-AU', 'zh-CN']);
});
test('device outranks account, detected and browser', () => {
  assert.deepEqual(resolveUiLocale({deviceLocale:'en-AU', accountLocale:'zh-CN',
    sessionLocale:'zh-CN', browserLanguages:['zh']}), {locale:'en-AU',source:'device',locked:true});
});
test('account outranks automatic session', () => assert.deepEqual(
  resolveUiLocale({accountLocale:'zh-CN',sessionLocale:'en-AU'}),
  {locale:'zh-CN',source:'account',locked:true}));
test('automatic session outranks browser without creating a lock', () => assert.deepEqual(
  resolveUiLocale({sessionLocale:'zh-CN',browserLanguages:['en-US']}),
  {locale:'zh-CN',source:'session',locked:false}));
test('first render uses browser', () => assert.equal(resolveUiLocale({browserLanguages:['zh-CN','en']}).locale,'zh-CN'));
test('unsupported first browser candidate does not discard later supported ones', () => assert.equal(
  resolveUiLocale({browserLanguages:['ja-JP','en-US','zh']}).locale,'en-AU'));
test('traditional does not silently map to simplified', () => assert.equal(
  resolveUiLocale({browserLanguages:['zh-Hant','en-GB']}).locale,'en-AU'));
test('unknown defaults to English', () => assert.deepEqual(resolveUiLocale({}),
  {locale:'en-AU',source:'default',locked:false}));
test('invalid cookie cannot select an import path', () => assert.equal(
  resolveUiLocale({deviceLocale:'../../secrets',browserLanguages:['zh']}).locale,'zh-CN'));
test('one signal does not flip UI', () => assert.equal(
  observeLanguage(newAutoState('en-AU'),event(),context()).kind,'observe'));
test('two signals propose a switch without falsely marking persistence success', () => {
  const result=second(); assert.equal(result.kind,'apply'); assert.equal(result.target,'zh-CN');
  assert.equal(result.state.locale,'en-AU'); assert.equal(result.state.autoApplied,false);
});
test('successful commit changes only UI state', () => {
  const result=second(); const state=commitAutomaticSwitch(result.state,'zh-CN',0);
  assert.equal(state.locale,'zh-CN'); assert.equal(state.autoApplied,true); assert.equal(state.revision,1);
  assert.equal(state.pending,null); assert.equal('conversationLocale' in state,false);
});
test('stale commit is rejected', () => assert.throws(() => commitAutomaticSwitch(second().state,'zh-CN',1)));
test('wrong target commit is rejected', () => assert.throws(() => commitAutomaticSwitch(second().state,'en-AU',0)));
test('one inferred switch per session', () => {
  const state=commitAutomaticSwitch(second().state,'zh-CN',0);
  const result=observeLanguage(state,event({languageTag:'en',evidenceUnits:100,revision:1}),context());
  assert.equal(result.reason,'session-switch-limit');
});
test('explicit preference wins even during detection', () => assert.equal(
  second(context({locked:true})).reason,'explicit-preference'));
test('input detection can be disabled independently of browser detection', () => assert.equal(
  second(context({inputDetectionEnabled:false})).reason,'input-detection-disabled'));
for (const origin of ['interview','transcript','import','external','generated'])
  test(`${origin} never changes UI`, () => assert.equal(
    observeLanguage(first(),event({id:'e2',origin}),context()).reason,'ineligible-origin'));
for (const actor of ['other','unknown'])
  test(`${actor} viewer cannot change UI`, () => assert.equal(
    observeLanguage(first(),event({id:'e2',actor}),context()).reason,'ineligible-origin'));
test('partial speech is ignored', () => assert.equal(
  observeLanguage(first(),event({id:'e2',final:false}),context()).reason,'ineligible-origin'));
test('duplicate delivery is not a second signal', () => assert.equal(
  observeLanguage(first(),event(),context()).reason,'invalid-or-duplicate-event'));
test('stale revision is ignored', () => assert.equal(
  observeLanguage(first(),event({id:'e2',revision:5}),context()).reason,'stale-revision'));
for (const observedAt of [NOW+1,NOW-301000,Number.NaN])
  test(`invalid timestamp ${observedAt}`, () => assert.equal(observeLanguage(
    first(),event({id:'e2',observedAt}),context()).reason,'stale-or-invalid-time'));
test('weak signal resets consecutive evidence', () => {
  const result=observeLanguage(first(),event({id:'e2',quality:'uncertain'}),context());
  assert.equal(result.state.count,0);
});
test('mixed language does not switch', () => assert.equal(observeLanguage(first(),
  event({id:'e2',mixed:true}),context()).kind,'ignore'));
test('too little text does not switch', () => assert.equal(observeLanguage(first(),
  event({id:'e2',evidenceUnits:3}),context()).kind,'ignore'));
test('unsupported language does not become English signal', () => assert.equal(observeLanguage(first(),
  event({id:'e2',languageTag:'fr'}),context()).kind,'ignore'));
test('current language clears pending alternative', () => assert.equal(observeLanguage(first(),
  event({id:'e2',languageTag:'en',evidenceUnits:100}),context()).state.count,0));
for (const busyKey of Object.keys(IDLE))
  test(`${busyKey} defers automatic AND manual switching`, () => {
    const busy={...IDLE,[busyKey]:true}; const result=second(context({busy}));
    assert.equal(result.kind,'defer'); assert.equal(result.state.locale,'en-AU');
    assert.equal(manualSwitchPlan('zh-CN',busy).kind,'defer');
  });
test('unknown busy state fails closed', () => assert.equal(isBusy({}),true));
test('safe boundary releases pending proposal', () => {
  const pending=second(context({busy:{...IDLE,recording:true}})).state;
  assert.equal(flushPending(pending,context()).kind,'apply');
});
test('pending expires', () => assert.equal(flushPending(second().state,
  context({now:NOW+301000})).reason,'pending-expired'));
test('manual lock cancels pending', () => assert.equal(flushPending(second().state,
  context({locked:true})).state.pending,null));
test('manual target validated', () => assert.equal(manualSwitchPlan('fr',IDLE).kind,'invalid'));
test('manual change is immediate when safe', () => assert.equal(manualSwitchPlan('zh-CN',IDLE).kind,'apply'));
test('initial state rejects invalid revision', () => assert.throws(() => newAutoState('en-AU',-1)));

// Detector adapter tests use stub rankers: they test gating, NOT franc accuracy.
const english='I would like to find out how I can change the settings on this application and save my account preferences for the next visit.';
const chinese='我想了解这个应用应该怎么使用，请告诉我如何保存这些内容以及下次打开时应该在哪里找到我的记录。';
const rankEnglish=()=>[['eng',1],['sco',0.6],['fra',0.2]];
const rankChinese=()=>[['cmn',1]];
test('long English candidate passes adapter gates',()=>assert.equal(detectDirectUiText(english,rankEnglish).languageTag,'en'));
test('simplified candidate passes adapter gates',()=>assert.equal(detectDirectUiText(chinese,rankChinese).languageTag,'zh-Hans'));
test('short text abstains',()=>assert.equal(detectDirectUiText('OK',rankEnglish).quality,'uncertain'));
test('foreign language winner is not forced to English',()=>assert.equal(detectDirectUiText(english,()=>[['fra',1],['eng',0.3]]).languageTag,null));
test('ambiguous English ranking abstains',()=>assert.equal(detectDirectUiText(english,()=>[['eng',1],['sco',0.99]]).languageTag,null));
test('detector exception abstains',()=>assert.equal(detectDirectUiText(english,()=>{throw new Error('unavailable')}).languageTag,null));
test('code and URL do not trigger inference',()=>assert.equal(detectDirectUiText(`${english} https://example.test`,rankEnglish).languageTag,null));
test('quote does not trigger inference',()=>assert.equal(detectDirectUiText(`> ${english}`,rankEnglish).languageTag,null));
test('traditional script markers abstain',()=>assert.equal(detectDirectUiText('我想了解這個應用應該怎麼使用，請告訴我如何保存這些內容以及下次打開時應該在哪裡找到我的記錄。',rankChinese).languageTag,null));
test('mixed scripts abstain',()=>assert.equal(detectDirectUiText(`${chinese} ${english}`,rankChinese).mixed,true));
test('overlarge input abstains without ranker execution',()=>assert.equal(detectDirectUiText('a'.repeat(5000),()=>{throw Error('must not execute')}).reason,'invalid-size'));
