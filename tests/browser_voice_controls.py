"""Exercise the real composer and audio lifecycle with deterministic media/API doubles."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]


def main():
    source = (ROOT / 'apps/web/client/memoir/client.js').read_text()
    source = '\n'.join(line for line in source.splitlines() if not line.startswith('import '))
    source = source[:source.rindex('installUiLocaleBridge();')]
    catalog = json.loads((ROOT / 'apps/web/messages/en-AU.json').read_text())
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={'width': 1100, 'height': 800})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.route('http://voice.test/**', lambda route: route.fulfill(body='<html><body><div id="app"></div></body></html>', content_type='text/html'))
        page.goto('http://voice.test')
        page.wait_for_load_state('networkidle')
        page.add_style_tag(path=str(ROOT / 'apps/web/public/styles.css'))
        page.evaluate('catalog => window.catalog = catalog', catalog)
        page.add_script_tag(content='''
const translate = key => key.split('.').reduce((value, part) => value?.[part], window.catalog) || key;
const currentUiLocale = () => 'en-AU';
const translateWith = key => translate(key);
const MEMOIR_ROUTES = {home: '/memoir'};
''' + source + '''
Object.defineProperty(window, 'speechSynthesis', {value: {cancel() {}}});
window.testState = state;
window.recorders = [];
window.tracks = [];
window.uploads = 0;
window.turns = 0;
window.playbacks = 0;
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
toast = () => {};
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
syncUiLocaleFromVoiceTranscript = async () => {};
ensureMemorySession = async () => null;
agentTurn = async () => { turns++; return {reply: 'What do you remember?'}; };
streamAssistantMessage = async () => {};
storyApi = async (path, options) => {
  if (path === '/v1/story/transcriptions') {
    uploads++;
    window.lastTranscription = JSON.parse(options.body);
    if (window.failTranscription) throw new Error('Speech unavailable');
    return {text: 'An afternoon by the sea.', source: {language: 'en'}};
  }
  return {url: 'test-audio'};
};
playGeneratedAudio = async () => { playbacks++; };
state.project = {id: 'test'};
render();
''')
        draft = page.get_by_role('textbox', name='Your message')
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
        print('Voice controls passed: cancel, stop/review, draft preservation, explicit send, spoken reply/relisten, mute, exit, pending permission cancellation, attachment selection/removal/upload, mobile layout.')


if __name__ == '__main__':
    main()
