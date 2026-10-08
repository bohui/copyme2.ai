import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {responsePhotoCards} from '../../apps/web/client/memoir/interview-photo-turns.mjs';

const fixture=fs.readFileSync(new URL('../test_interview_photo_turns_browser.py',import.meta.url),'utf8');
const source=fs.readFileSync(new URL('../../apps/web/client/memoir/client.js',import.meta.url),'utf8');
const openingMessages=['en-AU','zh-CN'].map(locale=>JSON.parse(fs.readFileSync(new URL(`../../apps/web/messages/${locale}.json`,import.meta.url),'utf8')).Memoir.conversation.opening);
const scripts=Object.fromEntries([...fixture.matchAll(/((?:PROJECT|CHAT)_STORAGE_INIT) = """([\s\S]*?)"""/g)].map(match=>[match[1],match[2].replace('__PRODUCT_OPENING__',JSON.stringify(openingMessages[0]))]));
const registrations=[...fixture.matchAll(/\b(context|page)\.add_init_script\(((?:PROJECT|CHAT)_STORAGE_INIT)\b/g)].map(match=>({scope:match[1],script:scripts[match[2]]}));
const key='memory-spark-chat-history:owner:photos';
const storage=()=>{const values=new Map();return {getItem:key=>values.get(key)||null,setItem:(key,value)=>values.set(key,String(value)),removeItem:key=>values.delete(key)}};
function bootstrap(tab,original){for(const {scope,script} of registrations)if(scope==='context'||original)vm.runInNewContext(script,tab)}


test('the original photo test page seeds its opening without overwriting saved history on reload',()=>{
 const tab={localStorage:storage(),sessionStorage:storage()};bootstrap(tab,true);
 assert.equal(JSON.parse(tab.sessionStorage.getItem(key)).length,1);
 const saved=JSON.stringify([{role:'assistant',text:'Saved chosen question?',clientTurnId:'accepted'}]);
 tab.sessionStorage.setItem(key,saved);bootstrap(tab,true);
 assert.equal(tab.sessionStorage.getItem(key),saved);
});

test('photo fixture bootstrap never injects original-page chat into a fresh tab',()=>{
 const shared=storage(),original={localStorage:shared,sessionStorage:storage()};bootstrap(original,true);
 const fresh={localStorage:shared,sessionStorage:storage()};bootstrap(fresh,false);
 assert.equal(fresh.sessionStorage.getItem(key),null);
});

test('durable cached history also prevents a synthetic opening from being reseeded',()=>{
 const durable=storage(),saved=JSON.stringify([{role:'assistant',text:'Existing response?'}]);durable.setItem(key,saved);
 const tab={localStorage:durable,sessionStorage:storage()};bootstrap(tab,true);
 assert.equal(tab.sessionStorage.getItem(key),null);assert.equal(durable.getItem(key),saved);
});

test('the actual fixture opening stays ahead of the restored canonical reply and photo card',async()=>{
 const tab={localStorage:storage(),sessionStorage:storage()};bootstrap(tab,true);
 const initial=JSON.parse(tab.sessionStorage.getItem(key));
 const card={photo_id:'upload:11111111-1111-4111-8111-111111111111',kind:'private_upload',title:'Your private photo'};
 const state={supabase:{user:{id:'owner',is_anonymous:true}},project:{id:'photos'},chat:initial,photoTurns:{cards:responsePhotoCards}};
 const context=vm.createContext({state,openingMessages,conversationMessage:()=>openingMessages[0],cleanAssistantText:text=>text,persistChatHistory(){},storyApi:async()=>({project_id:'photos',policy_epoch:'1',next_cursor:null,items:[{server_turn_id:'server',client_turn_id:'accepted',narrator_text:'I remember this garden.',reply:'What did you grow there?',response_photos:[card]}]})});
 for(const name of ['captureProjectScope','isCurrentProjectScope','originalConversationText','normalizeHistoryOpening','hydrateAccountHistory'])vm.runInContext(source.match(new RegExp(`(?:async )?function ${name}\\([^]*?\\n\\}`))[0],context);
 await context.hydrateAccountHistory();
 assert.equal(state.chat[0].text,openingMessages[0]);
 assert.equal(state.chat.filter(message=>message.role==='assistant').at(-1).text,'What did you grow there?');
 assert.equal(state.chat.filter(message=>message.responsePhotos?.length).length,1);
 assert.equal(state.chat.length,3);
});
