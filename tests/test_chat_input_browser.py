"""Chat input composition through the production renderer; no API/model calls."""
from pathlib import Path
import re

import pytest
from playwright.sync_api import expect, sync_playwright


CLIENT = (Path(__file__).resolve().parents[1] / 'apps/web/client/memoir/client.js').read_text()


def function(name):
    return re.search(r'(?:async )?function ' + name + r'\([\s\S]*?\n\}', CLIENT)[0]


@pytest.fixture
def chat_page():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.set_content('<div id="app"></div>')
            page.add_script_tag(content='''
                const state = {project:{id:'project'}, chat:[], chapters:[], audioTranscript:'',
                    dictationStatus:'off', workspaceRevision:0};
                const $ = selector => document.querySelector(selector);
                const escapeHtml = text => {const node=document.createElement('span');node.textContent=text;return node.innerHTML;};
                const translate = String, translateWith = String, MEMOIR_ROUTES = {home:'/memoir'};
                const ATTACHMENT_TYPES = {};
                const currentPath = () => '/memoir/interview/project';
                const composingWorkspaceActive = () => true, freeRecallFinished = () => false;
                const workspaceIsVisible = () => true, workspaceHasContent = () => true;
                const isFreshAnonymousSession = () => true, activeWorkspaceTab = () => 'memoir';
                const workspaceDetail = () => '<aside id="workspace-detail">Revision '+state.workspaceRevision+'</aside>';
                const noop = () => {}, empty = () => '';
                const profileMenu = empty, renderMessage = empty, placeJourneySurface = empty;
                const recallPackagePrompt = empty, workspaceMemoryFocusMarkup = empty;
                const selectedPhotoCue = empty, composerAttachments = empty, composerIcon = empty;
                const bindProfileMenu = noop, disposeCesiumPlaceJourney = noop, initCesiumPlaceJourney = noop;
                const initFamilyVisualizations = noop, bindPhotoPagination = noop, bindPhotoMemoryActions = noop;
                const persistChatHistory = noop, bindHistoricalControls = noop;
                const supabaseApi = noop, toast = noop, currentUiLocale = () => 'zh-CN';
                const submitSectionRework = noop, saveMemoryEventEdit = noop, startMemory = noop, finishChapter = noop;
                const toggleVoiceInput = noop, startAudioRecorder = noop, cancelDictation = noop, discardAudioDraft = noop;
                const addPerson = noop, generatePrivateDraft = noop, retryPrivateDraft = noop, loadMorePrivateDraft = noop;
                const loadMoreMemoryEvents = noop, refreshFamilyContext = noop;
                const mapPhotoAlbums = {sync:noop}, mapMemoryEvents = {sync:noop};
                const storyGameDialog = {sync:noop}, authReminder = {mount:noop};
                const conversationScroll = {following:() => false, pause:noop, follow:noop, mount:noop};
                window.sentMessages = [];
                const sendChatMessage = () => sentMessages.push($('#chat-input').value);
            ''' + '\n'.join(function(name) for name in (
                'captureProjectScope', 'isCurrentProjectScope', 'resizeChatInput',
                'render', 'renderStory', 'storyGameButton', 'chatInputLimitReached', 'chatComposer', 'bindViewActions',
            )) + '\nrender();')
            yield page
        finally:
            browser.close()


def test_workspace_refresh_preserves_active_ime(chat_page):
    page = chat_page
    input_box = page.locator('#chat-input')
    input_box.fill('是')
    ime = page.context.new_cdp_session(page)
    ime.send('Input.imeSetComposition', {'text': 'sfd', 'selectionStart': 3, 'selectionEnd': 3})
    expect(input_box).to_have_value('是sfd')

    page.evaluate('''() => {
        window.composingInput = document.querySelector('#chat-input');
        for (let revision = 1; revision <= 3; revision++) {
            state.workspaceRevision = revision;
            render();
        }
    }''')
    assert page.evaluate('composingInput === document.activeElement && composingInput.isConnected')
    expect(input_box).to_have_value('是sfd')
    assert input_box.evaluate('node => [node.selectionStart, node.selectionEnd]') == [4, 4]
    ime.send('Input.imeSetComposition', {'text': 'shufu', 'selectionStart': 5, 'selectionEnd': 5})
    ime.send('Input.insertText', {'text': '舒服'})

    expect(input_box).to_have_value('是舒服')
    expect(input_box).to_be_focused()
    expect(page.locator('#workspace-detail')).to_have_text('Revision 3')
    assert page.evaluate('state.audioTranscript') == '是舒服'
    assert page.evaluate('sentMessages') == []


@pytest.mark.parametrize('keyboard_event,composition_active', [
    ({'isComposing': True}, False), ({'keyCode': 229}, False), ({}, True),
])
def test_enter_during_composition_does_not_send(chat_page, keyboard_event, composition_active):
    input_box = chat_page.locator('#chat-input')
    input_box.fill('是')
    input_box.dispatch_event('compositionstart')
    if not composition_active:
        input_box.dispatch_event('compositionend')
    input_box.dispatch_event('keydown', {'key': 'Enter', **keyboard_event})
    assert chat_page.evaluate('sentMessages') == []


def test_enter_sends_once_after_composition_finishes(chat_page):
    input_box = chat_page.locator('#chat-input')
    input_box.fill('是舒服')
    input_box.dispatch_event('compositionstart')
    input_box.dispatch_event('compositionend')
    input_box.press('Shift+Enter')
    assert chat_page.evaluate('sentMessages') == []
    input_box.press('Enter')
    assert chat_page.evaluate('sentMessages') == ['是舒服\n']


def test_workspace_refresh_preserves_plain_text_and_selection(chat_page):
    input_box = chat_page.locator('#chat-input')
    input_box.fill('A childhood memory')
    input_box.evaluate('node => node.setSelectionRange(2, 11)')
    chat_page.evaluate('() => { state.workspaceRevision++; render(); }')
    expect(input_box).to_have_value('A childhood memory')
    expect(input_box).to_be_focused()
    assert input_box.evaluate('node => [node.selectionStart, node.selectionEnd]') == [2, 11]
    expect(chat_page.locator('#workspace-detail')).to_have_text('Revision 1')


@pytest.mark.parametrize('change_scope', [
    "state.project = {id:'other-project'}",
    "state.supabase = {user:{id:'other-owner'}}",
    'state.navigationGeneration = 1',
])
def test_composition_does_not_block_navigation(chat_page, change_scope):
    chat_page.locator('#chat-input').fill('unfinished')
    chat_page.locator('#chat-input').dispatch_event('compositionstart')
    chat_page.evaluate('() => { state.workspaceRevision++; render(); }')
    chat_page.evaluate('() => { ' + change_scope + '; render(); }')
    expect(chat_page.locator('#workspace-detail')).to_have_text('Revision 1')
    assert chat_page.evaluate('state.chatComposition') is None
