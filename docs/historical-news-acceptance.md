# Issue 55: historical news acceptance evidence

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
