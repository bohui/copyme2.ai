# Issue 55: historical news acceptance evidence

Subsequent merged-main verification is recorded in the
[12 October live addendum](verification/issues53-55-live-20261012.md).
The previously blocked rendered citation/control smoke now passes on macOS, as
do all 44 historical PostgreSQL cases through the existing disposable-container
transport. Live discovery returned unavailable with no eligible clue. Wider
browser/aggregate gates remain unresolved; issue 55 remains open. The results
below retain the original implementation-run scope and dates.

The feature is disabled by default. No live provider calls, production migrations,
deployment or real storyteller data were used. Synthetic tests establish tested
relevance and non-leading invitation quality, not historical provider accuracy
or actual human recall.

## Acceptance coverage

| Criteria | Executable evidence |
|---|---|
| AC1–2: bounded hypotheses and conservative context | `test_historical_news.py`: realistic canonical birth event, explicit remembered period, uncertain birth, ambiguous place, confirmed English/Chinese moves and unparsed-move suppression |
| AC3–4: privacy and verified public evidence | Unit/provider fixtures capture coarse queries; reject missing native receipts, fabricated identities, publication/event confusion, unsupported source content and private URLs; native persistence rejects missing and over-limit fields |
| AC5: background completion and subsequent turn | Controlled barriers save the immediate ordinary reply and a second ordinary turn while research remains held; delayed completion preserves the newer plan; a normal-turn fixture executes the actual research helper with a controlled provider |
| AC6–7: retained pool and neutral invitation | Existing plan/photo runtime tests plus bilingual reviewed invitation, bridge, acknowledgement and citation module tests; ordinary/active memory candidates retain priority; present-day photo default is unchanged |
| AC8–9: durable references and testimony boundary | Native PostgreSQL validates current owned references, biographical year restrictions, immutable citation replay, exact later testimony and versioned cue-assisted attribution |
| AC10: controls | Native skip/opt-out/re-enable, explicit return, excluded topic and narrator-control fixtures; ordinary narration containing “paused” does not disable clues; module control smoke is available but rendered execution remains blocked |
| AC11: budgets and failures | Deterministic two-query/six-source/five-clue saturation, controlled-clock 45-second deadline and 24-hour expiry, bounded retries, failure accounting/cache behavior, concurrent claim dedup and source subprocess cancellation |
| AC12: isolation and stale writes | Native RLS/direct-write denial, snapshot-to-claim correction race, source/context changes, ownership transfer, deletion, opt-out and stale completion fences |
| AC13: integration and review | Skill catalog/install, public/private worker, recovery/history, localization and OpenAPI contracts; independent exact-source review; aggregate/build pass (see below) |
| AC14: semantic quality | Positive and negative bilingual fixtures, including surrounding acknowledgement and sensitive cited card; rubric and scope in `historical-news-semantic-review.md` |

## Verified results

Red tests were observed before the initial modules existed and with the incremental
migration withheld. Independent review found and prompted regression-backed repairs
for durable JSON null handling, stale claims, source identity/date evidence,
conservative context parsing, source cancellation, pool preservation, testimony
attribution, surrounding acknowledgement safety and source field bounds.

- Local `4a6b98c`: 132 focused application/provider/plan/photo-runtime tests and
  3 Node citation/replay tests pass.
- Independent `4a6b98c`: 134 focused Python tests and 3 Node tests pass; no remaining
  reproducible code finding. This commit only adds tests over `26f8e25`.
- Independent `26f8e25`: 261 broader focused/runtime/recovery tests pass. Disposable
  native PostgreSQL 17: 44 repository tests plus 7 independent negative probes
  pass; owned clusters were shut down and cleaned up.
- Localization catalog validates 562 messages; mobile OpenAPI snapshot matches
  all 36 operations. JavaScript syntax and whitespace checks pass.

## Open gates and unavailable checks

The rendered smoke could not launch Chromium in this cloud runtime: Unix socket
creation is not permitted. This is unavailable, not passed. The opt-in command is
`MEMOIR_RUN_HISTORICAL_BROWSER=1 python -m pytest tests/test_historical_news_browser.py`;
it exercises the production citation/control module. No denied browser route was
retried. The browser waiver for another pull request does not cover this feature.

Final local source `13a2821`: full Python aggregate passes with **3,897 passed,
503 skipped, zero failures** in 347 seconds. Skips include opt-in rendered/HTTP
fixtures and native PostgreSQL outside the default PATH; the separately executed
44 native historical-news tests and 7 independent probes above remain distinct
evidence, not blanket coverage for skipped suites. The first aggregate found an
introduced isolated voice-renderer dependency failure; the unchanged regression
was reproduced on this branch (base passed), then repaired by rendering a
historical card only when historical context exists. Independent review of the
repair passed 141 focused tests plus 3 Node tests, and a production renderer probe
confirmed both the cited card and voice-mode behavior.

All 345 non-browser Node regression tests pass on that same source, including
production historical snapshot persistence/streaming and the existing photo,
history, scope, voice and locale suites. Legacy isolated helper tests exposed
additional absent-snapshot calls; five guards repair them without changing prior
assertions. Test execution uses the existing Python venv on PATH and
`ENV_FILE=/dev/null` for the synthetic Make/Node report fixture, with no credentials
or live evaluation. The new production integration tests ensure valid snapshots
still flow through those paths.

Practical real Next HTTP checks also pass: 18 locale-negotiation tests and 8
Auth/locale tests (one explicitly browser-only case skipped). Task-owned loopback
servers were shut down. These checks supplement the aggregate opt-in skips;
pre-existing Playwright journeys requiring isolated frontend/browser servers
remain unrun, as does the directly relevant new rendered citation/control smoke.
The HTTP checks do not establish click, layout or browser recovery behavior.

The standard Next 16 production build passes on `13a2821`. Setup required disabling telemetry
(to avoid the read-only home configuration directory) and a task-local dependency
copy (Turbopack disallows an external node_modules symlink). No source/config
workaround was needed. Final published-head/tree verification remains pending. The feature
must remain disabled and unmerged until required acceptance/review gates, including
the rendered browser gate, are satisfied or explicitly revised by the owner.

## Interview activation repair — 15 October 2026

The owner explicitly requested repairing and enabling historical research during
Memoir interviews. The canonical runtime now queues research only after a saved
narrator reply. Response cleanup sends the reply, releases the conversation lease
and local lock, then runs research before closing its authenticated storage
client. Failed optional research cannot replace or invalidate the saved reply.
Completed research is deduplicated on replay; disabled/opted-out projects create
no new durable research job.

The updated regression uses the current canonical JSON and streaming transports,
not the removed legacy runtime methods. It blocks research while another reply
completes, verifies later clue consumption, and covers missing context and
provider/storage failures. Real disposable PostgreSQL tests verify a saved reply
precedes the research claim, no interview lease remains during discovery, a
completed replay makes no new model request/job, a later question cites the
persisted clue, and public history creates no personal MemoryEvent.

The focused Python set passed **141 tests**; the two canonical PostgreSQL tests
were also rerun successfully after adding replay assertions. All **44 existing
historical-news PostgreSQL checks** and the real Chromium citation/skip/replay
smoke passed. A separately attempted older
`test_lifetime_memory_runtime.py` fixture failed while constructing its local
socket DSN (`'-p' is not in list`), before interview execution. The new
PostgreSQL regression explicitly requests the supported TCP publication fixture.
This repair changes no browser code.

Live calls through the configured gateway reproduced HTTP 400 for
`max_tool_calls`; the adapter no longer sends it. A real completed response
contained a 457-character opaque response ID, so receipt validation now accepts
bounded IDs up to 1,024 characters. The main `gpt-5.6-luna-pooled` gateway alias
reported maximum reasoning effort despite a low-effort request. Historical
research therefore uses the existing same-model `memoir-luna-low` alias via
`MEMORY_SPARK_HISTORICAL_NEWS_MODEL`; blank retains the normal LLM model.

The repaired adapter completed native search with returned source URLs and
structured historical leads. Live Sydney 1973 and 2000 samples each returned
completed discovery receipts and up to 24 returned URLs. Their complete bounded
research runs produced **zero eligible clues** because source access or exact
evidence validation failed; both stopped at the existing 45-second deadline.
This proves gateway discovery interoperability, not a successful live citation
or real-person memory benefit. Independent source inspection, provenance,
sensitivity, privacy and opt-out checks remain enforced.

Local `.env` enables research and selects `memoir-luna-low`. Compose now forwards
both settings to the API; repository defaults remain opt-in. After the existing
stack operation released its lock, the API was recreated and service aliases
refreshed. Running-container readback confirmed `MEMORY_SPARK_HISTORICAL_NEWS=1`
and research model `memoir-luna-low`, while the collector retained
`gpt-5.6-luna-pooled`. The stack health check passed, and API connections to both
Codex and photo workers returned HTTP 200. A final discovery call from the
restarted container, using its saved configuration without overrides, completed
in **24.81 seconds**, returning a completed native receipt, **24 source URLs** and
**two leads**. This final call verifies discovery, not independent inspection or
publication of those leads. The full repository test suite was not rerun.

## Independent cloud review repair — 15 October 2026

The GitHub Codex cloud review on PR #67 reviewed published `bb0b371` and found
three defects. Regression tests reproduced all three before repair:

- Source-only narration now changes the durable historical context/job revision.
  An older running job cannot suppress replacement research, and ready clues are
  hidden until their hypothesis is checked against the current accepted basis.
  Local revalidation can retain inspected evidence for an unchanged hypothesis;
  a move, changed preference, stale snapshot or different owner cannot rebind it.
- JSON and streaming transports record successful terminal delivery. Cleanup
  always releases the lease and storage, but only a delivered reply starts
  external research. A failed terminal or final body makes no search request.
- A native search receipt now requires the whole response and its event message
  to have explicit completed statuses. Valid JSON inside partial output fails
  closed instead of being reported as completed research.

The follow-up set passed **215 tests**, including the historical application,
provider, current canonical JSON/stream SQL, historical SQL, actual Chromium,
interview-plan, skill installation/configuration and governed transport suites.
The source fence is an incremental migration,
`202610150001_historical_news_source_fences.sql`; apply pending migrations using
`make migrate` before running this application version.

The broader Python aggregate completed 6,179 cases with **5,016 passed,
647 failed, 275 errors and 241 skipped**. It used four isolated workers and a
30-second per-test timeout. Many setup errors were fixture timeouts; the directly
relevant canonical SQL cases subsequently passed with a sufficient fixture
budget. Representative route failures, a removed worker-contract expectation
and an indefinitely waiting legacy worker test were also reproduced on baseline
`6808ef5`. This aggregate overlapped follow-up edits and is diagnostic evidence,
not an exact-final-commit green run. It does not establish that every broader
failure is pre-existing.

The owner explicitly permits closing #55 when its feature checks and final
independent cloud review pass, with broader failures recorded as non-blocking.
The final reviewed commit and final check outcomes are recorded on PR #67 and
the issue rather than represented by the earlier aggregate's starting SHA.
Live human recall benefit remains unmeasured; no suitable live news is a valid
outcome and no citation is fabricated to obtain a positive result.

The second cloud review found an upgrade-only case: existing three-component
clue revisions were invisible to the new source fence. The incremental
`202610150002_historical_news_legacy_fences.sql` preserves those ready records
with a legacy sentinel, making them eligible for local revalidation rather than
direct selection or mandatory rediscovery. Real SQL covers both unchanged and
changed hypotheses without creating another research job.

The repeated canonical fixture timeout was independently reproduced with a
262,144-byte command input and a child that waits before reading. The shared
test command runner could stop writing stdin after its first 0.1-second poll.
It now supplies input through an automatically closed temporary file while
retaining deadline/cancellation polling and child cleanup. Text and binary
regressions cover this case. The upgrade/runner/historical SQL/canonical set
passed **58 checks** after the repair.

The next review identified recovery after failed initial delivery. An eligible
saved replay now queues post-delivery enrichment too; the current owned durable
claim prevents duplicate research after a successful original delivery. Real
SQL JSON/stream regressions cover a failed initial terminal send, successful
cached delivery without another collector call, one recovered research job,
another deduplicated replay and later clue selection or move-based rejection.
An additional regression exposed a missing citation in canonical cached replies;
replay now restores the saved public historical projection without private
research metadata or another collector call. Only the latest accepted source's
eligible saved replay can recover research, so older replies cannot restart it
after a newer exchange.
Stopped exchanges, unavailable saved replies and disabled research remain
ineligible, while current project opt-out is enforced by the durable claim.
