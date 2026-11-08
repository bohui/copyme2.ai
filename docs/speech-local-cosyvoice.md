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

Prepare private recording storage once, then start or refresh the local stack:

```bash
make recording-retention-setup
make up
```

The normal Compose configuration passes the speech settings and
`MEMOIR_ORIGINAL_RECORDINGS` from `.env` to the API. Set it to `1` to allow
voice input and transcription or `0` to pause them, then run `make up`.
Saved audio stays retrievable with current consent and source permissions.
The speech override is optional for Compose workflows.

The API calls authenticated `POST /tts` with the server's `text`, `voice`, and
`speed` JSON fields and receives a mono 16-bit WAV file. Use the voice names
returned by authenticated `GET /voices`; this server currently exposes `英文女`
and `中文女`, rather than `longwan_v3`. The server serializes synthesis requests
and may return a busy response; the client treats that as retryable.

Guests can choose **Continue without signing in** when opening browser voice
conversation or dictation. Memoir sends those clips to Groq and keeps only the
text submitted in the guest conversation.

To save original audio, provide `MEMOIR_PUBLICATION_DATABASE_URL` (the Makefile
derives it from `SUPABASE_DB_URL` when unset) and connect a confirmed email or
phone to the Supabase account. Select the microphone and approve both private
recording storage and AI transcription through Groq. Consent is
stored by the backend with its notice version, locale and revision; editing the
profile or granting browser microphone permission cannot substitute for it.

Open **Voice privacy** beside the composer to withdraw consent. Withdrawal
waits for admitted reads/transcription to finish, then blocks subsequent audio
access and STT. It does not claim to erase saved audio or transcript text; the
existing recording deletion API remains available to the owner after withdrawal.

`make recording-retention-setup` creates or verifies the private
`memoir-original-recordings` bucket and applies the recording consent table and
related functions from the consolidated baseline. Rerun setup once on existing
development databases to update the recording functions in place and preserve
stored consent and recordings. The backend uses a server-only Supabase
credential to access recording objects after checking ownership and consent.

Groq handles English and Mandarin transcription. A Groq failure keeps the
original available for retry; Memoir does not forward it to another ASR provider.
DashScope credentials do not add Qwen to the Groq-only consent scope.
