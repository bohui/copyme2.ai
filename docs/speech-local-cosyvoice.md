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
# Opt in only after storage, identity, and consent are configured. This retains
# each original recording in private storage before sending it to STT.
MEMOIR_ORIGINAL_RECORDINGS=1
MEMORY_SPARK_STT_MODEL=whisper-large-v3-turbo
MEMORY_SPARK_TTS_MODEL=cosyvoice-v3-flash
MEMORY_SPARK_TTS_VOICE_EN_AU=longwan_v3
MEMORY_SPARK_TTS_VOICE_ZH_CN=longwan_v3
```

Start the API with the speech override:

```bash
docker compose -f compose.yml -f compose.speech-local.yml up --build
```

The API calls authenticated `POST /tts` with the server's `text`, `voice`, and
`speed` JSON fields and receives a mono 16-bit WAV file. If your local server
exposes different voice names, set the two `MEMORY_SPARK_TTS_VOICE_*` variables
to those names. The server serializes synthesis requests and may return a busy
response; the client treats that as retryable.

Browser microphone transcription uses the same backend route that preserves the
original audio. Set `MEMOIR_ORIGINAL_RECORDINGS=1`, provide
`MEMOIR_PUBLICATION_DATABASE_URL` (the Makefile derives it from
`SUPABASE_DB_URL` when unset), and link the browser session to a recoverable
identity. Anonymous sessions are intentionally rejected before STT so raw voice
is never retained without an approved identity and consent.

Qwen3-ASR-Flash remains an optional Mandarin fallback. Enable it by adding
`DASHSCOPE_API_KEY`, `DASHSCOPE_WORKSPACE_ID`, and `DASHSCOPE_REGION` to `.env`.
