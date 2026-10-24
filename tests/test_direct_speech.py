"""Exercise the native speech protocols without sending user data to a provider."""

import asyncio
import base64
import gzip
import io
import json
import shutil
import struct
import subprocess
import wave

import httpx
import pytest

from apps.api import speech


def wav_audio():
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as audio:
        audio.setparams((2, 2, 8000, 0, 'NONE', 'not compressed'))
        audio.writeframes(b'\x00\x00' * 2 * 2400)
    return buffer.getvalue()


def gemini_response(content=None):
    return {'candidates': [{'content': {'parts': [{'inlineData': {
        'mimeType': 'audio/wav', 'data': base64.b64encode(content or wav_audio()).decode(),
    }}]}}]}


def test_gemini_uses_native_tts_model_and_separates_delivery_from_the_transcript():
    requests = []

    def provider(request):
        requests.append(request)
        return httpx.Response(200, json=gemini_response())

    service = speech.GeminiSpeechService('gemini-test', client=httpx.Client(
        base_url='https://gemini.test/v1beta', transport=httpx.MockTransport(provider)))
    result = service.synthesize('What do you remember?', language='en-AU')
    assert requests[0].url.path == '/v1beta/models/gemini-3.8-flash-lite-tts:generateContent'
    payload = json.loads(requests[0].content)
    part = payload['contents'][0]['parts'][0]
    assert part['text'] == 'What do you remember?'
    assert 'Australian English' in part['speech_metadata']['style']
    assert payload['generationConfig']['speechConfig'] == {'voiceConfig': {'voice': 'Kore'}}
    assert result['content'] == wav_audio()
    assert result['mime_type'] == 'audio/wav'
    assert result['provider'] == 'gemini'


@pytest.mark.parametrize('status,retryable', [(401, False), (429, True), (503, True)])
def test_gemini_maps_provider_failures_without_exposing_the_response(status, retryable):
    client = httpx.Client(base_url='https://gemini.test', transport=httpx.MockTransport(
        lambda request: httpx.Response(status, json={'error': 'private provider details'})))
    with pytest.raises(speech.SpeechProviderError) as failure:
        speech.GeminiSpeechService('test', client=client).synthesize('Hello')
    assert failure.value.retryable is retryable
    assert 'private' not in str(failure.value)


@pytest.mark.parametrize('response', [
    {}, {'candidates': []}, {'candidates': [{'content': {'parts': []}}]},
    {'candidates': [{'content': {'parts': [{'inlineData': {'mimeType': 'audio/wav', 'data': '!!!'}}]}}]},
    {'candidates': [{'content': {'parts': [{'inlineData': {'mimeType': None, 'data': 'YXVkaW8='}}]}}]},
    gemini_response(b'not a WAV file'),
])
def test_gemini_rejects_malformed_or_missing_audio(response):
    client = httpx.Client(base_url='https://gemini.test', transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=response)))
    with pytest.raises(speech.SpeechProviderError):
        speech.GeminiSpeechService('test', client=client).synthesize('Hello')


def test_gemini_rejects_an_unsupported_format_before_any_paid_request():
    requests = []
    client = httpx.Client(base_url='https://gemini.test', transport=httpx.MockTransport(
        lambda request: requests.append(request)))
    with pytest.raises(speech.SpeechProviderError, match='Unsupported'):
        speech.GeminiSpeechService('test', client=client).synthesize('Hello', output_format='invalid')
    assert requests == []


@pytest.mark.parametrize('response', [None, [], {}, {'text': {'unexpected': 'object'}}])
def test_openai_transcription_rejects_invalid_data(response):
    client = httpx.Client(base_url='https://openai.test', transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=response)))
    with pytest.raises(speech.SpeechProviderError):
        speech.OpenAISpeechService('test', client=client).transcribe(b'recording')


def test_doubao_tts_joins_audio_chunks_and_sends_seed_2_delivery_options():
    requests = []

    def provider(request):
        requests.append(request)
        return httpx.Response(200, text='\n'.join(json.dumps(chunk) for chunk in [
            {'code': 0, 'data': base64.b64encode(b'first').decode()},
            {'code': 0, 'data': base64.b64encode(b'second').decode()},
            {'code': 20000000},
        ]))

    client = httpx.Client(base_url='https://doubao.test', transport=httpx.MockTransport(provider))
    service = speech.DoubaoSpeechService('doubao-test', client=client)
    result = service.synthesize('你还记得吗？', language='zh-CN')
    request = requests[0]
    assert request.url.path == '/api/v3/tts/unidirectional'
    assert request.headers['X-Api-Key'] == 'doubao-test'
    assert request.headers['X-Api-Resource-Id'] == 'seed-tts-2.0'
    params = json.loads(request.content)['req_params']
    assert params['text'] == '你还记得吗？'
    assert params['speaker'] == 'zh_female_vv_uranus_bigtts'
    assert params['audio_params'] == {'format': 'mp3', 'sample_rate': 24000, 'speech_rate': 10}
    assert '普通话' in json.loads(params['additions'])['context_texts'][0]
    assert result['content'] == b'firstsecond'
    assert result['mime_type'] == 'audio/mpeg'
    assert result['model'] == 'doubao-seed-tts-2.0'


@pytest.mark.parametrize('body', [
    'not json', '{}', '{"code": 0, "data": "!!!"}',
    '{"code": 0, "data": "YXVkaW8="}\n{"code": 45000001, "message": "private"}',
])
def test_doubao_tts_discards_audio_when_the_stream_fails(body):
    client = httpx.Client(base_url='https://doubao.test', transport=httpx.MockTransport(
        lambda request: httpx.Response(200, text=body)))
    with pytest.raises(speech.SpeechProviderError) as failure:
        speech.DoubaoSpeechService('test', client=client).synthesize('你好', language='zh')
    assert 'private' not in str(failure.value)


def server_frame(body, *, final=False):
    payload = gzip.compress(json.dumps(body, ensure_ascii=False).encode())
    return bytes((0x11, 0x93 if final else 0x91, 0x11, 0)) + struct.pack('>iI', -1 if final else 1, len(payload)) + payload


class DoubaoSocket:
    def __init__(self, acknowledge_chunks):
        self.acknowledge_chunks = acknowledge_chunks
        self.sent = []
        self.closed = False

    async def __aenter__(self):
        self.responses = asyncio.Queue()
        return self

    async def __aexit__(self, *args):
        self.closed = True

    def __aiter__(self):
        return self

    async def __anext__(self):
        return await self.responses.get()

    async def send(self, frame):
        self.sent.append(frame)
        final = bool(frame[1] & 2)
        if final:
            self.responses.put_nowait(server_frame({'result': {
                'text': '我小时候和二舅去学校。',
                'utterances': [{'text': '我小时候和二舅去学校。', 'start_time': 0, 'end_time': 300}],
            }}, final=True))
        elif self.acknowledge_chunks or frame[1] >> 4 == 1:
            self.responses.put_nowait(server_frame({}))


@pytest.mark.parametrize('acknowledge_chunks', [True, False])
def test_doubao_asr_sends_pcm_and_finishes_with_or_without_chunk_acknowledgements(monkeypatch, acknowledge_chunks):
    socket = DoubaoSocket(acknowledge_chunks)
    connections = []
    pcm = b'\x00\x01' * 7000
    conversions = []

    def convert(audio, output_format, **options):
        conversions.append((audio, output_format, options))
        return pcm

    def connect(url, **options):
        connections.append((url, options))
        return socket

    monkeypatch.setattr(speech, '_transcode_audio', convert)
    monkeypatch.setattr(speech, 'connect', connect)
    service = speech.DoubaoSpeechService('doubao-test')
    original = b'original private WebM recording'
    result = service.transcribe(original, language='zh-CN', mime_type='audio/webm')
    assert connections[0][0].endswith('/api/v3/sauc/bigmodel_nostream')
    headers = connections[0][1]['additional_headers']
    assert headers['X-Api-Key'] == 'doubao-test'
    assert headers['X-Api-Resource-Id'] == 'volc.seedasr.sauc.duration'
    assert conversions == [(original, 'pcm', {'sample_rate': 16000})]
    config = json.loads(gzip.decompress(socket.sent[0][8:]))
    assert config['audio'] == {'format': 'pcm', 'codec': 'raw', 'rate': 16000, 'bits': 16, 'channel': 1}
    assert config['request']['enable_ddc'] is False
    assert all(frame[1] == 0x20 for frame in socket.sent[1:-1])
    assert socket.sent[-1][1] == 0x22
    assert b''.join(gzip.decompress(frame[8:]) for frame in socket.sent[1:]) == pcm
    assert result['text'] == '我小时候和二舅去学校。'
    assert result['provider'] == 'doubao'
    assert result['model'] == 'doubao-seed-asr-2.0'
    assert result['segments'][0]['end_time'] == 300
    assert socket.closed


@pytest.mark.parametrize('frame', [
    'not binary', b'', b'\x11\x91\x11\x00',
    b'\x11\x93\x11\x00\xff\xff\xff\xff\x00\x00\x00\x02{}',
    server_frame([]), server_frame({})[:-1],
    bytes((0x11, 0xf0, 0x10, 0)) + struct.pack('>II', 45000001, 0),
])
def test_doubao_asr_rejects_invalid_or_error_frames(frame):
    with pytest.raises(speech.SpeechProviderError):
        speech._doubao_result(frame)


@pytest.mark.skipif(not shutil.which('ffmpeg'), reason='FFmpeg is required in the API runtime')
@pytest.mark.parametrize('container,codec', [('webm', 'libopus'), ('mp4', 'aac')])
def test_browser_recordings_really_convert_to_16khz_mono_pcm(container, codec):
    command = ['ffmpeg', '-v', 'error', '-i', 'pipe:0', '-acodec', codec]
    if container == 'mp4':
        command += ['-movflags', 'frag_keyframe+empty_moov']
    recording = subprocess.run(command + ['-f', container, 'pipe:1'], input=wav_audio(),
                               capture_output=True, check=True, timeout=10).stdout
    converted = speech._transcode_audio(recording, 'pcm', sample_rate=16000)
    # 300 ms of mono, signed 16-bit PCM at 16 kHz, allowing codec padding.
    assert 9000 <= len(converted) <= 18000
    assert recording != converted


@pytest.mark.skipif(not shutil.which('ffmpeg'), reason='FFmpeg is required in the API runtime')
def test_gemini_can_honor_an_explicit_mp3_request():
    client = httpx.Client(base_url='https://gemini.test', transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=gemini_response())))
    result = speech.GeminiSpeechService('test', client=client).synthesize('Hello', output_format='mp3')
    assert result['mime_type'] == 'audio/mpeg'
    assert result['content'].startswith((b'ID3', b'\xff'))


@pytest.mark.parametrize('language,provider,model,voice,output_format', [
    ('zh-CN', 'cosyvoice', 'cosyvoice-v3-flash', 'longwan_v3', 'mp3'),
    ('zh_CN', 'cosyvoice', 'cosyvoice-v3-flash', 'longwan_v3', 'mp3'),
    ('zh', 'cosyvoice', 'cosyvoice-v3-flash', 'longwan_v3', 'mp3'),
    ('en-AU', 'cosyvoice', 'cosyvoice-v3-flash', 'longwan_v3', 'mp3'),
    ('en', 'cosyvoice', 'cosyvoice-v3-flash', 'longwan_v3', 'mp3'),
])
def test_localized_synthesis_resolves_the_exact_provider_model_voice_and_format(monkeypatch, language, provider, model, voice, output_format):
    monkeypatch.delenv('MEMORY_SPARK_TTS_VOICE_EN_AU', raising=False)
    monkeypatch.delenv('MEMORY_SPARK_TTS_VOICE_ZH_CN', raising=False)
    service = speech.build_speech_service()
    options = speech.speech_synthesis_options(service, language)
    assert (options['provider'], options['model'], options['voice'], options['output_format']) == (provider, model, voice, output_format)


def test_partial_credentials_do_not_dispatch_to_another_provider(monkeypatch):
    monkeypatch.delenv('GROQ_API_KEY', raising=False)
    monkeypatch.delenv('DASHSCOPE_API_KEY', raising=False)
    monkeypatch.delenv('DASHSCOPE_WORKSPACE_ID', raising=False)
    service = speech.build_speech_service()
    with pytest.raises(speech.SpeechUnavailable, match='GROQ_API_KEY'):
        service.transcribe(b'audio', language='zh-CN')
    with pytest.raises(speech.SpeechUnavailable, match='DASHSCOPE_API_KEY'):
        service.synthesize('你好', language='zh-CN')
    with pytest.raises(speech.SpeechUnavailable, match='DASHSCOPE_API_KEY'):
        service.synthesize('Hello', language='en-AU')
    assert service.stt.api_key == ''


def test_transcription_routes_through_groq_and_qwen_fallback(monkeypatch):
    service = speech.build_speech_service()
    calls = []

    def groq(audio, **options):
        calls.append(('groq', audio, options['language']))
        return {'text': 'An English memory.'}

    def qwen(audio, **options):
        calls.append(('qwen', audio, options['language']))
        return {'text': '童年的回忆。'}

    monkeypatch.setattr(service.stt, 'transcribe', groq)
    monkeypatch.setattr(service.fallback, 'transcribe', qwen)
    assert service.transcribe(b'english', language='en-AU')['text'] == 'An English memory.'
    def unavailable(*args, **kwargs):
        raise speech.SpeechProviderError('Groq unavailable')
    monkeypatch.setattr(service.stt, 'transcribe', unavailable)
    assert service.transcribe(b'chinese', language='zh_CN')['text'] == '童年的回忆。'
    assert calls == [('groq', b'english', 'en-AU'), ('qwen', b'chinese', 'zh_CN')]


@pytest.mark.parametrize('service', [speech.GeminiSpeechService, speech.DoubaoSpeechService])
def test_native_speech_services_only_accept_managed_delivery_prompts(service):
    with pytest.raises(ValueError, match='managed'):
        service('test').synthesize('Hello', instructions='Unreviewed model instructions')


def test_groq_transcription_uses_whisper_turbo_and_openai_compatible_multipart():
    requests = []

    def provider(request):
        requests.append(request)
        return httpx.Response(200, json={'text': 'A remembered place.', 'language': 'en', 'segments': []})

    client = httpx.Client(
        base_url='https://groq.test/openai/v1', transport=httpx.MockTransport(provider),
    )
    result = speech.GroqSpeechService('groq-test', client=client).transcribe(
        b'private audio', filename='memory.webm', mime_type='audio/webm', language='en-AU',
    )
    request = requests[0]
    assert request.url.path == '/openai/v1/audio/transcriptions'
    assert request.headers['Authorization'] == 'Bearer groq-test'
    body = request.content
    assert b'name="model"' in body and b'whisper-large-v3-turbo' in body
    assert b'name="language"' in body and b'en' in body
    assert b'filename="memory.webm"' in body
    assert result == {
        'text': 'A remembered place.', 'language': 'en', 'segments': [],
        'model': 'whisper-large-v3-turbo', 'provider': 'groq',
    }


def test_qwen_fallback_sends_dashscope_data_url_payload():
    requests = []

    def provider(request):
        requests.append(request)
        return httpx.Response(200, json={
            'choices': [{'message': {'content': '童年的回忆。'}}],
        })

    client = httpx.Client(
        base_url='https://dashscope.test', transport=httpx.MockTransport(provider),
    )
    result = speech.QwenASRService(
        'dashscope-test', workspace_id='workspace-test', client=client,
    ).transcribe(b'abc', mime_type='audio/webm', language='zh-CN')
    request = requests[0]
    assert request.url.path == '/compatible-mode/v1/chat/completions'
    assert request.headers['Authorization'] == 'Bearer dashscope-test'
    payload = json.loads(request.content)
    audio_data = payload['messages'][0]['content'][0]['input_audio']['data']
    assert payload['model'] == 'qwen3-asr-flash'
    assert audio_data == 'data:audio/webm;base64,YWJj'
    assert payload['asr_options'] == {'enable_itn': False}
    assert result['text'] == '童年的回忆。'
    assert result['provider'] == 'qwen'


class CosyVoiceSocket:
    def __init__(self):
        self.sent = []
        self.messages = [
            json.dumps({'header': {'event': 'task-started'}}),
            b'first-audio',
            b'second-audio',
            json.dumps({'header': {'event': 'task-finished'}}),
        ]

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self.messages:
            raise StopAsyncIteration
        return self.messages.pop(0)

    async def send(self, message):
        self.sent.append(json.loads(message))


def test_cosyvoice_synthesis_uses_bilingual_voice_and_duplex_task_protocol(monkeypatch):
    socket = CosyVoiceSocket()
    connections = []

    def connect(url, **options):
        connections.append((url, options))
        return socket

    monkeypatch.setattr(speech, 'connect', connect)
    result = speech.CosyVoiceSpeechService(
        'dashscope-test', workspace_id='workspace-test', region='ap-southeast-1',
    ).synthesize('What do you remember?', language='en-AU')
    assert connections[0][0] == 'wss://workspace-test.ap-southeast-1.maas.aliyuncs.com/api-ws/v1/inference'
    headers = connections[0][1]['additional_headers']
    assert headers['Authorization'] == 'Bearer dashscope-test'
    assert headers['X-DashScope-WorkSpace'] == 'workspace-test'
    assert [message['header']['action'] for message in socket.sent] == [
        'run-task', 'continue-task', 'finish-task',
    ]
    assert socket.sent[0]['payload']['model'] == 'cosyvoice-v3-flash'
    assert socket.sent[0]['payload']['parameters']['voice'] == 'longwan_v3'
    assert socket.sent[1]['payload']['input']['text'] == 'What do you remember?'
    assert result == {
        'content': b'first-audiosecond-audio', 'mime_type': 'audio/mpeg',
        'model': 'cosyvoice-v3-flash', 'voice': 'longwan_v3', 'provider': 'cosyvoice',
    }
