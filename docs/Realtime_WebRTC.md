# Mira Realtime/WebRTC backend

## Implemented scope

`POST /api/v1/memoir/realtime/calls` (legacy alias `/v1/realtime/calls`) authenticates the supplied Supabase bearer token, reads that user's RLS-protected profile and recent memories, then exchanges the SDP offer using OpenAI's [Realtime unified WebRTC interface](https://developers.openai.com/api/docs/guides/voice-webrtc?api=realtime). Audio subsequently travels directly between the browser and OpenAI. No permanent or ephemeral OpenAI credential is returned to the browser.

The backend reuses the versioned Mira journalist prompt, adds the selected conversation language, and supplies bounded private context labelled as untrusted recollections. It does not attach extraction skills or speak machine markers. Low-eagerness semantic VAD allows more time for recollection; automatic replies and interruption are enabled. Input transcription is enabled for later UI integration.

## Configuration

- `OPENAI_API_KEY`: server-only project credential with access to the selected model.
- `OPENAI_BASE_URL`: defaults to `https://api.openai.com/v1`; any override must support the Realtime calls API, not just Chat Completions.
- `MEMORY_SPARK_REALTIME_MODEL`: defaults to `gpt-realtime-2.1`.
- `MEMORY_SPARK_REALTIME_VOICE`: defaults to `marin`.
- `MEMORY_SPARK_STT_MODEL`: defaults to `gpt-4o-mini-transcribe`.
- Existing `SUPABASE_URL` and `SUPABASE_PUBLISHABLE_KEY` are required. Legacy test accounts do not bypass this authentication.

Model, voice, instructions and provider URL are controlled by server configuration. The creation request cannot override them. Credentials and upstream error bodies are never relayed. Creation has a 30-second provider timeout and no automatic retries, since a timeout can occur after a billable call was created.

## HTTP contract

Headers: `Authorization: Bearer <Supabase access token>`, `Content-Type: application/json`.

```json
{"sdp":"<browser audio SDP offer>","language":"zh-CN"}
```

`language` accepts `en-AU` (default) or `zh-CN`. Unknown fields are rejected. SDP is limited to 65,536 characters and the complete JSON body to 96 KiB, including chunked requests.

Success: **201**, `Content-Type: application/sdp`, `Cache-Control: no-store`, raw SDP answer body. No call identifier, provider credential or private context is returned in the HTTP response.

Errors: **401** invalid/missing login; **413** oversized request; **415** wrong content type; **422** malformed payload; **429** provider quota/capacity; **502** provider or context-loading failure; **503** missing configuration/auth service unavailable; **504** provider timeout. Errors use the application's normal error response. Do not retry a failed call automatically.

## Frontend handoff — not implemented in this backend change

1. On explicit user start, request microphone permission (HTTPS or localhost). Create an `RTCPeerConnection`, attach the microphone track and a remote audio element, and create the `oai-events` data channel before making the SDP offer.
2. Set the local offer, POST the JSON above using the current Supabase token, and apply the returned text with `setRemoteDescription({type: "answer", sdp})`. If the app also has a legacy session cookie, include its CSRF header as other existing mutations do.
3. Wait for data-channel readiness. Send `response.create` if Mira should open the interview aloud. Subsequent user turns trigger responses through VAD. Play remote audio directly; do not additionally invoke file transcription/TTS or a second agent reply for each turn.
4. Handle `conversation.item.input_audio_transcription.completed`, `response.output_audio_transcript.done`, VAD events, playback events and errors. Transcription is fallible and may arrive asynchronously; preserve item IDs and speaker attribution, and do not assume a complete generated transcript was heard after an interruption.
5. Close the peer/data channel, stop every microphone track and detach audio on stop, logout, navigation or failure. Handle autoplay denial and allow return to typed chat.

New transcript persistence, evidence-linked workspace extraction, and reconnect/reconciliation are **not** implemented here. The endpoint reads existing memories but writes none. Existing authenticated `/v1/user/memories` is a separate save API; a future integration must preserve provenance, deduplicate events and confirm saves before Mira claims success. Starting the backend alone does not change the current recorder UI into a live conversation.

Before public rollout, add per-user spend/session-duration and creation-rate controls, integrate the product's session/entitlement rules, and test real microphone playback/interruption with the deployment's OpenAI account. Authentication alone is not a usage limit. Data-channel session updates are client-controlled; prompts must never be used to enforce privileged operations or paid access. No privileged tools are exposed in this implementation.

## Verification

`python3 -m pytest tests/test_realtime_routes.py -q` covers the multipart provider contract, languages, private context scoping/bounds, authentication, strict input validation, body limits, missing configuration, upstream failures, timeouts and client cleanup. Provider calls are mocked; these tests do not prove live model access, microphone permissions or browser audio playback.
