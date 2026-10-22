"""Real chat renderer and revision animation in Chromium; no API/model calls."""
from pathlib import Path
import re

import pytest
from playwright.sync_api import expect, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
CLIENT = (ROOT / 'apps/web/client/memoir/client.js').read_text()
REVISION = (ROOT / 'apps/web/client/memoir/reply-revision.mjs').read_text()


def function(name):
    return re.search(r'(?:async )?function ' + name + r'\([\s\S]*?\n\}', CLIENT.replace('\r', ''))[0]


@pytest.mark.parametrize('reduced', [False, True])
@pytest.mark.parametrize('draft,final', [
    ('I remember the family detail you shared. 👩‍👩‍👧‍👦', 'We can change the subject.'),
    ('你提到了之前的家庭经历，我们可以继续谈谈。👩‍👩‍👧‍👦', '好的，我们换个话题。'),
])
def test_streamed_draft_is_erased_before_replacement(draft, final, reduced):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(reduced_motion='reduce' if reduced else 'no-preference')
            page.set_content('<main></main>')
            page.add_script_tag(content='''
                const state = {voiceMode:false}, CHATBOT_NAME = 'Mira';
                const cleanAssistantText = String, translate = String;
                const escapeHtml = text => {const node=document.createElement('span');node.textContent=text;return node.innerHTML;};
                const formatText = escapeHtml, renderAgentTrace = () => '';
                const $ = () => null, conversationScroll = {following:() => false};
                window.message = {id:'draft',role:'assistant',text:'',streaming:true};
                window.frames = [];
                function render() {document.querySelector('main').innerHTML=renderMessage(message);}
            ''' + function('renderMessage') + '\n' + function('updateStreamingAssistantMessage')
                + '\n' + REVISION.replace('export function ', 'function ', 1) + '''
                window.revision = createReplyRevision({message,current:() => true,
                    render:value => {updateStreamingAssistantMessage(value);frames.push(value.text);}});
                revision.begin(0);render();
            ''')
            page.evaluate('text => revision.append(text,0)', draft)
            text = page.locator('.message-text')
            expect(text).to_have_text(draft)
            expect(text).to_have_attribute('aria-live', 'off')
            expect(page.locator('.listen-button')).to_have_count(0)
            page.evaluate('text => {revision.begin(1);revision.append("LATE OLD TOKENS",0);revision.append(text,1);}', final)
            expect(text).to_have_text(final)
            frames = page.evaluate('frames')
            assert '' in frames
            assert all('LATE OLD TOKENS' not in frame and '\ufffd' not in frame for frame in frames)
            if not reduced:
                assert any(frame and frame != draft and draft.startswith(frame) for frame in frames)
                assert any(frame and frame != final and final.startswith(frame) for frame in frames)
            page.evaluate('async text => {await revision.finish(text);message.streaming=false;render();revision.dispose();}', final)
            expect(text).to_have_attribute('aria-live', 'polite')
            expect(page.locator('.listen-button')).to_have_count(1)
        finally:
            browser.close()


@pytest.mark.parametrize('draft,final', [
    ('Did your father help you settle in Sydney?', 'What stands out about your first day in Sydney?'),
    ('父亲有没有帮助您在悉尼安顿下来？', '您初到悉尼时，什么最让您难忘？'),
])
def test_real_stream_parser_revises_only_the_current_bubble(draft,final):
    names=['captureProjectScope','isCurrentProjectScope','currentWorkspaceMemoryFocus','workspaceTurnFocus',
        'markWorkspaceFocusStarted','agentTurn','streamAgentTurn','streamAssistantMessage','renderMessage',
        'updateStreamingAssistantMessage']
    with sync_playwright() as playwright:
        browser=playwright.chromium.launch(headless=True)
        try:
            page=browser.new_page()
            page.set_content('<main></main>')
            page.add_script_tag(content='''
                const state={supabase:{accessToken:'synthetic',user:{id:'owner'}},project:{id:'project'},chat:[
                    {id:'old',role:'assistant',text:'XXXXX — earlier saved reply.',streaming:false}]};
                const CHATBOT_NAME='Mira', cleanAssistantText=String, translate=String;
                const escapeHtml=text=>{const node=document.createElement('span');node.textContent=text;return node.innerHTML;};
                const formatText=escapeHtml, renderAgentTrace=()=>'', conversationLanguage=()=> 'en-AU';
                const $=()=>null,conversationScroll={following:()=>false},simulatedLoopTrace=()=>[];
                const memoirApiPath=path=>path,readCookie=()=>'',toast=()=>{};
                const refreshPrivateDraft=async()=>{},refreshStageReadiness=async()=>{};
                let workspaceUpdateQueue=Promise.resolve(),messageId=0;
                const nextAssistantMessageId=()=>`current-${++messageId}`;
                function render(){document.querySelector('main').innerHTML=state.chat.map(renderMessage).join('');}
                window.fetch=async()=>new Response(new ReadableStream({start(controller){
                    const emit=event=>controller.enqueue(new TextEncoder().encode(JSON.stringify(event)+'\\n'));
                    window.draft=text=>{emit({type:'reply_revision',data:{revision:0}});emit({type:'text_delta',text,revision:0});};
                    window.restrict=text=>{
                        emit({type:'reply_revision',data:{revision:1}});
                        emit({type:'text_delta',text:'LATE CANCELLED TEXT',revision:0});
                        for(const char of text)emit({type:'text_delta',text:char,revision:1});
                        emit({type:'conversation_saved',data:{reply:text,conversation_saved:true}});
                        emit({type:'result',data:{reply:text,conversation_saved:true}});controller.close();
                    };
                }}),{headers:{'Content-Type':'application/x-ndjson'}});
            '''+'\n'.join(function(name) for name in names)+'\n'+REVISION.replace('export function ','function ',1)+'''
                render();
                window.turn=agentTurn('Please leave my father out.').then(async result=>{
                    await streamAssistantMessage(result.reply,{streamedMessage:result.streamedMessage});
                    window.finished=result;
                });
            ''')
            previous=page.locator('[data-message-id="old"]')
            old_markup=previous.inner_html()
            page.wait_for_function('typeof window.draft === "function"')
            page.evaluate('text=>draft(text)',draft)
            current=page.locator('[data-message-id="current-1"] .message-text')
            expect(current).to_have_text(draft)
            expect(previous).to_contain_text('XXXXX — earlier saved reply.')
            page.evaluate('text=>restrict(text)',final)
            page.wait_for_function('Boolean(window.finished)')
            expect(current).to_have_text(final)
            expect(page.locator('.assistant-message')).to_have_count(2)
            assert previous.inner_html()==old_markup
            assert 'LATE CANCELLED TEXT' not in page.locator('main').inner_text()
            assert page.evaluate('finished.streamedMessage.provisional') is False
        finally:
            browser.close()
