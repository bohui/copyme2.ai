## Problem

The existing five-case live runner uses its legacy evaluation storage/direct
composition path and samples only 20/25/50. It cannot establish canonical
MemoryEvent/Temporal acceptance. The new fixture callback exercises real
UserStorage, CodexRuntime/private workers and native PostgreSQL/Temporal at
default and nondefault cadence, but is not a complete live launcher.

Related: Issues #2 and #6. Keep both originals open until their remaining
acceptance passes. The user requests reviewed landing first, then five separate
50-round datasets on exact merged main, followed by fix/review/retest.

## Agent scope

Wire `scripts/canonical_evaluation.py` into the existing evaluation command
through the authenticated story workflow. Complete its live adapter only after
verified provider accounting (G3); the current callback rejects live mode.
Preserve canonical MemoryEvents, accepted original sources, source-claim cN
validation/metadata stripping, attributed/timing event vetoes and null claims.
Use the agreed UserStorage/runtime/worker public seam and /TDD. Independent
review stays in cloud; no local code-review agents.

## Acceptance criteria

- Run preflight without model calls; fail closed on missing isolation,
  worker configuration, provider accounting, exact revision, or required judge
  configuration. Never create credentials or infer a judge configuration.
- Pin actual main SHA/tree, dataset/expected/truth/rubric and skill/reference
  hashes, evaluator version, configured model/provider identifiers and budgets.
- Use five separate synthetic storytellers/projects, 50 original inputs each;
  do not reuse customer storage, provider homes, object paths or task namespaces.
  Reject populated/reused projects before dispatch and retain original testimony.
- Execute the normal runtime/worker contract and actual PostgreSQL/Temporal
  source, extraction and composition lanes. Read every milestone 5/10/.../50
  through public storage; retain stable event IDs, evidence links, source
  versions, coverage, unchanged-content hashes and saved/proposed/failed states.
- Grade skill invocation separately from skill output. Record positive,
  negative, optional and unavailable outcomes without turning skips/errors or
  synthetic provider replies into model-quality passes.
- Preserve failed-round trajectory and raw outcomes, emit a reproducible
  case/run manifest and bounded timeout/cancellation/cleanup receipts.
- On exact main, perform the approved 250-round workload and publish durable
  Langfuse/browser evidence (G4). Any observed bug gets a failing public-seam
  regression, fix, cloud review, approved landing and justified affected rerun.
- Add focused native tests using the existing supported UUID Apple Container
  `postgres:18.3` fixture: no shared mounts/published ports, TCP disabled,
  container-exec psql, exact fixture cleanup. At most one fixture container and
  one Temporal dev process at a time on this host; coordinate other heavy tasks.

## Limits and evidence

The prior whole native suite is 1,194 pass / 4 live-only skip / 0 fail / 0 error.
The new callback/budget suite is separate, with synthetic provider responses.
Historical baseline is 205/8/37 of 250; affected run is 152/5/43 of 200;
diagnostic pilots do not replace acceptance. Read the landing disposition and
canonical readiness receipt on PR11's exact reviewed integration head.
No shared restart, deployment, production migration, paid run or merge is
authorized by this ticket alone. The parent coordinates head/disposition and
the numerical live budget before execution.
