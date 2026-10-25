# LAN speech providers

This setup keeps transcription in Groq and sends synthesis to the CosyVoice
server running on the second Mac mini at `192.168.0.50:50001`.

Create a Groq key in the [Groq console](https://console.groq.com/) under
**API Keys**. `COSYVOICE_API_KEY` is the key accepted by your local CosyVoice
server. Keep both values server-side.

Add this block to `.env`:

```dotenv
GROQ_API_KEY=
COSYVOICE_API_KEY=
COSYVOICE_BASE_URL=http://192.168.0.50:50001
# Each account must confirm its identity and explicitly opt in before capture.
MEMOIR_ORIGINAL_RECORDINGS=1
MEMORY_SPARK_STT_MODEL=whisper-large-v3-turbo
MEMORY_SPARK_TTS_MODEL=cosyvoice-v3-flash
MEMORY_SPARK_TTS_VOICE_EN_AU='英文女'
MEMORY_SPARK_TTS_VOICE_ZH_CN='中文女'
```

Enable private recording storage and the database rollout once, then start or
refresh the local stack (including STT and TTS):

```bash
make recording-retention-enable
make up
```

The normal Compose configuration passes the speech settings and retention flag
to the API. The speech override is optional for Compose workflows.

The API calls authenticated `POST /tts` with the server's `text`, `voice`, and
`speed` JSON fields and receives a mono 16-bit WAV file. Use the voice names
returned by authenticated `GET /voices`; this server currently exposes `英文女`
and `中文女`, rather than `longwan_v3`. The server serializes synthesis requests
and may return a busy response; the client treats that as retryable.

Browser microphone transcription uses the same backend route that preserves the
original audio. Set `MEMOIR_ORIGINAL_RECORDINGS=1`, provide
`MEMOIR_PUBLICATION_DATABASE_URL` (the Makefile derives it from
`SUPABASE_DB_URL` when unset), and link the browser session to a recoverable
identity: a confirmed email or phone on a non-anonymous Supabase account.
Select the microphone to review two separate choices: private original-audio
retention and AI transcription through Groq. Both must be accepted. Consent is
stored by the backend with its notice version, locale and revision; editing the
profile or granting browser microphone permission cannot substitute for it.

Open **Voice privacy** beside the composer to withdraw consent. Withdrawal
waits for admitted reads/transcription to finish, then blocks subsequent audio
access and STT. It does not claim to erase saved audio or transcript text; the
existing recording deletion API remains available to the owner after withdrawal.

`make recording-retention-enable` creates or verifies the private
`memoir-original-recordings` bucket, applies only the consent table and related
functions from the consolidated baseline, and enables the selected database's
rollout. It does not reset user data or grant consent for anyone. The baseline's
rollout remains off for new installations until explicitly enabled. Recording
objects use a backend-only Supabase credential after ownership/consent checks;
browser tokens cannot list, sign, overwrite or directly retrieve them.

Groq handles English and Mandarin transcription. A Groq failure keeps the
original available for retry; Memoir does not forward it to another ASR provider.
DashScope credentials do not add Qwen to the Groq-only consent scope.
