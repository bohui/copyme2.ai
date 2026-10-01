import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(new URL('../../apps/web/client/memoir/client.js', import.meta.url), 'utf8');

test('successful OAuth updates the visible guest menu without another chat turn', () => {
  const state = { supabase: { user: { id: 'guest', is_anonymous: true } } };
  let menu = '';
  const context = vm.createContext({
    state, authReminder: { tick() {} }, UI_LOCALES: new Set(),
    refreshProfileMenu() { menu = context.profileMenu(); },
    profile: () => ({}), escapeHtml: String, translate: key => key,
  });
  for (const name of ['profileDetails', 'profileMenu', 'syncSupabaseSession']) {
    vm.runInContext(source.match(new RegExp(`function ${name}\\([^]*?\\n\\}`))[0], context);
  }
  menu = context.profileMenu();
  assert.match(menu, /data-profile-action="login"/);
  context.syncSupabaseSession({ access_token: 'test-token', user: {
    id: 'existing', email: 'owner@example.com', is_anonymous: false,
  } });
  assert.doesNotMatch(menu, /data-profile-action="login"/);
  assert.match(menu, /data-profile-action="logout"/);
  assert.match(menu, /data-profile-action="attached-history"/);
  assert.match(menu, /owner@example.com/);
});
