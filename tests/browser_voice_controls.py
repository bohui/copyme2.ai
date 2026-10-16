"""Exercise the real composer and audio lifecycle with deterministic media/API doubles."""
import json
import re
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]


def main():
    source = (ROOT / 'apps/web/client/memoir/client.js').read_text()
    # This fixture replaces individual media functions with deterministic doubles.
    # Keep that legacy harness while sourcing the functions from their new module.
    audio_source = (ROOT / 'apps/web/client/memoir/conversation-audio.mjs').read_text()
    audio_source = re.sub(r'^  ', '', audio_source, flags=re.M)
    audio_functions = '\n'.join(re.findall(r'^(?:async )?function \w+\(.*?\n\}', audio_source, re.S | re.M))
    source = re.sub(r'const \{[^}]+\} = createConversationAudio\(\{[^}]+\}\);',
                    lambda _: audio_functions, source)
    source = source.replace('createInterviewPhotoState({state, scope:captureProjectScope, render, api,',
                            "createInterviewPhotoState({state, scope:captureProjectScope, render: () => render(), api: (...args) => api(...args), uuid: () => 'voice-turn-' + (window.turns || 0),")
    imports = [(names, relative) for names, relative in
               re.findall(r'import \{([^}]+)\} from "([^"]+)";', source)
               if relative.startswith('.')]
    source = '\n'.join(line for line in source.splitlines() if not line.startswith('import '))
    source = source[:source.rindex('installUiLocaleBridge();')]
    catalog = json.loads((ROOT / 'apps/web/messages/en-AU.json').read_text())
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={'width': 1100, 'height': 800})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        def serve(route):
            path = urlsplit(route.request.url).path
            if path == '/':
                return route.fulfill(body='<html><body><div id="app"></div></body></html>', content_type='text/html')
            file = ROOT / 'apps/web' / path.lstrip('/')
            route.fulfill(body=file.read_text(), content_type='application/json' if file.suffix == '.json' else 'text/javascript')
        page.route('http://voice.test/**', serve)
        page.goto('http://voice.test')
        page.wait_for_load_state('networkidle')
        page.add_style_tag(path=str(ROOT / 'apps/web/public/styles.css'))
        page.evaluate('catalog => window.catalog = catalog', catalog)
        page.evaluate('''async imports => {
          for (const [names, relative] of imports) {
            const url = new URL(relative, 'http://voice.test/client/memoir/client.js').href;
            const module = await import(url);
            for (const name of names.split(',').map(name => name.trim())) window[name] = module[name];
          }
        }''', imports)
        page.evaluate('messages => {window.englishMessages = messages[0]; window.chineseMessages = messages[1];}',
            [catalog, json.loads((ROOT / 'apps/web/messages/zh-CN.json').read_text())])
        page.add_script_tag(content='''
const translate = key => key.split('.').reduce((value, part) => value?.[part], window.catalog) || key;
const currentUiLocale = () => 'en-AU';
const translateWith = (key, values = {}) => Object.entries(values).reduce((text, [name, value]) => text.replaceAll('{' + name + '}', String(value)), translate(key));
const MEMOIR_ROUTES = {home: '/memoir'};
''' + source + '''
window.browserSpeeches = [];
Object.defineProperty(window, 'speechSynthesis', {value: {cancel() {}, speak(utterance) {
  browserSpeeches.push(utterance.text); utterance.onend?.();
}}});
window.testState = state;
window.recorders = [];
window.tracks = [];
window.uploads = 0;
window.turns = 0;
window.turnRequests = [];
window.recordingUploads = new Map();
window.deletedRecordings = [];
window.recordingSequence = 0;
Object.defineProperty(window.crypto,'randomUUID',{value:()=> 'aaaaaaaa-aaaa-4aaa-8aaa-' + String(++window.recordingSequence).padStart(12,'0')});
window.playbacks = 0;
window.spokenRequests = [];
window.speakers = [];
window.notifications = [];
window.mediaRequests = [];
api = async (path, options = {}) => {
  mediaRequests.push({path, body: options.body ? JSON.parse(options.body) : null});
  if (path === '/v1/uploads') return {id: `upload-${mediaRequests.length}`, max_part_size: 5};
  if (path.endsWith('/finalize')) return {id: `asset-${mediaRequests.length}`};
  return {state: 'UPLOADING'};
};
Object.defineProperty(navigator, 'mediaDevices', {value: {getUserMedia: async () => {
  const track = {enabled: true, stopped: false, stop() { this.stopped = true; }};
  tracks.push(track);
  return {getTracks: () => [track]};
}}});
window.MediaRecorder = class {
  static isTypeSupported() { return true; }
  constructor() { this.state = 'inactive'; this.mimeType = 'audio/webm'; this.listeners = {}; recorders.push(this); }
  addEventListener(name, callback) { this.listeners[name] = callback; }
  start() { this.state = 'recording'; }
  stop() { this.state = 'inactive'; queueMicrotask(() => {
    this.listeners.dataavailable?.({data: new Blob(['audio'])}); this.listeners.stop?.();
  }); }
};
render = () => { document.querySelector('#app').innerHTML = `<main class="chat-main"><header class="chat-heading"><h1>Your story</h1></header><div class="chat-scroll"><p>Tell me about an afternoon you remember.</p></div>${chatComposer()}</main>`; bindViewActions(); };
toast = message => notifications.push(message);
window.micLevel = 128;
window.audioContexts = [];
window.AudioContext = class {
  constructor() { this.closed = false; audioContexts.push(this); }
  createMediaStreamSource() { return {connect() {}}; }
  createMediaElementSource() { return {connect() {}}; }
  createAnalyser() { return {fftSize: 512, connect() {}, getByteTimeDomainData(data) { data.fill(micLevel); }}; }
  resume() { return Promise.resolve(); }
  close() { this.closed = true; return Promise.resolve(); }
};
ensureMemorySession = async () => null;
agentTurn = async (text, fallback, tools, language, first, conversationText, action, sourceKind, photoOptions = {}) => {
  turnRequests.push({sourceKind,...photoOptions});
  turns++;
  const turn = state.photoTurns.prepare({text, conversationText, sourceKind, attachments: state.attachments, recordingIds:photoOptions.recordingIds});
  const result = {reply: 'What do you remember?', conversation_saved: true};
  state.photoTurns.finish(turn, result);
  return result;
};
streamAssistantMessage = async () => {};
storyApi = async (path, options) => {
  if (path === '/v1/story/transcriptions') {
    uploads++;
    window.lastTranscription = JSON.parse(options.body);
    if (window.failTranscription) throw new Error('Speech unavailable');
    const recordingId = recordingUploads.get(lastTranscription.upload_idempotency_key) || 'recording-' + uploads;
    recordingUploads.set(lastTranscription.upload_idempotency_key, recordingId);
    if (window.holdTranscription) await new Promise(resolve => window.releaseTranscription = resolve);
    return {text: 'An afternoon by the sea.', source: {language: 'en'}, recording:{id:recordingId, backend_saved:true, storage_status:'ready'}};
  }
  if (path.startsWith('/v1/story/recordings/by-upload/')) {
    const id = recordingUploads.get(path.split('/').at(-1));
    if (!id) throw Object.assign(new Error('Missing'),{status:404});
    return {recording:{id}};
  }
  if (path.startsWith('/v1/story/recordings/') && options?.method === 'DELETE') {
    deletedRecordings.push(path.split('/').at(-1).split('?')[0]);
    return {deleted:true};
  }
  if (path === '/v1/story/question-audio') {
    const speech = JSON.parse(options.body);
    spokenRequests.push(speech);
    if (window.failSynthesis) throw Object.assign(new Error('Speech unavailable'), {status: 503});
    return {voice: speech.language === 'zh-CN' ? 'coral' : 'marin'};
  }
  return {url: 'test-audio'};
};
playGeneratedAudio = async generated => { playbacks++; speakers.push(generated.voice); };
        state.project = {id: 'test'};
render();
''')
        assert not errors, errors
        draft = page.get_by_role('textbox', name='Your message')
        initial_height = draft.bounding_box()['height']
        assert initial_height <= 60
        draft.fill('One line.')
        single_line_height = draft.bounding_box()['height']
        draft.fill('\n'.join(f'Line {index}' for index in range(24)))
        expanded_height = draft.bounding_box()['height']
        max_height = page.evaluate("parseFloat(getComputedStyle(document.querySelector('#chat-input')).maxHeight)")
        assert expanded_height > single_line_height
        assert expanded_height <= max_height + 1
        assert draft.evaluate("element => element.style.overflowY") == 'auto'
        draft.fill('My draft.')
        page.get_by_role('button', name='Dictate', exact=True).click()
        expect(page.get_by_text('Recording…', exact=True)).to_be_visible()
        page.wait_for_function("document.querySelector('.dictation-wave i').style.height === '3px'")
        page.evaluate('micLevel = 160')
        page.wait_for_function("parseFloat(document.querySelector('.dictation-wave i:last-child').style.height) > 20")
        page.get_by_role('button', name='Cancel dictation').click()
        assert page.evaluate('audioContexts.every(context => context.closed)')
        expect(draft).to_have_value('My draft.')
        assert page.evaluate('uploads') == 0
        page.get_by_role('button', name='Dictate', exact=True).click()
        page.get_by_role('button', name='Stop recording').click()
        expect(draft).to_have_value('My draft. An afternoon by the sea.')
        assert page.evaluate('turns') == 0
        assert page.evaluate('uploads') == 1
        assert page.evaluate('lastTranscription.audio_base64') == 'YXVkaW8='
        assert page.evaluate('mediaRequests.length') == 0
        assert page.evaluate('audioContexts.every(context => context.closed)')
        page.get_by_role('button', name='Send message').click()
        page.wait_for_function('turns === 1 && !testState.loading')
        assert page.evaluate('playbacks') == 0
        assert page.evaluate('turnRequests[0].recordingIds') == ['recording-1']
        assert page.evaluate('testState.audioRecordings') == []
        # Add files with the plus button; upload only on explicit send.
        with page.expect_file_chooser() as chooser:
            page.get_by_role('button', name='Add pictures or videos').click()
        chooser.value.set_files([
            {'name': 'holiday.png', 'mimeType': 'image/png', 'buffer': b'\x89PNG\r\n\x1a\nphoto'},
            {'name': 'holiday.mp4', 'mimeType': 'video/mp4', 'buffer': b'video-fixture'},
        ])
        expect(page.locator('.composer-attachment')).to_have_count(2)
        assert page.evaluate('mediaRequests.length') == 0
        page.get_by_role('button', name='Remove attachment: holiday.png').click()
        expect(page.locator('.composer-attachment')).to_have_count(1)
        page.get_by_role('button', name='Send message').click()
        assert page.evaluate('mediaRequests.length') == 0
        page.get_by_role('checkbox').check()
        page.get_by_role('button', name='Send message').click()
        page.wait_for_function('turns === 2 && !testState.loading')
        assert page.evaluate("mediaRequests[0].body.kind") == 'video'
        assert page.evaluate("mediaRequests.filter(r => r.path.endsWith('/parts')).length") == 3
        expect(page.locator('.composer-attachment')).to_have_count(0)
        # Send from recording transcribes and dispatches exactly once.
        draft.fill('Another draft.')
        page.get_by_role('button', name='Dictate', exact=True).click()
        page.get_by_role('button', name='Send message').click()
        page.wait_for_function('turns === 3 && !testState.loading')
        assert page.evaluate('testState.chat.at(-1).text') == 'Another draft. An afternoon by the sea.'
        expect(draft).to_have_value('')
        # Failed STT must preserve the draft and must not send it.
        draft.fill('Keep this draft.')
        page.evaluate('failTranscription = true')
        page.get_by_role('button', name='Dictate', exact=True).click()
        page.get_by_role('button', name='Send message').click()
        expect(draft).to_have_value('Keep this draft.')
        assert page.evaluate('turns') == 3
        page.evaluate('failTranscription = false')
        page.get_by_role('button', name='Dictate', exact=True).click()
        page.wait_for_function('testState.pendingAudioUpload === null && testState.dictationStatus === \"off\"')
        page.get_by_role('button', name='Discard draft recordings', exact=True).click()
        page.wait_for_function('testState.audioRecordings.length === 0')
        draft.fill('')
        page.get_by_role('button', name='Start voice conversation').click()
        expect(page.locator('.voice-orb')).to_be_visible()
        page.wait_for_function("Number(document.querySelector('.voice-orb').style.getPropertyValue('--voice-level')) > 0.5")
        orb = page.locator('.voice-orb').bounding_box()
        composer = page.locator('.chat-composer').bounding_box()
        assert orb['y'] > 0 and orb['y'] + orb['height'] < composer['y']
        page.evaluate('micLevel = 128')
        page.wait_for_function("Number(document.querySelector('.voice-orb').style.getPropertyValue('--voice-level')) === 0")
        wave_transform = page.locator('.voice-orb-water i').first.evaluate("el => getComputedStyle(el).transform")
        page.wait_for_function("previous => getComputedStyle(document.querySelector('.voice-orb-water i')).transform !== previous", arg=wave_transform)
        page.screenshot(path=str(ROOT / 'output/playwright/voice-orb-desktop.png'))
        page.set_viewport_size({'width': 375, 'height': 700})
        page.screenshot(path=str(ROOT / 'output/playwright/voice-orb-mobile.png'))
        orb = page.locator('.voice-orb').bounding_box()
        composer = page.locator('.chat-composer').bounding_box()
        assert orb['y'] > 0 and orb['y'] + orb['height'] < composer['y']
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.emulate_media(reduced_motion='reduce')
        assert page.locator('.voice-orb-water i').first.evaluate("el => getComputedStyle(el).animationName") == 'none'
        page.emulate_media(reduced_motion='no-preference')
        page.set_viewport_size({'width': 1100, 'height': 800})
        page.get_by_role('button', name='Mute microphone', exact=True).click()
        assert page.evaluate('tracks.at(-1).enabled') is False
        assert page.locator('.voice-orb-water i').first.evaluate("el => getComputedStyle(el).animationPlayState") == 'paused'
        page.get_by_role('button', name='Unmute microphone', exact=True).click()
        assert page.evaluate('tracks.at(-1).enabled') is True
        page.get_by_role('button', name='Send message').click()
        page.wait_for_function('turns === 4 && playbacks === 1 && testState.voiceModeStatus === "listening"')
        page.screenshot(path=str(ROOT / 'output/playwright/voice-composer.png'))
        # A failed spoken reply stays in text, then relistens without switching voices.
        page.evaluate('failSynthesis = true')
        page.get_by_role('button', name='Send message').click()
        page.wait_for_function('turns === 5 && testState.voiceModeStatus === "listening" && !testState.loading')
        assert page.evaluate('playbacks') == 1
        assert page.evaluate('browserSpeeches') == []
        assert page.evaluate('notifications.at(-1)') == 'Voice playback is unavailable.'
        page.evaluate('failSynthesis = false')
        page.get_by_role('button', name='Send message').click()
        page.wait_for_function('turns === 6 && playbacks === 2 && testState.voiceModeStatus === "listening"')
        assert page.evaluate('speakers') == ['marin', 'marin']
        assert page.evaluate('spokenRequests.every(request => !request.voice && !request.instructions)')
        page.get_by_role('button', name='End voice conversation').click()
        expect(page.locator('.voice-orb')).to_have_count(0)
        assert page.evaluate('tracks.every(track => track.stopped)')
        assert page.evaluate('audioContexts.every(context => context.closed)')
        # Output audio uses the same level response and releases its audio graph.
        page.evaluate('''() => {
          testState.voiceMode = true;
          testState.voiceModeStatus = 'speaking';
          render();
          micLevel = 160;
          window.stopPlaybackMonitor = monitorVoicePlayback({});
        }''')
        page.wait_for_function("Number(document.querySelector('.voice-orb').style.getPropertyValue('--voice-level')) > 0.5")
        page.screenshot(path=str(ROOT / 'output/playwright/voice-orb-speaking.png'))
        page.evaluate('stopPlaybackMonitor(); stopVoiceMode({silent: true})')
        assert page.evaluate('audioContexts.every(context => context.closed)')
        # Several dictated clips keep their order through typed edits and send.
        for _ in range(2):
            page.get_by_role('button', name='Dictate', exact=True).click()
            page.get_by_role('button', name='Stop recording', exact=True).click()
            page.wait_for_function('testState.dictationStatus === "off"')
        clips = page.evaluate('testState.audioRecordings.map(recording => recording.id)')
        assert len(clips) == 2
        draft.fill('Corrected date and a typed clarification.')
        page.get_by_role('button', name='Send message', exact=True).click()
        page.wait_for_function('turns === 7 && !testState.loading')
        assert page.evaluate('turnRequests.at(-1).recordingIds') == clips
        assert page.evaluate('turnRequests.at(-1).sourceKind') == 'narrator_transcript'
        # Cancelling an in-flight appended clip preserves the earlier original.
        page.get_by_role('button', name='Dictate', exact=True).click()
        page.get_by_role('button', name='Stop recording', exact=True).click()
        page.wait_for_function('testState.audioRecordings.length === 1')
        earlier = page.evaluate('testState.audioRecordings[0].id')
        page.evaluate('holdTranscription = true')
        page.get_by_role('button', name='Dictate', exact=True).click()
        page.get_by_role('button', name='Stop recording', exact=True).click()
        page.wait_for_function('typeof window.releaseTranscription === "function"')
        page.get_by_role('button', name='Cancel dictation', exact=True).click()
        page.evaluate('holdTranscription = false; releaseTranscription()')
        page.wait_for_function('testState.pendingAudioUpload === null')
        assert page.evaluate('testState.audioRecordings.map(recording => recording.id)') == [earlier]
        assert earlier not in page.evaluate('deletedRecordings')
        page.get_by_role('button', name='Discard draft recordings', exact=True).click()
        page.wait_for_function('testState.audioRecordings.length === 0')
        # Cancel while permission is pending: the eventual stream must be released.
        page.evaluate('() => { navigator.mediaDevices.getUserMedia = () => new Promise(resolve => window.allowMic = resolve); }')
        page.get_by_role('button', name='Dictate', exact=True).click()
        page.get_by_role('button', name='Cancel dictation').click()
        page.evaluate('allowMic({getTracks: () => [{stop: () => window.lateTrackStopped = true}]})')
        page.wait_for_function('window.lateTrackStopped === true')
        expect(draft).to_be_visible()
        page.set_viewport_size({'width': 375, 'height': 700})
        page.screenshot(path=str(ROOT / 'output/playwright/voice-composer-mobile.png'))
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), page.evaluate('[...document.querySelectorAll("*")].filter(e => e.getBoundingClientRect().right > innerWidth).map(e => [e.tagName, e.className, e.getBoundingClientRect().right])')
        assert not errors, errors
        browser.close()
        print('Voice controls passed: ordered recording references, edited multi-clip dictation, append cancellation, cancel, stop/review, draft preservation, explicit send, consistent speaker after synthesis failure, spoken reply/relisten, mute, exit, pending permission cancellation, attachment selection/removal/upload, mobile layout.')


if __name__ == '__main__':
    main()
