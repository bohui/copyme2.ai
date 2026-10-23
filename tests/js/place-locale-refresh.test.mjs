import { readMemoirClientSource } from './helpers/memoir-source.mjs';
import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';

test('locale repaint refreshes localized place grouping even when the map is reused', () => {
  const source = readMemoirClientSource();
  const journey = {place: 'Chengde'};
  let listener;
  const calls = [];
  const context = vm.createContext({
    state: {placeJourney: journey},
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
  assert.deepEqual(calls, [journey]);
});
