# Fifty-input budget proposal, not live admission

This note describes the pure `scripts/fifty_round_budget_contract.py` interface.
It changes no existing actor, guard, launcher, service, database or credential.
The old ten-input canary remains capped at 80 sends, 900 seconds and 60 seconds
per request. Its approval/reservation does not authorize a fifty-input run.

## Source and call graph

Audit source: `3a9a339813ed06fb06ba18815bf32b880072314e`, tree
`640f47d4ea8d1e8cb52f3198dfb93719cec1457e`. The module records the inspected
file hashes; revalidate them against latest main before any future campaign.
This is one fresh synthetic owner/project, 50 original typed inputs, fixed
locale/Family policy and checkpoints at rounds 5, 10, ..., 50. It is a synthetic-
entitlement backend test, not evidence that the ordinary 20-round free/browser
gate permits a 50-round run. Voice is excluded.

For one sequential, non-replayed canonical path:

L = I + 150 + Qp + Qf + P + C

- 50 collector + 50 broad workspace + 50 canonical extraction worker calls
- I = 0–1 initial locale classification calls; an explicitly seeded locale needs none
- Qp = 0–50 focused place calls
- Qf = 0–150 focused Family calls when enabled, including up to 100 semantic repairs; zero when disabled
- P = total actual uncached dirty-active-event preparation dispatches
- C = up to 30 drafts + 30 reviews, including up to 40 semantic repairs

Ten successful, changed, nonempty checkpoints normally require at least 20
composer calls. Cached/unchanged or incomplete checkpoints can use fewer; their
counts never establish completeness. Canonical composition skips the legacy
model-indexing path. Preparation concurrency bounds parallelism, not P.

Source references: `codex_runtime.py` collector/language/workspace dispatch;
`memory_event_worker.py` timeline direct POST; `canonical_composer.py` dirty-event
preparation; `memoir_preview.py::compose_candidate` three-attempt draft/review
loop; `codex_agent.py::turn` tool-continuation loop. A worker invocation can cause
multiple upstream generations. Never identify worker counts with provider calls.

P is not automatically 50. The extraction schema permits up to 100 proposals
per commit. P ≤ 5,000 is only conditional on exactly 50 commits, stable
policy/configuration, no outside edits, successful sequential checkpoints and no
uncached replay. Re-preparing all accumulated history at each checkpoint instead
produces P = 275e for e new events per round (27,500 at e = 100). The proposed
P ≤ 100 below is an independent operational stop, not a forecast or source-derived
guarantee. Reaching it may leave the campaign incomplete.

## Envelope to ask the user to approve

- At most 600 actual upstream sends across every role, continuation and repair
- At most 100 uncached preparation calls; at most 511 logical worker calls with
  Family, or 361 without Family
- One concurrent model operation, 60 seconds per send, 7,200 seconds total
- No transport retry, activity redelivery, account failover or reservation reset
- No judge, photo, geocoding, hosted remote tool, voice or paid-provider route
- One shared actual-send reservation and independent role/preparation counters
- Stop on unknown/unsettled usage, quota/provider/protocol failure, cancellation,
  time limit or exhausted cap; retain unresolved reservations

At the full 511-worker allowance, the proposed 600-send stop leaves 89 sends for
additional internal continuations. That is not evidence that 89 will suffice.
Neither 600 sends nor two hours guarantees completion, and time/concurrency are
not spending controls. This contract is always `unapproved`, cannot authorize or
dispatch, and does not implement these new runtime limits.

`runtime.observed_worker_requests` alone is insufficient: the canonical timeline
posts directly, while the canonical composer uses a SimpleNamespace without its
recorder. A future approved implementation needs a shared worker-boundary count
plus the actual upstream guard. Unknown actual counts must remain unknown, not
be substituted with worker counts or guarded-entry totals.

## Preserve latest-main role routing

Compose/example defaults are:

- Collector, broad/focused workspace and locale: `MEMORY_SPARK_LLM_MODEL`, alias
  `gpt-5.6-luna-pooled`; interview reasoning setting defaults to `max`
- Canonical timeline: `MEMORY_SPARK_MEMOIR_COMPOSER_MODEL`, alias
  `memoir-luna-low`; `MEMORY_SPARK_AUTHOR_TIMELINE_REASONING_EFFORT` defaults to `low`
- Composer prepare/draft/review: the same composer model setting, with
  `MEMORY_SPARK_MEMOIR_COMPOSER_REASONING_EFFORT` defaulting to `low`

Explicit payload models take precedence. A global worker reasoning override also
wins over role defaults. Native configuration is unverified. Code-only fallbacks
also differ when settings are absent: CodexRuntime's composer fallback is
`legal2ai-luna-low`, and CodexWorker falls back to its ordinary model. Do not guess
native alias resolution from the example configuration.

The old canary forces all roles to `gpt-5.6-luna`/`low`; this is a separate override
experiment and cannot establish latest-main routing. A fifty-input campaign must
record each role's configured alias, actual wire model and reasoning policy, and
obtain separate approval before any override.

The proposed existing account is erduoy, identified by the prior non-secret
fingerprint in the contract. Both role aliases must be verified against the
intended existing consumer and single-account subscription context. This is not
proof of equivalence to a deployed provider pool. Consumer/account binding,
model aliases and native routing remain unverified here.

There is no verified input/output/reasoning-token bound, per-request output cap,
price/rate, currency or maximum cost. No hard token or monetary ceiling is claimed.
The user would need to approve a specifically disclosed request/time-only
subscription envelope, or provide a compatible enforceable token/cost route.
No paid request may be made to discover that budget. Broader #14 judge calibration,
variant comparisons and token/cost acceptance remain open.

## Pure API

`build_budget_proposal(family_enabled=..., max_actual_requests=600,
wall_seconds=7200, request_seconds=60, max_preparation_requests=100)` returns a
fresh JSON-safe unapproved proposal. `assess_budget_observations` checks explicit
per-stage counts and a separately supplied actual count; `None` remains unknown.
It detects overrun/exhaustion and unsettled requests, rejects missing/unsupported
stages or any changed fixed proposal field, and never grants admission or claims
native evidence. Proposal validation requires exact JSON container and scalar
types recursively: `50.0` cannot replace `50`, and `0` cannot replace `false`.
Plain JSON roundtrips and dictionary key reordering are supported; container,
string and numeric subclasses are rejected. The independent fifty-round planner
can compose this object.
