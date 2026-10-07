"""Run the real voice reply path across successful and failed audio turns."""

import json
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("failure_stage", ["generation", "playback"])
@pytest.mark.parametrize("error_status", [None, 503, 502, 429])
def test_voice_reply_keeps_the_same_speaker_after_audio_failure(failure_stage, error_status):
    program = r'''
const fs = require('node:fs'), vm = require('node:vm');
const scenario = JSON.parse(fs.readFileSync(0, 'utf8'));
const source = fs.readFileSync('apps/web/client/memoir/client.js', 'utf8');
const speakers = [], requests = [], notifications = [];
let turn = 0;
const error = Object.assign(new Error('Provider failed'), {status: scenario.error_status});
const context = vm.createContext({
  state: {voiceMode: true, voiceModeTurnId: 1},
  render() {},
  currentUiLocale: () => 'en-AU',
  conversationLanguage: () => turn === 1 ? 'zh-CN' : 'en-AU',
  conversationMessage: () => 'Voice playback is unavailable.',
  toast: message => notifications.push(message),
  storyApi: async (path, options) => {
    requests.push({path, ...JSON.parse(options.body)});
    if (turn === 1 && scenario.failure_stage === 'generation') throw error;
    return {voice: JSON.parse(options.body).language === 'zh-CN' ? 'coral' : 'marin'};
  },
  playGeneratedAudio: async generated => {
    if (turn === 1 && scenario.failure_stage === 'playback') throw error;
    speakers.push(generated.voice);
  },
  SpeechSynthesisUtterance: class { constructor(text) { this.text = text; } },
  window: {SpeechSynthesisUtterance: true, speechSynthesis: {
    cancel() {},
    speak(utterance) {
      speakers.push(utterance.voice?.name || 'system-default-male');
      utterance.onend?.();
    },
  }},
});
for (const name of ['speakBrowserText', 'speakVoiceReply']) {
  const match = source.match(new RegExp(`(?:async )?function ${name}\\([^]*?\\n\\}`));
  if (match) vm.runInContext(match[0], context);
}
(async () => {
  for (turn = 0; turn < 3; turn++) await context.speakVoiceReply('A memory to explore.');
  process.stdout.write(JSON.stringify({speakers, requests, notifications}));
})().catch(error => { console.error(error); process.exitCode = 1; });
'''
    result = subprocess.run(
        ["node", "-e", program], cwd=ROOT,
        input=json.dumps({"failure_stage": failure_stage, "error_status": error_status}),
        text=True, capture_output=True, check=True,
    )
    observed = json.loads(result.stdout)
    assert observed["speakers"] == ["marin", "marin"], observed
    assert all("voice" not in request and "instructions" not in request for request in observed["requests"])
    assert [request["language"] for request in observed["requests"]] == ["en-AU", "zh-CN", "en-AU"]
    assert observed["notifications"] == ["Voice playback is unavailable."]


def test_voice_mode_prevents_separate_read_aloud_from_changing_the_speaker():
    program = r'''
const fs = require('node:fs'), vm = require('node:vm');
const source = fs.readFileSync('apps/web/client/memoir/client.js', 'utf8');
let playbacks = 0;
const context = vm.createContext({
  state: {voiceMode: true}, CHATBOT_NAME: 'Mira',
  cleanAssistantText: text => text, escapeHtml: text => text, formatText: text => text,
  translate: key => key, renderAgentTrace: () => '',
  SpeechSynthesisUtterance: class {},
  currentUiLocale: () => 'zh-CN',
  window: {speechSynthesis: {cancel() {}, speak() { playbacks++; }}},
});
for (const name of ['renderMessage', 'speakText']) {
  vm.runInContext(source.match(new RegExp(`(?:async )?function ${name}\\([^]*?\\n\\}`))[0], context);
}
(async () => {
  const message = {role: 'assistant', text: 'Tell me about your childhood.'};
  const duringVoice = context.renderMessage(message);
  await context.speakText(message.text);
  context.state.voiceMode = false;
  const afterVoice = context.renderMessage(message);
  process.stdout.write(JSON.stringify({duringVoice, afterVoice, playbacks}));
})().catch(error => { console.error(error); process.exitCode = 1; });
'''
    result = subprocess.run(["node", "-e", program], cwd=ROOT, text=True, capture_output=True, check=True)
    observed = json.loads(result.stdout)
    assert 'data-action="speak"' not in observed["duringVoice"]
    assert 'data-action="speak"' in observed["afterVoice"]
    assert observed["playbacks"] == 0
