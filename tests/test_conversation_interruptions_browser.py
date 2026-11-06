"""Production composer, input queue and streaming client with a controlled server."""
import json
from pathlib import Path
import re

import pytest
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
CLIENT = (ROOT / 'apps/web/client/memoir/client.js').read_text()
SEND_WAIT = json.loads((ROOT / 'apps/web/messages/zh-CN.json').read_text())['Memoir']['story']['sendWait']


@pytest.fixture
def chat():
    def function(name):
        return re.search(r'(?:async )?function ' + name + r'\([\s\S]*?\n\}', CLIENT)[0]
    modules = '\n'.join((ROOT / 'apps/web/client/memoir' / name).read_text().replace('export function ', 'function ')
        for name in ['conversation-inputs.mjs', 'interview-photo-turns.mjs'])
    history = (ROOT / 'apps/web/client/memoir/conversation-history.mjs').read_text()
    modules += '\n' + history[history.index('function createConversationHistory'):]
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            script_errors = []
            page.on('pageerror', lambda error: script_errors.append(str(error)))
            page.route('https://memoir.test/', lambda route:route.fulfill(body='<div id="app"></div>', content_type='text/html'))
            page.goto('https://memoir.test/')
            page.add_script_tag(content=f'const sendWait = {json.dumps(SEND_WAIT)};\n' + modules + '''
                const state={project:{id:'project',profile:{}},supabase:{accessToken:'fixture',user:{id:'owner'}},
                  chat:[],attachments:[],audioRecordings:[],audioTranscript:'',audioTranscriptKind:'narrator_chat',
                  dictationStatus:'off',navigationGeneration:0};
                const $=selector=>document.querySelector(selector);
                const translate=key=>key==='Memoir.story.sendWait' ? sendWait : key;
                const translateWith=String, escapeHtml=text=>String(text).replaceAll('&','&amp;').replaceAll('<','&lt;');
                const noop=()=>{}, empty=()=>'', ATTACHMENT_TYPES={};
                const workspaceMemoryFocusMarkup=empty, storyGameButton=empty, selectedPhotoCue=empty;
                const composerAttachments=empty, composerIcon=empty, conversationLanguage=()=> 'en-AU';
                const profile=()=>({conversation_language:{initialized:true}}), simulatedLoopTrace=()=>[];
                const ensureMemorySession=async()=>null, settleUiLocale=async()=>true;
                const currentUiPreference=()=>({locale:'en-AU'}), conversationMessage=key=>key;
                const workspaceTurnFocus=()=>null, markWorkspaceFocusStarted=noop;
                const refreshStageReadiness=noop, refreshPrivateDraft=noop, refreshFamilyContext=noop;
                const applyCommittedConversationLocale=noop, applyCurrentActiveLocation=noop, freeRecallFinished=()=>false;
                const memoirApiPath=value=>value, readCookie=empty, cleanAssistantText=String, historicalContext=value=>value;
                const {persistChatHistory,restoreChatHistory,nextAssistantMessageId}=createConversationHistory({state,cleanAssistantText});
                let workspaceUpdateQueue=Promise.resolve();
                const conversationScroll={follow:noop}, ASSISTANT_STREAM_CHUNK_SIZE=3, ASSISTANT_STREAM_DELAY_MS=0;
                const updateStreamingAssistantMessage=()=>render();
                const errors=[];const toast=error=>errors.push(error);
                function render(){
                  const draft=$('#chat-input')?.value ?? state.audioTranscript;
                  $('#app').innerHTML=state.chat.map(message=>`<p class="${message.role}">${escapeHtml(message.text)}</p>`).join('')+chatComposer();
                  $('#chat-input').value=draft;
                  $('#chat-form').onsubmit=event=>{event.preventDefault();void sendChatMessage();};
                  $('#chat-input').oninput=event=>{state.audioTranscript=event.target.value;};
                  $('#chat-input').onkeydown=event=>{if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();void sendChatMessage();}};
                  const retry=$('[data-action="retry-interview-turn"]');
                  if(retry) retry.onclick=()=>void retryInterviewTurn();
                  persistChatHistory();
                }
                const requests=[];
                window.fetch=async(path,options)=>{
                  const input=JSON.parse(options.body), request={input,aborted:false};requests.push(request);
                  const stream=new ReadableStream({start(controller){
                    request.emit=event=>controller.enqueue(new TextEncoder().encode(JSON.stringify(event)+'\\n'));
                    request.accept=()=>request.emit({type:'source_accepted',data:{project_id:'project',client_turn_id:input.client_turn_id}});
                    request.token=text=>request.emit({type:'text_delta',text});
                    request.finish=reply=>{const data={project_id:'project',client_turn_id:input.client_turn_id,reply,conversation_saved:true};
                      request.emit({type:'conversation_saved',data});request.emit({type:'result',data});controller.close();};
                    request.fail=()=>{request.emit({type:'error',message:'Controlled reply error'});controller.close();};
                    options.signal.addEventListener('abort',()=>{request.aborted=true;controller.error(new DOMException('Interrupted','AbortError'));},{once:true});
                  }});
                  return new Response(stream,{headers:{'Content-Type':'application/x-ndjson'}});
                };
            ''' + '\n'.join(function(name) for name in ['captureProjectScope', 'isCurrentProjectScope',
                'chatInputLimitReached', 'chatComposer', 'sendChatMessage', 'processChatMessage', 'retryInterviewTurn',
                'agentTurn', 'streamAgentTurn', 'waitForAssistantStream', 'streamAssistantMessage']) + '''
                state.photoTurns=createInterviewPhotoState({state,scope:captureProjectScope,render,api:async()=>({})});
                state.conversationInputs=createConversationInputs({scope:captureProjectScope,current:isCurrentProjectScope,
                  run:processChatMessage,busy:loading=>{state.loading=loading;render();}});
                render();
            ''')
            assert not script_errors, script_errors
            yield page
        finally:
            browser.close()


@pytest.mark.parametrize('before_acceptance', [True, False])
def test_send_interrupts_mira_and_keeps_three_separate_inputs(chat, before_acceptance):
    page = chat
    originals = ['We moved in 1985.', 'Actually, it was 1986.', 'My sister came with us.']
    page.locator('#chat-input').fill(originals[0])
    page.locator('.send-button').click()
    page.wait_for_function('requests.length===1')
    expect(page.locator('.send-button')).to_be_enabled()
    if not before_acceptance:
        page.evaluate("requests[0].accept();requests[0].token('An outdated partial reply.');")
        expect(page.locator('.assistant')).to_have_text('An outdated partial reply.')
    page.locator('#chat-input').fill(originals[1])
    page.locator('#chat-input').press('Enter')
    assert page.locator('#chat-input').input_value() == ''
    assert page.locator('.user').all_text_contents() == originals[:2]
    page.locator('#chat-input').fill(originals[2])
    page.locator('.send-button').click()
    assert page.locator('.user').all_text_contents() == originals
    if before_acceptance:
        assert page.evaluate('requests.length') == 1
        assert not page.evaluate('requests[0].aborted')
        page.evaluate('requests[0].accept()')
    page.wait_for_function('requests.length>=2')
    assert page.evaluate('requests[0].aborted')
    page.evaluate('requests[1].accept()')
    page.wait_for_function('requests.length===3')
    assert page.evaluate('requests[1].aborted')
    page.evaluate("requests[2].accept();requests[2].finish('Your sister moved with you in 1986.');")
    page.wait_for_function('!state.loading')
    expect(page.locator('.user')).to_have_text(originals)
    expect(page.locator('.assistant')).to_have_text('Your sister moved with you in 1986.')
    assert page.evaluate('new Set(requests.map(request=>request.input.client_turn_id)).size') == 3
    assert page.evaluate('errors') == []
    expect(page.locator('.send-button')).to_be_enabled()


@pytest.mark.parametrize('failure', [None, 'before_acceptance', 'after_acceptance'])
def test_send_waits_for_mira_after_eight_inputs(chat, failure):
    page = chat
    box = page.locator('#chat-input')
    send = page.locator('.send-button')
    note = page.get_by_role('status')
    originals = [f'Memory {number}' for number in range(1, 9)]
    for original in originals:
        expect(send).to_be_enabled()
        box.fill(original)
        send.click()
    expect(send).to_be_disabled()
    expect(note).to_be_visible()
    expect(note).to_have_text('您说的太快了，请稍等')

    box.fill('One more memory')
    box.press('Enter')
    page.locator('#chat-form').evaluate('form => form.requestSubmit()')
    expect(box).to_have_value('One more memory')
    expect(page.locator('.user')).to_have_text(originals)

    for index in range(7):
        page.wait_for_function('count => requests.length === count', arg=index + 1)
        page.evaluate('index => requests[index].accept()', index)
    page.wait_for_function('requests.length === 8')
    if failure != 'before_acceptance':
        page.evaluate("requests[7].accept(); requests[7].token('A partial reply.');")
        expect(page.locator('.assistant')).to_have_text('A partial reply.')
        expect(send).to_be_disabled()
        expect(note).to_have_text('您说的太快了，请稍等')

    if failure:
        page.evaluate('requests[7].fail()')
        page.wait_for_function('!state.loading')
        if failure == 'before_acceptance':
            page.evaluate("state.chat = restoreChatHistory('project'); render();")
        expect(send).to_be_disabled()
        page.locator('.retry-interview-turn').click()
        page.wait_for_function('requests.length === 9')
        assert page.evaluate('requests[8].input.client_turn_id === requests[7].input.client_turn_id')
        page.evaluate('requests[8].accept()')

    page.evaluate("requests.at(-1).finish('I heard all eight memories.');")
    page.wait_for_function('!state.loading')
    expect(page.locator('.assistant')).to_have_text('I heard all eight memories.')
    expect(send).to_be_enabled()
    expect(note).to_have_count(0)
    expect(box).to_have_value('One more memory')
    send.click()
    expect(page.locator('.user')).to_have_text([*originals, 'One more memory'])
