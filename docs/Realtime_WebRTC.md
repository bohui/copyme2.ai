# Voice input and spoken replies

The development app uses one saved conversation engine for typed and spoken input.

1. The browser records microphone audio with `MediaRecorder`.
2. `POST /api/v1/memoir/story/transcriptions` returns the transcript.
3. The browser sends those words to `POST /api/v1/memoir/agent/turn` with `source_kind=narrator_transcript`.
4. The canonical engine saves the source, applies its privacy and publication fences, and produces the reply.
5. Voice mode plays the reply through the speech endpoint, then records the next turn.

Dictation also supports reviewing the transcript before sending it. Stop, cancellation, navigation and logout release microphone tracks. Transcription and spoken replies retain the existing English/Chinese language and voice settings.

The separate direct WebRTC endpoint `/api/v1/memoir/realtime/calls` was removed on 2026-10-14. It did not save voice turns and is no longer an application conversation path. No old Codex home or raw-context worker execution is selected by a compatibility flag.

Checks: `tests/test_canonical_only_conversation.py`, `tests/test_speech.py`, and `tests/test_speech_integration.py` cover transcript forwarding, speech provider contracts and route retirement with controlled providers. These tests do not claim a real microphone or provider session was exercised.
