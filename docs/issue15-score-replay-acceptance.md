# Issue 15: score replay acceptance boundary

This audit covers [Issue 15](https://github.com/bohui/copyme2.ai/issues/15)
and the existing [draft PR 18](https://github.com/bohui/copyme2.ai/pull/18).
It does not close Issue 15 or Issue 2, authorize a merge, or authorize new
telemetry publication, retention changes, deletion, or service restarts.

## Code and offline evidence

The production fix remains the two-file change at
`701032f608a7d4c35b3ad098cf3ff1ec7c705563`, based on
`291622826cdfb776e946dcd92b65d2fdaf4923ad`:

- Preserve each deterministic score ID, including when the SDK raises a
  `TypeError` after accepting a submission. Never retry without the ID.
- Send the retained trajectory's timezone-aware `started_at` in UTC. Reject
  missing, invalid, and timezone-free values before submitting a score.
- Preserve authoritative worker trace/observation links for step scores.

The follow-on subprocess test adds no production behavior. It loads that
publisher independently in three fresh Python interpreters, reads the same
unchanged synthetic trajectory file, and controls publication clocks spanning
three UTC dates. All six captured score submissions retain two stable
ID/name/timestamp tuples, the original UTC millisecond timestamp, and the
expected run/worker subjects. Child environments are empty, Python runs in
isolated mode, and socket connections are rejected. No Langfuse SDK, database,
provider, judge, or network service is used.

The test fails against the pre-fix base because the missing timestamp becomes
the publication day's timestamp at the controlled transport boundary. It
passes against PR 18. This establishes cross-process **application transport
behavior**, not live Langfuse deduplication after a publisher restart or across
an actual UTC-date transition.

Cloud checks for this test/document-only follow-on:

- Focused trajectory/replay suite: **34 passed**; the new restart regression
  separately fails on the pre-fix base and passes on PR 18.
- Initial complete Python collection: **1,076 passed, 183 skipped, zero
  failures or errors**. Skips comprise 130 native PostgreSQL cases, one supported
  Apple-Container launcher case, 48 frontend/browser cases, and four opt-in
  live-model cases. This is not a complete native/browser acceptance pass.
- A second full collection on committed head `61994740b0434878849200fc01255deafd836598`
  returned **1,075 passed, 183 skipped, one failure** in the existing
  `test_sql_stdout_eof_exhausted_deadline_closes_process_before_later_cleanup`.
  Its three-second fixture returned `TimeoutError` with cleanup verified but
  no synthetic SQL child PID file. That test and its implementation are
  unchanged from main; a focused rerun passed. Both full-run results are
  retained, and this audit does not relabel the failed full run as passing.
  The lifecycle owner was notified for investigation.
- JavaScript/component checks: **173 passed**, zero skipped or failed.
- Python compilation, all 541 localization messages, and the 63 specification
  route assertions passed. The existing web lockfile matched the dependency
  tree used for the read-only localization parser check.
- No production file changed after the previously reviewed PR 18 head. Native
  and authenticated-browser evidence still belongs to the designated Mac
  test owner. No shared service or live model was used in these cloud checks.

## Live evidence already retained

The retained synthetic evidence packet
`memoir-issue15-durable-readback-701032f-20261006.tar.gz`, version 1, records a
successful separate-process readback at `2026-10-06T13:30:04.556670+00:00`.
It is historical evidence, not a fresh service observation from this cloud
audit. Its manifest hashes were checked before using it.

| Evidence | Recorded result | Remaining limit |
| --- | --- | --- |
| Project | `cmut9t75w00071z02n8bdv7it` (`memior`) | Only this existing authorized project is in scope |
| New replay probe | Trace `fcdb03715b4c791ad95ce1ad282d3700`; root `6dd48baccc028aad`; child `f9abfeb9b9fa0623` | Synthetic ingestion, not canonical model acceptance |
| Replay score | `f676a571676d34f029e893916ca827cf9eb0bab419d208abf4f8f97f21266cb9`; name `mac.issue15_replay_probe`; numeric value 1 | API numeric score, not a configured automatic evaluator job |
| Duplicate submissions | Three identical submissions in one publisher process; one logical API row and one `scores FINAL` row after process exit | No live republishing from a restarted process or later UTC date was demonstrated |
| Timestamp | `2026-10-06T13:20:53.063Z`, including millisecond precision and child linkage | Authenticated browser confirmation remains absent |
| Historical preservation | 3,750 logical year-9999 score rows; full-row fingerprint `10146712981589141912` unchanged | No timestamp reconstruction, legacy replay, or history repair was performed |
| Retention | `NULL`, unchanged | A concrete owner decision remains pending |

The original canary remains a separate record. Browser acceptance must locate
trace `f8316b85df420c4f0f17367985dbb22c`, root `edce02d9071ea188`, child
`f5de9464f6d47a01`, and score `37a2aace-2cdb-4b14-a345-19149ba7df9c`
in the actual authenticated browser with an explicit 2026-10-05 time window.
Verify the root marker, parent/score linkage, and numeric value 1. Do not
republish it merely to make it visible.

## Remaining acceptance gates

1. Obtain supported access to the actual authenticated browser and retain
   safe exact-ID confirmation for the original canary and the existing replay
   probe. The prior Mac evidence reports zero visible Chrome windows. No
   cookies, credentials, profiles, or private narrative content may be copied.
2. If live restart/date replay is needed, obtain approval for that specific
   synthetic publication before any write. Keep the retained score ID, name,
   recorded timestamp, trace, and subject. Do not replay old history or restart
   shared services. Read back after the publishing process exits and identify
   the browser records separately.
3. On exact-main canonical acceptance, join local run/case/round/step IDs to
   actual worker trace/observation IDs and run/step scores. The bounded
   application canary and configured/calibrated judging are separate gates;
   this synthetic probe provides neither semantic quality nor a complete
   canonical run.
4. Record the owner's explicit retention/cleanup decision. The earlier
   proposal offered either retaining synthetic evidence under unchanged NULL
   retention while review completes, or separately authorizing deletion of
   only the new probe after browser/evidence review. Neither option has been
   selected by this audit. Project-wide retention and irreversible deletion
   need their own concrete authorization.
5. Independently cloud-review the final code and evidence and pass applicable
   required checks before any merge. Preserve the historical fingerprint and
   existing canary throughout.

Issue 14 adds `trace_id`, `observation_id`, `job_id`, and `checkpoint_id`
correlation aliases in the same production module. Preserve those additions
when integrating its separately reviewed branch; they do not replace the
recorded score identity/date contract. Issue 13's evaluator changes are in a
different file and do not establish live score or semantic-judge acceptance.
