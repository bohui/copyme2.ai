# Memoir five-case, 50-round E2E evaluation design

Status: implemented and executed, `memoir-five-case-eval/1`

## Goal and non-goals

This evaluation runs five isolated, fictional biographies through the normal
Memoir application → `CodexRuntime` → private `codex-worker` boundary. A round
is exactly one storyteller/user response followed by one completed assistant
handling, including the application persistence and any background workspace
handling that the runtime exposes for that turn. Each case has exactly 50
rounds, for 250 rounds total.

The live-provider result is the release evidence. Deterministic fixture runs
are useful for exercising the runner, evaluator, persistence assertions and UI
journeys, but are never reported as live-model passes. No real memoir, family,
address, photograph, rights claim, or customer identity is used.

## Case coverage

The checked-in dataset will contain five coherent fictional lives, split across
`en-AU` and `zh-CN`. Every case supplies grounded material for all seven
supported life stages: `baby`, `toddler`, `childhood`, `adolescence`,
`young_adulthood`, `midlife`, and `later_life`. The round plan makes the stage
explicit in the storyteller's words, while still including ambiguous/corrective
rounds where the expected result is `unplaced` or a preserved uncertainty.

Each biography includes:

- a childhood anchor and later-life reflection;
- at least two named public places and a move/return boundary;
- a meaningful family relationship, a correction, and an unresolved identity
  or date that must not be inferred;
- approximate, ranged, and unknown dates, including a correction;
- an authorised personal-photo reference whose date/rights remain explicit;
- public-photo requests in current-day, historical, and unresolved/negative
  forms; and
- an explicit review-only composition request in the final round.

Round bands are stable across cases so aggregation is comparable:

| Rounds | Coverage | Expected high-level behavior |
| --- | --- | --- |
| 1–7 | baby/toddler | establish language and earliest memories; accept only explicit places/stages |
| 8–15 | childhood | places, routines, family detail, and approximate childhood dates |
| 16–22 | adolescence | family-tree and author-timeline work when entitled; corrections remain grounded |
| 23–30 | young adulthood | moves, place groups, historical/current public-photo distinctions, uncertainty |
| 31–38 | midlife | relationships, work/home transitions, current place references, negative skill cases |
| 39–46 | later life | reflective but source-grounded context, photo rights/date boundaries, corrections |
| 47–50 | cross-stage review | ambiguity/no-op checks, progressive enrichment, consented review-only composition |

The existing application contract names allowed stages but does not define
numeric age cutoffs. Therefore Harbour's round-30 early-thirties anchor is
`young_adulthood`, consistent with the 23–30 band; other round-30 anchors that
explicitly say “midlife” remain `midlife`. The oracle correction is recorded
separately in [memoir_five_case_oracle_corrections.json](../tests/evaluation/memoir_five_case_oracle_corrections.json)
and does not change the runtime schema or immutable baseline artifacts.

The five fixtures are deliberately different in geography, language, family
roles, occupations, and narrative voice; they are not five paraphrases of one
life. Truth records and evaluator expectations live in the dataset. The model
receives only the current storyteller response plus the state/context that the
real runtime normally supplies from prior completed rounds. Hidden truth,
expected markers, and expected tool calls are never injected as instructions.

## Seven-skill matrix

The evaluator classifies every round for every skill as `required`, explicit
negative `must_not_call`, or unasserted `not_applicable`, and records both
invocation and output grades. Optional behavior is not treated as a failure;
only dataset-declared positive and negative scenarios contribute to rates.

| Skill | Required checks | Negative/unnecessary checks |
| --- | --- | --- |
| `memoir-memory-context` | first-reply locale decision; repeated stage tags; place/stage separation; no gender inference | generic place, quoted text, or ambiguous time does not create a stage/avatar |
| `memoir-place-journey` | every explicit coarse place; multiple places in order; grounded correction; approximate hierarchy only | no marker for implied/ambiguous place, hospital/street/building, or public-history-only place |
| `memoir-place-groups` | background grouping for each accepted preview/update/restored history; separate city group and child pins | no model-call substitute; no parent coordinates copied to unresolved child; stale/other-project result rejected |
| `memoir-family-tree` | paid Family-only explicit people/relationships; canonical IDs on later updates; uncertainty/visibility | unpaid/pending/revoked entitlement never exposes or persists Family data |
| `memoir-author-timeline` | explicit events/periods; approximate/range/unknown precision; correction via `existing_id` | no invented dates, exact addresses, people IDs, or entries from assistant/public history |
| `place-photo-research` | current-day default; explicit historical window; source/rights/date labels; bounded search trace | no historical inference from life stage/previous context; no search for ambiguous/unrelated request; no fabricated source/photo/rights |
| `memoir-composer` | private checkpoint gate; 20-round preview gate; progressive update; final consented review-only composition | no full composition from readiness suggestion, payment exhaustion, or unconfirmed silence; no publish/charge |

`memoir-place-groups` is an application background service, not a model marker.
The trace must therefore show the accepted source place, project identity,
group-membership result, pin source, revision/order guard, and any error. A
successful chat reply alone is insufficient evidence.

## Deterministic evaluation

The runner records a resumable per-round trace with:

- dataset/case/round IDs and a hash of the truth fixture;
- application revision, Python/Node/Codex/provider configuration, skill
  manifest hash, evaluator/rubric versions, and run timestamp;
- request/response timing, retry/timeout counts, provider usage/cost fields
  when exposed, and explicit `live`, `fixture`, `blocked`, or `mock_only`
  execution mode;
- normalized observable trajectory steps, pre-action context, tool names and
  arguments, results/errors, application validations, persistence, task and
  workspace events, terminal status, and visible reply;
- stage and skill invocation/output coverage; and
- failed expectations with the smallest relevant evidence and a replay command.

Deterministic gates inspect actual application state and traces, not just the
assistant prose: authorization and project scope, entitlement state, marker
syntax/grounding, stage tags, accepted place records, group membership and
pin provenance, family/timeline revisions, photo search period/rights labels,
composition gate/mode, source lineage, revision ordering, step/retry/time
budgets, and final saved response count (exactly 50 per case).

The evaluator distinguishes:

- `pass`: the required observable state and trace assertions hold;
- `fail`: an assertion is contradicted by evidence;
- `unavailable`: the required live provider/judge/connector was not reachable;
- `not_applicable`: the round intentionally requires no action; and
- `mock_only`: a deterministic fixture exercised the harness but cannot support
  a live quality claim.

Judge-only green is not accepted. A semantic judge, if the configured judge is
reachable, receives a minimized ordered trajectory plus the pre-action context
for each action and scores tool appropriateness, evidence use, recovery,
repetition, stopping, instruction adherence, and final response quality. The
judge must use a checked-in calibration manifest marked `human-reviewed`; a
missing/unavailable/unapproved judge remains `unavailable`. A semantic score
cannot override a deterministic failure. Known injected failure examples
(unnecessary place/photo call, invented date, unauthorised Family write,
duplicate successful search, and incomplete composition stop) are included in
the calibration/negative suite.

The production repair path keeps the broad workspace extraction model-driven,
then runs a focused family-tree or author-timeline recovery pass only when the
current storyteller text contains an explicit cue for that domain. It never
synthesizes a marker from the evaluator's expected outcome. This cue gate is
itself covered by a regression test because unnecessary recovery calls affect
latency and provider budget.

## Run plan and safety limits

1. Preflight the configured provider, Codex worker path, application health,
   photo search configuration/budget, and optional judge without sending story
   content. Capture exact endpoint/model and the reason for any blocker.
2. Run a bounded pilot (one case, five rounds, concurrency 1) through the real
   orchestration seam before starting 250 rounds. Stop and fix runner/runtime
   defects before full execution.
3. Run five cases with bounded concurrency (1 by default; the final repair
   run may use at most 3), per-round timeouts, bounded
   retries only for explicitly retryable transport failures, and resumable
   checkpoints. No case is retried wholesale without preserving the failed
   trace. A full-book/composer call is permitted only for the synthetic test
   project after final consent.
4. Use at most one bounded external photo-search call per explicitly planned
   photo scenario per case, with the existing skill cache/budget and no browser
   CAPTCHA bypass. Report provider calls, cache hits, source-page reads,
   blocked/unknown rights, downloads, and remaining budget. Never claim a
   source photo or rights status without actual evidence.
5. If the real configured provider is unreachable or requires new credentials,
   report the precise blocker and continue implementation, fixture/persistence
   tests, and UI journeys. Do not change provider/model or fabricate live
   results. The live five-case target remains `blocked` until rerun succeeds.

## Deliverables and replay

Executable runner code is separate from versioned synthetic dataset,
prompt/evaluator templates, calibration examples, and expected outcomes. Run
outputs live under an ignored `var/memoir-five-case-evaluation/<run-id>/` tree
with one case/round JSON trace, summary, provider receipt, failures, and a
replay manifest. The checked-in report includes commands for preflight, pilot,
resume, affected-case rerun, deterministic regression, and browser/UI checks.

The final report will list all five 50-round cases explicitly, per-skill and
per-stage coverage, invocation/output grades, provider usage/cost, judge
availability, failed expectations, fixed/retested defects, UI evidence, and
remaining known failures or blockers. It will not compress blocked or
mock-only runs into a green aggregate.
