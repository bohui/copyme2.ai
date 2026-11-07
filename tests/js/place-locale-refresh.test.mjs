import { readMemoirClientSource } from './helpers/memoir-source.mjs';
import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';

test('locale changes refresh place grouping only on the interview', () => {
  const source = readMemoirClientSource();
  const journey = {place: 'Chengde'};
  let listener, path = '/';
  const calls = [];
  const context = vm.createContext({
    state: {placeJourney: journey},
    currentPath: () => path,
    MEMOIR_ROUTES: { home: '/memoir' },
    window: {addEventListener: (name, handler) => {
      if (name === 'copyme2:ui-locale-change') listener = handler;
    }},
    closeProfileMenu() {},
    refreshOpeningMessageLocale: () => false,
    render() {},
    placeWorkspaceSelection: () => journey,
    resolvePlaceMap: place => calls.push(place),
  });

  vm.runInContext(source.match(/window.addEventListener\("copyme2:ui-locale-change", \(\) => \{[^]*?\n\}\);/)[0], context);
  listener();
  assert.deepEqual(calls, []);
  path = '/memoir/interview/project';
  listener();
  assert.deepEqual(calls, [journey]);
});
