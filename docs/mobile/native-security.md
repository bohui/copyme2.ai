# Native identity, encrypted storage, and media boundary

## Implemented boundaries

- Supabase uses the deployment's existing HTTPS project and publishable key. Native session and PKCE verifier persistence use `expo-secure-store`, `WHEN_UNLOCKED_THIS_DEVICE_ONLY`, and an environment-specific namespace. No token belongs in SQLite, AsyncStorage, browser storage, diagnostics, or outbox content.
- SecureStore values are UTF-8 chunked below the historical 2 KiB platform constraint. Each rotation writes a recovery journal, new immutable generation chunks, then a small atomic head. Readers never assemble mixed generations. Interrupted rotation removes orphan generations. Logout removes the head before erasing chunks; a retained cleanup journal cannot resurrect a session. Locked-device/storage errors surface instead of silently creating a new guest.
- The SQLCipher key is 32 random bytes in SecureStore, separate from sessions and content. Database filenames are SHA-256 of deployment namespace and owner ID. A missing key for an existing file is a recoverable lock error, never a silent new key or reset.
- Before schema creation, the native adapter sets the key and requires a nonempty `PRAGMA cipher_version`, then probes the existing schema. Ordinary SQLite and Expo Go fail closed. A dedicated connection uses serialized `BEGIN IMMEDIATE`/commit/rollback transactions. This intentionally avoids Expo's exclusive-transaction helper: the installed SDK opens a new connection for that helper without propagating the SQLCipher key.
- Every row includes an owner predicate. Handles are revoked immediately on close/logout, including already-queued writes. JSON credential fields are rejected. Draft/cache values are bounded to 2 MiB, the outbox to 500 entries, and media to 20 bounded originals. Native logout erases rows, checkpoints WAL, closes the connection, removes its key, and deletes the database. Cleanup errors are surfaced. Fixture mode is explicit, synthetic, in-memory only; web private persistence fails closed.

## Identity transitions

`createAuthClient` returns a minimal Supabase-compatible session, token getter, subscriber, anonymous/password signup/login, OAuth linking/login, refresh, callback and logout methods. `onIdentityChange` must stop the old UI's jobs and close its vault before exposing the next owner. `onLogout` must stop recording, delete cached media, clear the owner vault, and unlink any implemented notifications. There is no push registration in this scaffold.

Existing-account login is distinct from anonymous account linking. The injected transfer adapter must quiesce pending turns/uploads/draft jobs/previews and register the existing conversation before authentication replaces the guest. The same random capability, environment, guest identity/session and server expiry are retained in SecureStore across uncertain preparation. OAuth cancellation preserves that recovery. The UI must display the destination account and explicitly call `confirmTransfer`; attach retries use the same capability. Only a successful attach plus the adapter's authoritative history reconciliation erases recovery. No unsupported automatic merge or client-only guest restore is implemented. Expired transfer recovery needs a backend-authorized restart path before that option can be offered.

OAuth uses the system authentication browser and Supabase PKCE. The callback is checked against the exact configured scheme/host/path, a persisted random flow nonce, environment and expiry. Fragments, unexpected callbacks, duplicate code parameters and callback reuse are rejected. The flow is consumed before the code exchange. A failed/uncertain exchange requires restarting login, with the guest recovery retained. Refresh is foreground-controlled by the app; no background auth promise is made.

## Media and genuine limits

The native foreground recorder requests the microphone only on Record. It checks free disk space, requests mono AAC/M4A, caps recording at 60 seconds and accepts at most 1 MiB. Stop seals the immutable base64 original into the encrypted vault, commits `media.index` and the original in one transaction, removes the temporary recording, then reports saved. Reopening a recorder discovers indexed clips for that owner and restores the first saved clip for playback/review. Explicit discard atomically removes both original and index membership. Additional saved clips can be enumerated using `listSavedClips`.

The recorder must create a temporary app-private plaintext file while native hardware records. Process kill before sealing is **not recoverable** in this implementation, and temporary leftovers are possible. The recording UI must not claim crash-safe local save before the sealed state. `clearNativeMediaTemporaryFiles` removes only installed-SDK recorder and Memoir playback cache filenames; invoke it after stopping record/playback during logout. This is a release blocker for production-grade encrypted recording retention, not a claim of complete MOB-021/MOB-022 delivery. Background/lock transitions request stop and sealing but the OS can interrupt that work.

Playback decrypts a bounded original into an app-private temporary file, removed on stop/dispose/logout. Photo selection uses the system scoped picker and stores a bounded encrypted original; only a confirmed app-cache copy can be removed afterward, never the user's library original. `exif:false` suppresses returning metadata to JavaScript; it does **not** prove stripping metadata from original bytes. Server derivative stripping and verified private upload are still required.

`transcribeClip` is an explicitly consented, owner-bound, bounded `/story/transcriptions` compatibility seam only. It retains immutable original transcript text, clip ID, editable revision and unverified provenance. Microphone permission does not substitute for AI-processing consent. No resumable/binary upload, signed-URL refresh, verified asset finalization, background transfer, or production media upload is fabricated. These remain backend/native acceptance gates.

## Checks run and device-only gates

Offline Node tests exercise chunk rotation/interruption/tombstones, callback origin/nonce/reuse checks, preparation-before-login, cancelled OAuth, capability cleanup, SQLCipher absence, owner isolation/revoked handles, token rejection, parameter binding, real SQLite rollback of media+index, media recovery, permission denial, cancel-without-upload, transcription consent and bounds. The SQLite fixture returns a simulated cipher-version capability; it is not proof of on-device encryption. TypeScript and ESLint checks apply to the implementation. No real credentials, login, model call or microphone prompt is used by these tests.

Before release, run on physical iPhone and Android development builds:

1. Confirm SQLCipher header unreadability, wrong-key rejection, native transaction rollback and secure-delete/WAL behavior; force-kill at each acknowledged draft/outbox/media transition
2. Verify locked-device SecureStore errors, large real Supabase sessions, token rotation, relaunch, key loss, uninstall/reinstall and backup/restore; ensure backup rules exclude private databases/cache and secure credentials
3. Exercise foreground refresh, password and Google/Apple login/linking, custom-scheme and verified-app-link callbacks, denied/cancelled login, process-killed OAuth, nonce mismatch, expired transfer and repeated attach against staging
4. Verify two-account logout/switch including failed cleanup, unsent-work prompts, app-cache/media removal and prevention of old asynchronous response/outbox rendering
5. Test microphone denial, low storage, Bluetooth/headphones/route interruptions, maximum duration, background/screen lock, force-quit, playback cleanup, Chinese/English transcript review and accessibility
6. Add and verify binary/resumable asset upload and crash-safe encrypted media retention before claiming production offline-media support

## Official references

- [Expo SDK57 SQLite and SQLCipher](https://docs.expo.dev/versions/v57.0.0/sdk/sqlite/)
- [Expo SecureStore](https://docs.expo.dev/versions/latest/sdk/securestore/), currently SDK57 documentation
- [Expo SDK57 Audio](https://docs.expo.dev/versions/v57.0.0/sdk/audio/)
- [Supabase native deep linking](https://supabase.com/docs/guides/auth/native-mobile-deep-linking)

The implementation also follows mobile specification sections 7, 9 and 10; platform verification remains distinct from deterministic fixture evidence.

## Interrupted cleanup and playback regression hardening

Logout cleanup keeps handles revoked while retrying failed deletion, checkpoint, connection-close, key-removal and database-file stages. Successfully completed stages are not repeated against closed connections. Native key and file deletion have separate retry checkpoints; explicit native already-closed responses confirm an uncertain close. Concurrent clear requests serialize, and a previously closed native vault can still be cryptographically erased. These are in-process retries, not proof of crash-safe logout recovery.

Stop, background, route unmount and owner replacement invalidate playback generations before asynchronous native audio-mode setup can finish. Guards run again before plaintext file creation/write and player creation/start. Deterministic tests now exercise the actual reply hook and native recorder adapter with deferred native setup; they do not access a device.

Ordinary recorder-route unmount attempts to seal an active bounded clip into its owner's vault before removing the temporary file. A stop already sealing retains its original rather than treating route unmount as explicit discard. Explicit Cancel still discards. A revoked vault rejects sealing during logout, after which temporary-file cleanup and native release still run. Cleanup errors on an unmounted route cannot be presented there and do not establish saved status. Abrupt process kill before sealing remains the separate device/recovery release gate described above.
