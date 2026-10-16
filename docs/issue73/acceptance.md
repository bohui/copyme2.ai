# Issue 73: original recordings — draft acceptance record

**Not ready to enable or merge.** This branch implements the recording pipeline behind two disabled gates. It does not establish an approved retention-consent authority or deployed Storage acceptance. Local tests with controlled external transports do not constitute full feature acceptance.

Specification: https://github.com/bohui/copyme2.ai/issues/73 (full body and timeline read on 16 October 2026). Initial issue had no assignee, comments, linked PR or coding owner; the only open repository PR was unrelated #72. Initial base: `a6c1c9055119b90a21b04bb09b99f4d5545379f2`. Task-only work was subsequently rebased onto main `971dd672c407ca508b8cf62f913d96dbbb9b6ba0`; the newly added repository retention specification was also read. Worktree: `/workspace/issue73`; branch: `agent/issue73-original-recordings`. The original checkout was preserved. The final immutable commit is recorded in the draft PR and handoff.

## Resulting behavior

- `POST /api/v1/memoir/story/transcriptions` accepts the existing complete base64 payload, an optional `upload_idempotency_key`, and optional owned `project_id`; alternatively it accepts an owned `recording_id`. Payload and reference together are rejected. Success retains text/source fields and adds a recording descriptor.
- A trusted backend reserves metadata, validates the actual media, uploads to an immutable backend-generated object identity, reads back identical bytes, and attests finalization. Object existence never promotes a pending row. Only ready objects reach STT. The existing transactional server DSN performs attestation; user JWTs cannot call that operation or forge metadata.
- Request JSON is bounded before buffering/decoding. Originals are limited to 10 MiB and 300 decoded seconds, with a 300-second combined turn ceiling, validated using ffprobe/ffmpeg. Native capture remains at its existing 1 MiB/60-second limits. Generated speech is separate. Temporary decoder files are removed; the object store is the only original-audio persistence boundary.
- Metadata, lookup by upload key, exact-original content, and deletion operations live under `/api/v1/memoir/story/recordings`. Canonical HTTP responses expose opaque IDs and API paths; no object paths or signed/public Storage URLs. Binary reads verify SHA-256/length, use private/no-store caching, and hold a current database policy guard through ASGI publication.
- STT dispatch rechecks policy under database locks. A storage/finalization failure returns a pending identity and no saved acknowledgement/provider dispatch. An STT failure/empty result after storage returns a durable ID with saved-audio and failed-transcription stages. Successful ASR is persisted separately from edited narrator text and reused on retries. An ambiguous provider result does not promise exactly-once billing.
- Ordered `recording_ids` are attached in the existing source acceptance transaction in both canonical execution modes. Ownership, project, readiness, duplicate IDs and attachment reuse are checked. Replay includes ordered recording identity. A source-accepted receipt therefore implies committed associations, independent of reply generation and commercial round completion.
- Source detail, receipts and history restore bounded ordered readable descriptors. Pending-turn recovery separately restores the immutable accepted recording IDs, including audio-only deletions, so a failed reply can be retried without resurrecting audio. Source correction retains original provenance; withdrawal fences retrieval. Audio-only deletion preserves accepted text. Draft-only discard cannot delete an already accepted original.
- Exact-object cleanup receipts carry the write revision captured before DELETE. SQL completes cleanup only if that revision is still current and every admitted writer has stopped. A delayed response cannot acknowledge bytes written after physical removal; failed compensation remains pending and inaccessible until a fresh successful DELETE.
- Browser voice and dictation carry references; appended clips retain order through editing, typed additions, retry and cancellation. Owner/project-scoped session snapshots restore reviewed text, descriptors and uncertain ready uploads without caching binary audio. An incomplete upload whose bytes were lost is not presented as preserved. Native clips use stable capture UUIDs for upload retry, retain separate local/backend identities in the encrypted vault, and include references in the existing immutable turn outbox even after text edits.
- The migration adds application metadata/RPCs only. It does **not** provision a bucket or change Storage policies/access. `MEMOIR_ORIGINAL_RECORDINGS=0`, the database rollout row is false, and `original_recording_authorized(...)` returns false. Anonymous authentication, a microphone permission or the native consent checkbox cannot bypass that authority.

## Acceptance matrix

“Local” below means observed through real disposable PostgreSQL and/or bounded client tests with controlled Storage/STT transports. It does not mean deployed/provider/device acceptance. Numbers refer to the issue's user stories.

| Stories | Requirement | Implementation and local evidence | Remaining gate |
|---|---|---|---|
| 1, 5, 30, 34 | Preserve exact original, verified metadata/checksum, authenticated fresh-client readback | HTTP tests generate valid WebM/Opus, M4A/AAC and WAV; compare identical bytes after a fresh app/storage client; inspect persisted ASR and edited source separately | Actual private Storage HTTP and real recorder formats |
| 2 | Automatic browser voice turns | Existing voice-controls browser harness asserts saved IDs reach the turn snapshot and clear after acceptance | Actual microphone/device recording |
| 3, 7, 8, 9, 10 | Dictation review, ordered clips, edits and typed additions | Browser assertions cover appended clips, edited text and ordered IDs; API/SQL tests read two ordered originals, source and raw ASR | Word/time alignment deliberately absent; no exact-verbatim claim for edits |
| 4, 17 | Native upload versus local identity/status | Separate `clipId`/`recordingId`, encrypted recovery mapping, local/backend notices and outbox fields; mobile test/type/UI/integration checks | Native binary and real iOS/Android devices |
| 6, 33 | Correct canonical source/turn identity | Existing authoritative conversation mapping, atomic source-recording links, unique recording attachment, both execution modes | No second conversation ledger introduced |
| 11, 12 | STT failure/empty text preserves original | HTTP tests return a durable saved ID, retry by reference, and leave narrator/round counts unchanged | Actual provider timeout/ambiguous billing behavior |
| 13, 31 | Storage, readback and finalization failures | Controlled object failures and a real SQL finalization-failure trigger prove pending identity, no false readiness and no STT dispatch; same-key recovery works | Actual interrupted Storage writes |
| 14 | Mira failure preserves accepted contribution | HTTP provider-failure test checks source and attached original survive while no recall round completes | Actual provider outage evidence |
| 15 | Idempotent upload/turn and immutable ordered list | SQL/API retries reuse identity/ASR/source/round; changed bytes/order conflict; SQL association-failure trigger proves transaction rollback; deleted-audio pending turns replay the original IDs in both execution modes and permit the next turn | Exactly-once upstream billing is not claimed |
| 16 | Reload references | Fresh app, receipt/history/source API reads, browser pending-turn/review cache recovery, native encrypted outbox; SQL preserves accepted order separately from filtered playback descriptors | Cross-device UI review remains unobserved |
| 18, 19, 20 | Stop/discard/retake and private drafts | No upload on pre-upload cancellation; draft metadata never accepts a source; append cancellation preserves earlier clips; draft-only discard tombstones and retries exact-object deletion | Actual Storage access revocation and native cancellation on device |
| 21, 23 | Linking/transfer and account isolation | Native principal/project guards, browser scoped recovery, SQL transfer of recording/link ownership in the existing transaction; previous owner loses metadata | Storage-side transfer revocation; approved guest-retention authority remains absent |
| 22, 29 | Recoverable identity, current consent/policy and notices | Default-deny hook, disabled rollout, anonymous rejection, safe stage notices, SQL role restrictions and API outsider/anonymous tests | **Blocked:** approved identity + purpose-specific retention/AI consent integration is missing |
| 24 | Withdrawal/deletion | API source-withdrawal race blocks bytes before ASGI send; consent-authority revocation blocks reads/STT; audio deletion leaves text; delayed DELETE receipt plus late POST and failed compensation remain pending; project/account deletion leaves inaccessible cleanup tombstones | **Partial:** owner DELETE retries cleanup; project/account orphan tombstones need an approved cleanup transport/executor before activation |
| 25, 26 | Typed/older transcript compatibility | Existing text/canonical/source-recovery tests; absent client schema fields remain compatible; empty recording lists mean unavailable originals | No backfill or synthesized replacement |
| 27 | English/Chinese/mixed content | Binary preservation independent of language; controlled Chinese ASR is distinguishable from edited English/typed text | Real language/provider/device observations not run |
| 28 | Bad/oversized/duration-bounded inputs | Malformed/empty/corrupt/mislabeled bytes, decoded byte/duration bounds, encoded HTTP request bound and safe validation responses | Container decoder image build not run |
| 32 | Safe diagnostics | No added audio/transcript logging; errors are fixed safe codes and IDs; validation excludes Pydantic input/context (which can contain base64) | No live operational log audit |

## Verification and repeatable commands

Synthetic fixtures only. No customer recordings, configured shared database, production migration, deployment, merge or paid provider call was used. The test fixture starts task-owned PostgreSQL containers, uses actual `authenticated`/`anon` roles and separate connections, verifies loopback-only publication and stops each container. It does not use the single-user RLS-bypassing fallback. The HTTP suite uses the existing application, real SQL and real psycopg attestation/publication; only authentication exchange, object transport and model/STT are controlled.

TDD observations: the initial API/media tests produced 13 failures against the old implementation; the new shared/native contract tests produced 3 failures; the web ordered-reference regression failed before implementation. The independent runtime review of `804a5b19` returned two additional defects; the follow-up reproduced three cleanup HTTP failures, six recovery HTTP failures and three SQL failures before fixing them. Final observed results: **108 feature tests**, **103 affected canonical/API regression tests**, **21 web state tests**, the browser voice-controls scenario, and the complete mobile check (**92 unit/domain + 68 UI + 23 integration tests**, type checks, lint, 48-operation OpenAPI snapshot and native configuration introspection) passed. The migration-ledger checks include an additional pinned upgrade from main `45ea639` after its new version collided with the task migration; originals now use unapplied version **202610160005**. Exact commands, migration-history results and source hashes are captured in `verification.json`; the confirmed review findings and regression fixes are detailed in `review-fixes.md`.

```bash
MEMOIR_TEST_POSTGRES_BACKEND=docker python -m pytest \
  tests/test_original_recordings.py \
  tests/test_original_recordings_postgres.py \
  tests/test_original_recordings_http.py -q

MEMOIR_TEST_POSTGRES_BACKEND=docker python -m pytest \
  tests/test_lifetime_memory_runtime.py tests/test_canonical_guest_conversation.py \
  tests/test_conversation_recovery_api.py tests/test_speech_integration.py \
  tests/test_speech.py tests/test_canonical_only_conversation.py -q

MEMOIR_TEST_POSTGRES_BACKEND=docker python -m pytest \
  tests/test_consolidated_migration_upgrade.py -k migration_history -q

node --test tests/js/interview-photo-turns.test.mjs
python tests/browser_voice_controls.py
npm run check:mobile
python scripts/check_mobile_openapi.py
```

The execution environment used the preinstalled Python environment at `/workspace/copyme2.ai/.venv/bin/python`. npm caches and downloaded Playwright binaries were placed under `/tmp`; the browser command used `PLAYWRIGHT_BROWSERS_PATH=/tmp/issue73-playwright`. All five real PostgreSQL migration-ledger histories passed; Supabase CLI runner evidence remains unobserved. The new Containerfile dependency supplies ffmpeg/ffprobe, but no application container image was built or deployed.

The older private-photo suite has three failures in `test_final_conversation_commit_rejects_invalidated_saved_collector[source|photo|newer_turn]`. Each calls the retired `commit_user_agent_turn` and expects a later stale-publication error; current canonical admission rejects it earlier with `canonical execution required`. These same three failures reproduce on base `a6c1c90` with only the Docker fixture transport copied in: **34 pass / 3 fail on both base and this branch**. They are not new recording regressions and are not waived as release evidence.

## Explicit blockers for independent cloud review

1. **Approved authority is absent.** The canonical Supabase journey has no verified, approved recoverable-contact + purpose-specific recording-retention/AI-consent authority. The migration's hook intentionally returns false for everyone. An approved integration must verify actual durable authority and coordinate withdrawal with the existing project/policy locks. Do not replace it with `not is_anonymous`, a user-editable profile field or a browser checkbox. The fixture-only synthetic authority is not an implementation of product consent.
2. **Private Storage is not provisioned or verified here.** This environment has no configured Supabase URL/public key, server database DSN or provider credential. No Storage policies/access were changed. Before activation, separately authorize and verify the private bucket and pending-write/read/finalization policy, direct listing/get/sign/overwrite denial, source withdrawal, transfer revocation, and exact-object deletion using bounded synthetic audio over actual Storage HTTP. A successful mock transport is insufficient.
3. **Orphan/ambiguous-writer cleanup is incomplete.** Explicit owner DELETE retries and fences immediately, including cleanup failure. Source/project/account deletion retains inaccessible tombstones and cleanup intent. A separately authorized backend cleanup execution path for deleted-account/project objects is still required; the code does not export or recover deleted users' credentials or introduce a general garbage collector. Unresolved upload attempts also retain pending cleanup until an approved reconciliation path can establish that the writer has stopped; timeouts and 5xx are not erasure evidence.
4. **Provider/device/image evidence is missing.** No real STT calls, native builds, physical devices or actual browser microphone recording were exercised. Synthetic ffmpeg media and deterministic MediaRecorder doubles establish local behavior only. The updated API dependency image was not built.
5. **Independent review of the new fixes remains required.** Runtime review of `804a5b19` completed and returned the two defects documented in `review-fixes.md`. Rerun against the new exact PR head, including cleanup receipt ordering, deleted-audio pending-turn recovery, SQL wrapper compatibility, transfer/lifecycle locks, trusted DSN privileges and client cancellation/recovery. The draft remains disabled and must not be presented as full issue acceptance or deployed retention.

The deployment environment must already grant the server's transactional DSN appropriate execution of the restricted attestation operation. This branch adds no credentials and grants no such access to end-user or service JWT roles. Missing authority, schema, decoder or connection fails closed.
