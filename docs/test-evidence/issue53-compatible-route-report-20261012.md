# Issue 53: compatible low route, full-prompt comparison

## Outcome

The corrected routing-only experiment passes its **frozen exploratory latency
rule**, not release acceptance. All 42 foreground generations saved: 20 matched
pairs across Chinese and English, plus two actual candidate-history rollback
turns. The candidate retains the complete legacy prompt and current narration.
Normal API/private-worker collector settings remain pooled/max/legacy. No
optimized default, compact prompt, shared-key policy or customer data was changed.

| Backend receipt, median of 20 matched cases per variant | Baseline max/legacy | Compatible low/legacy | Reduction |
| --- | ---: | ---: | ---: |
| First meaningful public text | 16.375s | 3.678s | 77.5% |
| Validated reply | 22.520s | 4.884s | 78.3% |
| Conversation saved, in-memory adapter | 22.520s | 4.884s | 78.3% |

First text improved in 18/20 pairs. Both public-reference pairs started slightly
later (Chinese 13.487→14.419s; English 7.938→8.628s) but saved sooner. Save time
improved in all 20 pairs. No case exceeded the frozen 1.20 save-regression guard;
that guard is exploratory, not a user-agreed SLA. These are small synthetic
samples, **not production percentiles or durable SQL/browser latency**.

| Input language / case | First text, max→low | Save, max→low |
| --- | ---: | ---: |
| Chinese / first | 8.909→3.231s | 11.266→3.911s |
| Chinese / later | 16.731→5.060s | 20.767→6.149s |
| Chinese / resumed correction | 39.549→2.905s | 44.209→3.842s |
| English / first | 6.502→2.725s | 8.556→3.324s |
| English / later | 10.317→3.535s | 14.096→4.544s |
| English / resumed correction | 16.248→2.585s | 20.084→3.465s |

## Approved local gateway change

The separate `gpt-5.6-luna-memoir-low` alias reuses `memoir-luna-low`'s exact
underlying model, endpoint, existing low-effort key and zero outer retry policy.
It has a distinct deployment ID and the same scheduling metadata. Only the new
alias was appended to the existing Memoir consumer model allowlist; other checked
consumer policy fields and existing gateway configuration stayed unchanged.
Only LiteLLM was restarted, with explicit user approval. The gateway changes are
present in its checkout at `1a95ee07119bf66e91be7269b3109ebfc5d610c2`;
this task did not push that repository or change a production deployment.

Read-only exact-key policy inspection verified the same `gpt-5.6-luna` upstream
model: the baseline key still enforces **max**, and the existing Memoir key
enforces **low**. No key policy was edited. The normal composer still selects
`memoir-luna-low`; neither it nor other roles acquired the collector override.

## Profiler fix and retained failure

The [first approved freeze](issue53-compatible-route-freeze-20261012.json)
produced two saved opening replies, then failed on the first candidate resume.
It is retained as [stopped evidence](issue53-compatible-route-stopped-20261012.json),
not dropped or counted as a passing campaign. Two successful provider rows were
observed in that time window; exact per-application upstream attribution is absent.

A no-provider Linux reproduction showed `shutil.copytree` changes tenant-owned
0700/0600 history files to root ownership. The tenant could read the original
but not the copy. Archive copy retains file/directory ownership and passes the
same tenant read check. The profiler now uses `cp -a`; **production worker
permissions and customer runtime homes were not changed**. The existing matched
backend tests also check a tenant-owned persisted checkpoint on resume.

The corrected campaign had fresh explicit approval and a
[new pre-dispatch freeze](issue53-compatible-route-corrected-freeze-20261012.json).
It used the real Linux worker's **Codex 0.156.1**, not the host's 0.155.1, on
application revision `641e9d31ae1f30d8073f37cb53ff8b9fb9cef23f`. Fourteen source
files matched the pinned checkout before and after execution; SHA-256:
`78a4190ad112a16f8dbc60f6c5c47db57af07863870dac6858da4b54391ef5ab`.
The worker image has no Git, so its own receipt honestly records revision as
unavailable; the operator receipt supplies the independently verified revision.

Both freezes cap each generation at 120s and the campaign at 1,200s, stopping at
the first failure. The corrected run completed within that deadline. Its 42
app-server turns were one per successful foreground generation. The 84-turn
bound is not an exact upstream retry budget. Including the stopped run, 45
foreground generations were attempted; no replacement or additional campaigns
were dispatched after the corrected run.

## Quality review and measurement limits

All 20 candidate public replies were reviewed against their synthetic inputs and
baseline replies, without additional judge-model calls. No clear new invented
actor, identity, year, image observation or conversation-language failure was
found. Chinese names were retained; correction to the mother, sister-not-daughter,
unknown years, metadata-only photo attribution and public references not proving
residence were respected. Both pauses had zero questions. Both long-stress replies
used the unique final blue-envelope detail, and both rollback replies resumed the
candidate history with the prior language preference intact.

One **quality caution remains**: the English photo candidate asks what is remembered
about *when* the photo was taken after the narrator says they do not remember when.
This can seek circumstances, but risks re-asking unknown timing; the baseline asks
about the occasion. This is a review concern, not proof of a universal regression
or semantic equivalence. The repeated long text is a completeness stress case,
not representative emotional-quality evaluation. Private candidate planning and
live workspace extraction were not comprehensively semantically assessed.

The [full receipts](issue53-compatible-route-results-20261012.json) retain all
results and allowlisted provider observations. Forty-two successful provider
rows match the expected effort ordering (22 max, including rollback; 20 low),
consistent with one upstream request per generation. Correlation is by
time/order, **not an exact application UUID join**; per-generation upstream retry
counts remain unavailable. Recorded local gate wait is 0ms and bridge queue is
0–1ms. Broader provider/account load metrics are unavailable.

Fresh opening token counts now nearly match: Chinese 9,258/9,261 and English
9,191/9,194, with zero cached input for both. Later/resumed request footprints
still differ after an alias change in persisted Codex threads. For example,
Chinese later input is 23,743/16,557 and correction input is 25,102/34,292;
cache counts also differ on the later pair. **Do not attribute the entire speed
improvement solely to reasoning effort.** The actual intervention is the route
change with its resulting Codex/provider context and cache behaviour.

Storage is the existing isolated in-memory external adapter, and optional
workspace model responses are controlled. Photo pixels are not supplied by the
collector contract. This run does not establish real SQL save speed, live image
perception, real workspace extraction quality or a production SLA.

## Verification and issue 53 closure position

- Focused backend suite: **193 passed**, including real Apple-container SQL
  readback, stream, collector, source/language, plan/photo, lease and cancellation
  regressions; live-provider pytest switches disabled.
- Frontend regression suite: **59 passed**, including native-reader observation,
  save-gated readiness, the fixed-introduction race, navigation and reload.
- Linux worker: **six controlled profiler assertion checks passed**, directly
  executing the repository test functions with tenant-owned checkpoints;
  pytest is not installed there. Zero live provider dispatches in those checks.
- Gateway: **six configuration tests passed**; `make agent-ci` exited 0
  (79 startup, 56 composition-policy and 41 Node checks, plus build/lint/pack).
- Source hashes and normal collector/composer settings verified after the run.
  The frontend/API/smoke source from the
  [prior real-proxy smoke](issue53-pr58-follow-up-20261012.md) is unchanged.

The previously reported whole-repository run was **not green**: 4,009 passed,
69 failed, 194 skipped and 39 errors. No successful full-suite rerun or GitHub CI
status is claimed. The partial base comparison did not prove every failure
unrelated. The prior real-proxy smoke used normal max/legacy, not this candidate.

### Concurrent PR integration

Before publishing, remote PR 58 advanced to
`0f7af90269c5aacbb971e33701cbbb134797ff9e`, integrating historical-news main
changes and a separate verification repair slice. Those changes were preserved
in merge `b777cd5f82aff860b52fd500e876f68a369636b6`, without conflicts or a force
push. The profiler overlap only removed trailing blank lines; both profiler
fixes and their regression tests remain intact.

On that combined revision, **317 focused backend tests passed in 26.62s**
(the 193-test set above plus historical-news/provider and collector-boundary
checks), and **71 frontend Node tests passed** on Node 24.19.0 (the 59-test set
plus photo-browser fixtures and historical-news rendering). Counts overlap;
do not add them to the earlier totals. A first attempt to launch Homebrew Node
24.4.1 failed before test execution because its simdjson library was missing;
the bundled Node 24.19.0 completed the checks. No further live calls were made.

The imported [verification addendum](issue53-pr58-follow-up-20261012.md) records
an additional comprehensive cloud run: 4,283 passed, 71 failed, 94 setup errors
and 8 skipped, with unsuccessful cases classified there as browser-runtime,
Chromium socket or renderer-DNS prerequisites. That is inherited evidence,
not a new local full-suite pass, and the overall run remains **not green**.

The combined head changes runtime/schema/frontend source beyond the live
campaign's pinned `641e9d3` revision. Its historical-news behavior was not in
that campaign. Neither the campaign latency nor the earlier real-proxy smoke
is final-head live acceptance; candidate real API/SQL/proxy and semantic-quality
verification must use the combined release candidate before rollout.

| Acceptance area | Current evidence / remaining gate |
| --- | --- |
| Every-turn path, first/later/resumed, both languages | Shared implementation and focused tests pass; matched live latency positive; normal default not enabled. |
| Grounding, full testimony, plans, photos, Family, reference, pause, language | Focused contracts pass and public synthetic review is encouraging; broader semantic quality and the photo follow-up caution remain. |
| Server-owned route, genuine effort, role isolation, existing history, rollback | Dedicated local policy verified; histories retained; both actual rollback turns saved; other defaults unchanged. |
| Stream/save/readiness, cancellation, lease, quota and ownership | Focused backend/SQL and frontend checks pass; candidate real API/SQL/proxy smoke still needed. |
| Safe bounded timing, counts, source/config pinning, provider observations | Recorded; context/cache confounds and missing exact retry attribution disclosed; no production p95/SLA claim. |
| Compact prompt | Remains off. Prior negative pilot is retained; no final-head matched prompt-only/combined acceptance is claimed. |
| Quality-preserving release and full verification | **Not satisfied.** Candidate remains disabled; issue 53 stays open. |

Recommended next step is a small, separately bounded candidate test through the
real API/SQL and web proxy with isolated synthetic identities and no normal-route
change, followed by representative semantic-quality acceptance. Any additional
live calls or default activation need explicit approval. Keep the full prompt;
do not enable `compact-v1` or close issue 53 on the strength of this pilot alone.
