# PR9 + PR10 cloud integration

## Exact ancestry and scope

Integration branch: `codex/cloud-pr9-pr10-20261004-1941`

This branch combines the two reviewed, pinned heads in a two-parent merge commit:

- First parent, PR9: `84366778f50495d065e794a00f16184d16dc4216`
- Second parent, PR10: `90dee1f2be4f6a83fbc44e779f8d2e91106c6061`
- GitHub-confirmed common ancestor: `28acda14f684aab6dd4dbbaf4fcc398e4d853b9b`
- Main observed before publication: `8e61b19b0a223578450684500263e3c7e7a1c010`
- PR9 parent tree: `4fb4392f7212280b4fead659911b96625a768c45`
- PR10 parent tree: `57864f11af1d1ee1afeb594a09fab5f289b562b3`

Both PR heads still matched these pins immediately before integration. No PR was
merged into its target, retargeted, or marked ready. Main, PR3, PR9, and PR10 remain
separate refs. There was no live provider evaluation, production migration, shared
service restart, or deployment. This branch is for a fresh isolated Mac validation
session; it does not claim final live acceptance or main-merge readiness.

## Integration decisions

The only original overlap was three paths: runtime (three textual conflicts),
worker service (two), and timeline skill (one).

- Preserve PR9 accepted narrator source kind, canonical event lane, private draft
  lanes, prepare-task isolation, canonical-only UserStorage timeline persistence,
  trajectory privacy, and removal of the old private-draft synchronization path
- Preserve PR10 profile/stage routing, place recovery, bounded Family retries,
  per-item source association, private cN validation/stripping, and evaluator changes
- Pass both canonical_events and source_text through private worker and local
  prompt paths; propagate canonical ownership through every focused recovery
- Canonical workspace recovery permits place and relationship-tree work, but does
  not dispatch a duplicate legacy author-timeline recovery
- Keep canonical timeline SKILL.md byte-identical to PR9. Its schema remains
  {"events": [...]} with exact original source references. Preserve PR10's complete
  legacy marker contract unchanged in references/legacy-marker.md and load that
  only for the legacy workspace prompt
- Preserve all eight non-overlapping PR10 files exactly. Both Issue6 additive SQL
  migrations remain byte-identical to PR9; no migration is rewritten

Integration review found that simply retaining the legacy marker sanitizer would
lose explicit per-event recording vetoes on the canonical production lane. The
canonical validator now resolves exact quote/code-point spans against the same
source-clause splitting and veto-scope contract. Broad vetoes apply to the whole
source; a scoped veto applies to the preceding non-veto claim, including attributed
recollections. Independent allowed claims survive. Repeated quotes without a span
conservatively cover every occurrence. All source, timing, stage, relation, and
correction evidence is checked. Affected proposals are withheld without persisting
private cN fields or importing legacy first-person eligibility rules.

Review also found a malformed-claim edge case: an explicit null cN value previously
looked absent and could escape validation. An absence sentinel now distinguishes it;
null claims fail closed and are not persisted.

## Cloud verification (2026-10-04 UTC)

465 source text blobs were downloaded through the authorized GitHub connector and
verified against their Git object SHA before materialization. Unchanged binary
objects are retained directly by their original tree references.

- New integration tests: 26 passed, no skips
- Focused runtime/worker/profile/Family/evaluator/trajectory/stream/skill union:
  217 passed, no skips
- Composer Node contract and ten-profile progressive fixtures: 62 passed, no skips
- Python compilation of apps, scripts, and tests: passed
- Changed-runtime/worker/canonical-validator whitespace checks: passed
- Independent scoped integration review: no remaining integration-specific blocker;
  additionally checked 4,500 deterministic quote/span cases for equivalent behavior

Red/green evidence: the initial integration contract run on PR9 had 11 failures and
3 passes; new null-claim tests failed twice before the sentinel fix; attributed
veto tests exposed three failures before structural targeting; timing/stage/relation
veto tests failed three times before checking every evidence field. Final tests pass.

The broad non-browser run is **not green**: 736 passed, 125 skipped, 1 failed,
16 setup errors, 1 deprecation warning. The failure/error set was independently
reproduced unchanged on the exact PR9 parent:

- test_recall.py::test_ordinary_turns_cannot_use_legacy_opening_text_to_avoid_the_free_gate:
  its QuotaStorage test double lacks headers when the accepted-source RPC is invoked
- All 16 test_place_workspace.py cases fail fixture setup because their monkeypatch
  targets the absent apps.api.place_photo_fingerprints module

The 125 skips require local PostgreSQL tools (initdb, pg_ctl, psql), unavailable in
this cloud executor. Browser tests and the six Temporal integration tests were not
run here. Initial cloud-only missing SOCKS support was resolved in the isolated test
environment, not in repository dependencies. Cloud Python was 3.12, pytest 9.1.1,
Temporal SDK 1.34.0, and Node 24.19.0; the checkout's .nvmrc requests Node 26.

### Reproducible checks

From the pinned checkout, with its normal isolated dependencies:

```sh
python -m pytest -q tests/test_integrated_timeline_contracts.py tests/test_codex_agent.py tests/test_codex_worker.py tests/test_profile_intake.py tests/test_family_agent.py tests/test_memoir_five_case_evaluator.py tests/test_trajectory_evaluation.py tests/test_turn_stream.py tests/test_memoir_skill_configuration.py
node --test skills/memoir-composer/tests/*.test.mjs
python -m compileall -q apps scripts tests
python -m pytest -q --ignore=tests/test_memoir_lanes_temporal.py $(find tests -maxdepth 1 -name '*browser*' -printf '--ignore=%p ')
```

The final command is the cloud/Linux broad-run command and intentionally reports
the inherited failures and missing PostgreSQL coverage; GNU find's -printf is not
portable to macOS. On the Mac, use the repository's normal full test command and
explicit local test paths instead.

## Fresh Mac handoff

1. Fetch this new branch, record its exact remote commit/tree, and use a new isolated
   checkout/worktree. Preserve the existing dirty checkout and all paused sessions
2. Verify the ordered two parents against the pins above; rerun focused checks and
   the full suite with the Mac's supported dependencies/runtime
3. Run disposable native PostgreSQL tests, actual Temporal/private-worker tests,
   source_kind × trace/no-trace cases, browser desktop/mobile and interrupted/retry
   flows, localization, composer fixtures, migration contracts, and production build
4. Keep inherited test failures visible; diagnose them separately from this merge's
   changes. Do not silently import excluded PR8 or change unrelated branches to make
   an aggregate check look green
5. Produce an exact-commit acceptance matrix. Original PR10/PR3 fresh live five-case
   evaluation, semantic source-claim behavior, judge availability, durable Langfuse
   readback, and provider usage accounting remain outstanding where previously
   unavailable. Offline/controlled tests are not live acceptance
6. Do not merge a target/main branch, deploy, or touch production based on this
   integration report. Any eventual merge still requires all applicable acceptance
   criteria, checks, and review to pass
