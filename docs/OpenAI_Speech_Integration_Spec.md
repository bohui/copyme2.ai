# OpenAI STT and TTS for CopyMe2 Memoir

Status: reviewable draft; testing-seam confirmation and issue-tracker setup pending.

## Problem Statement

Storytellers need to answer Memory Spark questions in their own voice and hear questions read clearly, especially when typing or reading is difficult. The current browser dictation and read-aloud depend on browser capabilities. The connected five-round story journey accepts text, while the recorder fallback uses legacy project upload routes. This does not provide one dependable, source-linked voice journey for anonymous and signed-in storytellers.

## Solution

Add OpenAI transcription and spoken questions to the existing Memoir journey. A storyteller records an answer, reviews and corrects its transcript, and explicitly sends it through the existing story or interview flow. Original audio remains private and linked to the submitted text. Questions remain visible and can be played on demand in a warm, patient voice. Typed input continues to work when speech is unavailable.

Use `gpt-4o-mini-transcribe` by default, offer an explicit higher-quality retry with `gpt-4o-transcribe`, and synthesize speech with `gpt-4o-mini-tts`. Keep provider configuration behind small STT and TTS interfaces. Cache synthesized audio without sharing private questions across users.

## User Stories

1. As a storyteller, I want to record an answer, so that I can share memories without typing.
2. As a storyteller, I want to stop recording clearly, so that I control what is captured.
3. As a storyteller, I want to review my recording, so that I can decide whether to use it.
4. As a storyteller, I want to discard or retake an answer, so that accidental recordings do not enter my memoir.
5. As a storyteller, I want to see transcription progress, so that I know whether to wait or retry.
6. As a storyteller, I want an editable transcript before sending, so that recognition mistakes do not become my story.
7. As a storyteller, I want Chinese names and family terms preserved, so that my memories retain their meaning.
8. As a bilingual storyteller, I want mixed Chinese and English transcribed without automatic translation, so that my original expression is retained.
9. As a storyteller, I want to request a higher-quality transcription, so that a difficult recording can be reconsidered.
10. As a storyteller, I want manual transcription when my dialect is poorly recognized, so that I can still contribute.
11. As a storyteller, I want original audio retained under my retention settings, so that my family can hear my own voice.
12. As an authorized helper, I want corrections attributed to me, so that my edits are distinguishable from the storyteller's words.
13. As a storyteller, I want old transcript versions preserved, so that corrections do not invalidate existing evidence links.
14. As a storyteller, I want to hear the current question on demand, so that I can participate without reading it.
15. As a storyteller, I want slow, clear, warm speech, so that the interviewer is comfortable to follow.
16. As a storyteller, I want playback controls, so that I can pause, stop, and replay questions.
17. As a storyteller, I want playback stopped before recording starts, so that the question is not captured as my answer.
18. As a storyteller, I want an AI-voice disclosure, so that I understand who is speaking.
19. As a storyteller, I want text available when playback fails, so that I can continue my interview.
20. As a storyteller, I want typed input when microphone access is denied, so that device permissions do not block my progress.
21. As an anonymous storyteller, I want voice support during the five free rounds, so that I can try the actual experience before linking an identity.
22. As a storyteller, I want recordings to stay attached after identity linking, so that my first memories are preserved.
23. As a storyteller, I want transcription retries and question replays excluded from primary-session counts, so that technical problems do not consume my allowance.
24. As a storyteller, I want remaining recording capacity shown before recording, so that an answer is not silently truncated.
25. As a storyteller, I want interrupted uploads to distinguish saved material from local buffers, so that I know what can be recovered.
26. As a storyteller, I want private audio accessible only to authorized people, so that my memories remain private.
27. As a storyteller, I want deletion and access changes applied to generated speech as well as originals, so that derived audio respects my choices.
28. As an operator, I want repeated requests to reuse successful work, so that double clicks and retries do not create duplicate answers or unnecessary speech costs.
29. As an operator, I want speech failures and usage recorded without transcript content, so that I can operate the service without exposing family memories.
30. As an operator, I want deployment-specific speech configuration, so that speech processing follows existing regional restrictions.
31. As an operator, I want representative Mandarin and English evaluation, so that the advertised voice experience reflects observed quality.

## Implementation Decisions

- **Integration target:** implement the connected Supabase story journey and authenticated agent interview. Preserve the five-round, identity-linking, and payment behavior. Do not implement speech only in the retiring in-memory specification routes. Product vocabulary remains Storyteller, MemorySession, SourceVersion, EvidenceSpan, Memory, and Chapter; a free story round is the current application's entry point, not a new speech entitlement.
- **Provider boundary:** introduce small speech-to-text and text-to-speech interfaces with OpenAI implementations and injectable test doubles. Keep model IDs, voice, timeouts, and speech instructions in server configuration. Retain the existing interviewer and chapter-writing runtime.
- **Credential boundary:** use a server-only OpenAI API key. Speech calls originate from the authorized backend processing boundary, not the browser or a model-issued tool command. Missing configuration produces an explicit unavailable response while text continues to work.
- **Capture:** use MediaRecorder with runtime MIME negotiation, visible stop/discard controls, and microphone cleanup on stop, cancellation, navigation, and failure. Replace implicit browser SpeechRecognition as the default. Store the editable transcript in application state so rendering cannot erase it.
- **Ingestion:** authenticate anonymous and linked users through existing Supabase identity verification. Create owner-scoped upload records; validate actual media type, size, checksum, and decoded duration before provider work. Preserve immutable originals in private storage. Resume through ordered upload manifests; assemble and decode complete media before transcription. Reuse ingestion utilities where suitable without relying on legacy in-memory persistence.
- **Provider size limits:** normalize recordings and, where necessary, split decoded audio into independently playable bounded requests while retaining an original-time map. Never send arbitrary MediaRecorder fragments as complete recordings. The current OpenAI file-transcription limit is 25 MB per request; this is distinct from the product's proposed 100 MB turn upload limit. [OpenAI file transcription](https://developers.openai.com/api/docs/guides/speech-to-text)
- **STT result contract:** return immutable transcript identity/version, recording reference, original-language text, transcription method, model, and available language/timing metadata. Missing confidence is null. Default mini transcription does not establish precise word timestamps; use recording/chunk-level playback bounds with explicit granularity, and never invent word alignment. This narrows the older generic ASR segment requirement for this provider. [OpenAI timestamps](https://developers.openai.com/api/docs/guides/speech-to-text#timestamps)
- **Review and correction:** transcription does not automatically submit an answer or advance a round. Corrections create a new SourceVersion with actor and method attribution. Preserve normalized text hashes and Unicode code-point evidence offsets. Existing approved prose is not overwritten; dependencies become stale or require review under existing product rules.
- **Fallback:** expose an explicit better-transcription action after a usable or problematic first attempt; invoke `gpt-4o-transcribe` once for that operation. Preserve both versions for review. Never run both models for every recording or infer calibrated confidence from names that merely look unfamiliar. Manual correction remains available.
- **HTTP contract:** add authenticated operations under the canonical Memoir namespace for upload creation/finalization, transcription submission/status, transcript correction, and question-speech creation/retrieval. Accept opaque owned identifiers, expected transcript versions, and idempotency keys; do not accept arbitrary remote audio URLs or client-specified storage owners. Extend existing answer submission with optional validated recording and SourceVersion references alongside confirmed text. Keep typed-only submissions compatible.
- **Job contract:** accepted processing returns 202 with an operation ID and status URL. Persist queued/running/succeeded/failed status and safe error codes; successful results survive reconnects. Enforce uniqueness for owner, source version, operation type, and idempotency key; conflicting payload reuse returns a conflict. Bound retry attempts and timeout recovery. Do not promise exactly-once provider billing after an ambiguous provider response.
- **Persistence:** add narrowly scoped Supabase records for speech sources, transcript versions, operations, and speech assets/cache references. Enforce RLS, immutable version ownership, and unique idempotency keys. Store binary media in private Storage, link accepted source references through the existing memory storage boundary, and keep authoritative usage counters outside user-editable profile JSON. Do not revive the retired application-wide JSONB state store.
- **TTS:** synthesize visible interviewer questions and short interview prompts on explicit playback. Start with a configurable built-in voice and instructions to speak slowly, warmly, and clearly with natural pauses. Show that the voice is AI-generated and retain the displayed text. Mandarin voice selection requires listening review because current voices are optimized for English. [OpenAI text to speech](https://developers.openai.com/api/docs/guides/text-to-speech)
- **Playback:** provide play/pause/stop/replay, prevent overlapping audio, cancel stale playback after navigation or question changes, and stop playback before microphone capture. No autoplay with sound. Use accessible controls and status announcements.
- **Caching:** key successful speech assets by exact normalized text, language, provider/model, voice, instruction version, and output format. Share only explicitly public fixed prompts. Scope personalized speech to the authorized owner/project and deployment region. Authorize every retrieval, coalesce concurrent identical requests, avoid caching failures, and invalidate or delete derivatives when source permissions or retention require it.
- **Budgets:** preserve the existing 15-minute accepted-audio session rule. Valid retakes count toward technical audio capacity; provider reprocessing of the same accepted source does not debit it again. Failed validation does not consume accepted duration. Replays, correction, and transcription alone never complete or consume a primary session. The pasted three-minute TTS example is a cost scenario, not a new agreed user entitlement.
- **Errors and operations:** distinguish denied access, unsupported/corrupt media, exceeded limits, unavailable configuration, provider throttling, timeout, and transcription failure. Preserve saved recordings and editable text. Record operation/model/status, request identifiers, duration, cache hits, and available usage; keep private text and audio out of routine logs. Provider-cost estimates are separate from user allowances.
- **Regional policy:** apply existing deployment-region and processor permissions before sending audio or private question text. Do not enable OpenAI where deployment policy disallows it or silently reroute data across regions. Text/manual workflows remain usable when speech is disabled.

## Testing Decisions

- **Proposed primary seam, awaiting user confirmation:** exercise the authenticated Memoir HTTP API with the existing FastAPI TestClient/application-factory pattern. Fake OpenAI and Supabase at their external boundaries; assert responses, saved artifacts, authorization, and resulting story state rather than private helper calls.
- **Prior art:** existing story-flow tests cover anonymous rounds, identity linking, and chapter gates using fake Supabase user storage. Agent-route/storage tests cover authenticated user data and attachments. Existing browser smoke and end-to-end scripts provide UI verification patterns. Extend these patterns rather than inventing a new testing framework.
- **API scenarios:** audio to reviewed transcript to one accepted answer; typed compatibility; corrected immutable versions; source provenance; higher-quality retry; duplicate and concurrent operations; restart/reconnect recovery; corrupt and over-limit files; provider timeout/throttle/malformed output; no fabricated timestamps/confidence; and unchanged five-round/paid access behavior.
- **Privacy and usage scenarios:** cross-user identifiers fail before provider dispatch; anonymous-to-linked identity retains ownership; cache access does not leak personalized text/audio; deletion removes accessible derivatives; invalid inputs and retries obey duration accounting; user-editable profiles cannot grant speech budget; region-disabled speech performs no external request.
- **Browser scenarios:** recording start/stop/discard, denied microphone permission, unsupported capture with file/typed alternatives, transcript preservation across renders, explicit send, playback cancellation, accessible controls, and recovery messaging. Use deterministic media/provider fixtures for automation.
- **Real-device acceptance:** verify iPhone Safari, Android Chrome, and supported WeChat webviews for recording formats, interruptions, screen lock, upload retry, and playback. State actual recoverability; never promise preservation of bytes not received.
- **Quality acceptance:** evaluate consented or synthetic samples covering older speakers, Mandarin, English, mixed language, Shanghai/Sichuan/Cantonese-influenced Mandarin, names, historical place names, 大伯, 二舅, 姥姥, 粮票, 知青, and 下乡. Native-speaker review must assess transcription meaning and TTS clarity/pacing before Mandarin release. No universal dialect-support claim follows from passing API tests.
- **Live integration smoke:** separately verify configured model access, actual audio decoding, transcription, and playable synthesis with a small non-private fixture. Keep paid network calls out of ordinary automated tests. Record observed latency and cost rather than asserting the pasted estimates as guarantees.

## Out of Scope

- Realtime speech-to-speech, continuous listening, barge-in, and live partial transcription.
- Voice cloning, custom voices, emotional imitation, and full-book audiobook generation.
- Automatic speaker identity, diarization, exact word alignment, and guaranteed regional dialect support.
- A second speech vendor, self-hosted Whisper, or automatic cross-region provider routing.
- Changes to package prices, free-round counts, payment gates, or the interviewer/writing model.
- Broad legacy-route retirement, a replacement workflow platform, or unrelated repository cleanup.

## Further Notes

This spec synthesizes the supplied speech proposal and the current working tree as inspected on 2026-09-25. The product specification and SaaS architecture remain authoritative for consent, visibility, source provenance, retention, accessibility, and session accounting; the current connected Supabase journey determines the implementation target. No separate ADR or glossary file was found in the repository search.

The pasted per-session prices are planning estimates, not verified commitments. Actual speech costs, account/model availability, and language quality must be measured during integration. Preserve the requested model choices unless a later explicit decision changes them.

The Git remote identifies `bohui/copyme2.ai` as the likely publication repository. Its inspected issue labels contain only default GitHub labels; `ready-for-agent` is absent, and no project issue-tracker/triage configuration was found. Run `/setup-matt-pocock-skills` to establish that configuration before publication, as required by the invoked to-spec skill. The testing seam also awaits the skill-required user check. No issue has been published and no application implementation is included in this task.
