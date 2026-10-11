import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {signOutBrowserSession} from '../../apps/web/auth/browser.mjs';
import {createPreferenceSession} from '../../apps/web/i18n/session.mjs';
const source=fs.readFileSync(new URL('../../apps/web/client/memoir/client.js',import.meta.url),'utf8');
test('SIGNED_OUT callback cannot reload before blocked-storage logout recovery',async()=>{
 const events=[],state={supabase:{supabase_url:'https://logout.supabase.co',user:{id:'a'}}};
 const session=createPreferenceSession();
 const context=vm.createContext({state,uiPreferenceSession:session,signOutBrowserSession,
  closeProfileMenu(){},clearDerivedUiPreference(){},persistChatHistory(){},invalidateProjectNavigation(){},refreshProfileMenu(){},
  authReminder:{tick(){}},location:{reload(){events.push('reload');}},
  translate:key=>key,toast:value=>events.push(value),navigateTo(){},renderLanding(){},boot:async()=>events.push('boot'),
  MEMOIR_ROUTES:{home:'/'},PLACE_JOURNEY_PROJECT_STORAGE_KEY:'fixture',
  localStorage:{setItem(){throw new Error('QuotaExceededError');},removeItem(){throw new Error('SecurityError');}}});
 for(const name of ['syncSupabaseSession','signOut'])vm.runInContext(source.match(new RegExp(`(?:async )?function ${name}\\([^]*?\\n\\}`))[0],context);
 state.supabase.client={auth:{signOut:async()=>{events.push('revoked');context.syncSupabaseSession(null);return {};}}};
 await context.signOut();
 assert.deepEqual(events,['revoked','Errors.logoutStorageWarning']);assert.equal(state.supabase,null);assert.equal(state.explicitSignOutInProgress,false);
});
