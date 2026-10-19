# Issue 90: offline evaluation scope

This change extends `scripts/run_memoir_skill_evaluation.py` with a ten-skill
inventory and evidence-bound offline workflow. It is a draft implementation of
the independently runnable code scope of [issue 90](https://github.com/bohui/copyme2.ai/issues/90),
not full issue acceptance. Historical v2 builders, experiments, scores and the
standalone live runner remain intact. No live evaluation or publication ran.

## Commands and boundaries

```sh
# No credentials, clients, model calls or dataset writes are allocated by planning.
python scripts/run_memoir_skill_evaluation.py
python scripts/run_memoir_skill_evaluation.py --skill memoir-interviewer --locale zh-CN
python scripts/run_memoir_skill_evaluation.py --phase extract \
  --case memoir-memory-context/manual-blank/en-AU

# Runs available deterministic code. Missing external adapters remain unavailable.
# A report with unavailable quality/execution exits 1, honestly marked incomplete.
python scripts/run_memoir_skill_evaluation.py --execute \
  --max-skill-calls 0 --max-judge-calls 0 --output-root /tmp/issue90-offline-run

# Explicit synthetic application execution allocates a disposable PostgreSQL cluster.
python scripts/run_memoir_skill_evaluation.py --execute --controlled-application \
  --case memoir-story-game/publication/en-AU --output-root /tmp/issue90-game-run
# Play additionally requires a task-owned loopback source frontend and Chromium.
# Add --browser-url http://127.0.0.1:<allocated-port> for a selected play case.
# Explicit browser regression selection (requires that source frontend):
MEMOIR_BROWSER_URL=http://127.0.0.1:<allocated-port> \
  python -m pytest tests/browser_skill_eval_application.py
```

Repeat skill, phase, locale or case flags to select a subset. A contradictory or
empty selection fails before services or result directories are allocated. The
new phase names describe the actual task (interview, extract, progressive,
proposal, integration, review, group, discover, publish, play). The historical
v2 trigger/delivery entry remains `legacy_main()` for regression reproduction;
the CLI no longer implicitly publishes datasets when `--execute` is supplied.

The test seam is `main(argv, services=...)` or `await run(plan, directory, ...)`.
Tests inject skill completions, independent judge completions, configured photo
discovery/source reads, historical discovery/source reads, and composer model
completions. Production packet builders, validators, photo source parsing,
historical evidence checks and progressive composer orchestration still run.
Composer checkpoint I/O is explicitly in memory. The optional application adapter
uses real admission, source/event persistence, edition/consent/review/publication
RPCs and independent SQL readbacks in its own subprocess and disposable cluster.
It supports both locales for all eight game families plus interviewer grounded
questions and exact-testimony events. Other canonical scenarios remain unavailable.
Its external worker/model replies and Auth identity are controlled synthetic
fixtures; counted fixture dispatches explicitly record `live_model_dispatch=false`.
The adapter binds a separate receipt to exact task, output, source readbacks,
dataset snapshot and run identity, and verifies cluster removal before accepting it.
Receipt verification receives the runner's current run/source identity directly,
including a unique invocation ID, and requires an exact match to dispatch records
consumed by that invocation. A prior passing receipt cannot be reused in a new
run, even if its supplied run ID and hash are rewritten. The runner rejects zero
dispatch allowance or expired deadlines before invoking an application adapter.
Partial/failed native execution retains its consumed dispatch count. Historical
receipts remain preserved but do not establish delivery in a new run.
No fixture grants authority
on a real account. Application behavior and configured model routes are unchanged.

## Identities, datasets and judges

Inventory is the union of the background registry and runtime prompt owners.
Preflight rejects unmapped additions, including foreground prompt owners without
a skill package. Every skill has eight named scenario families, each with paired
`en-AU` and `zh-CN` tasks: 80 families and 160 concrete task items. Tasks include
action, scope, source/fixture data, required/forbidden behavior, gold facts and
required witnesses. Application packets exclude gold and judge rubrics.

Identity is `skill/case/locale`; hosted item IDs derive only from that identity.
Content changes have separate hashes. Stable dataset names are
`memoir/evaluation/skills/<skill>` for the ten skills, plus
`memoir/evaluation/workflows` and `memoir/evaluation/judge-calibration`.
Execution selection never retires unselected catalog items. Local plan timestamps
are labelled `local_plan_timestamp`; they are not claimed as hosted snapshots.

Controlled reconciliation tests inspect every selected asset before writes,
bind reviewed differences to observed content, require conditional writes,
read back each write, resume partial writes, reactivate or archive stable items,
and reject historical namespaces and ownership conflicts. The store is an
offline protocol, not an unverified SDK publisher. A live implementation must
verify the deployed release and its concurrency protections before use.

Twenty named evaluator definitions reuse the contract implementation and one
shared judge policy composed with ten skill rubrics. Judge text is registered
with the existing merged-main publisher as unpublished evaluation sources.
Runtime/export consumers require real receipts; no new receipt exists here.
The normal main-only publisher can publish these sources after review and merge.
A prompt publication does not update a compiled evaluator definition: that needs
a separate inspected/reviewed definition update and numeric evaluator readback.
Rules are disabled, synthetic-dataset scoped, and omit managed quality execution
when the SDK executor is selected. The runner rejects simultaneous judge executors.

The injected judge adapter keeps source/output data separate from instructions,
requires categorical judgments and valid supplied evidence citations, forces
critical violations to fail, and abstains on malformed or missing evidence.
Transport-owned response IDs, model and usage cannot be overwritten by model
JSON. The evaluated model cannot judge itself. Controlled fixtures can inspect
draft judge text; ordinary judge dispatch requires published component pins.

Skill/provider and judge dispatch budgets are separate. Failed/cancelled requests
consume allowance. Timeouts, deadlines and evidence size checks precede dispatch.
All planned rows are saved before execution and survive cancellation, unavailable
runners and exhaustion. Provider usage, internal attempts and cost remain unknown
when not supplied. Hosted contract scoring requires an independently obtained
application receipt with matching run/item/task/packet/output/source/dataset
identities. Hosted score readback checks named evaluator versions and exact
trace/observation/input/output identities, not just counts.

The read-only `read_experiment_scores` seam adapts PR93's useful v4 SDK
experiment checks while retaining this suite's receipt boundaries. It accepts an
injected client, bounds pagination, compares exact input/gold/output and item
metadata, and requires matching dataset snapshot, observation subject, named
score value and evaluator provenance. Metadata-only revisions remain reviewed
content changes. Tests deserialize controlled responses with the installed SDK's
own parser. No client or credentials are created, and this does not verify the
deployed server, publish assets or enable a live CLI path. PR93's smaller catalog
and publication-on-execution behavior were not imported.

Foreground packets also reuse PR93's governed immediate-selector approach:
production strategy/language/continuity composition, actual wire schema and
independent question/current-intent expectations for pause, redirect, correction
and pacing. The existing stable family identities and bilingual facts are retained.

Contract, execution, positive delivery, quality and human calibration remain
separate. Negative passes do not count as positive delivery. Verified disposable
application results have `canonical_delivery=true` only within their declared
synthetic phase; every result retains `live_delivery=false`. Browser play uses the
real source frontend, local API routes and SQL, checks movement and original
dialogue, reload/new-context recovery, and persisted consent revocation. Browser
network access is restricted to the task-owned origin and fulfilled Auth fixture.
These observations do not certify deployed or live model/browser acceptance.
Calibration development and holdout IDs are
disjoint and carry no invented human labels; all quality scores remain advisory.

## Issue acceptance matrix

`Offline` means implemented and controlled-test supported. `Partial` identifies
coverage whose real application witness or semantic acceptance remains open.
`Gate` requires the later authorized live/publication/human work.

| Issue stories | Offline result | Remaining acceptance |
| --- | --- | --- |
| 1, 5: inventory and unmapped-owner rejection | Offline: ten skills, registry/prompt-owner union, interviewer included | Keep preflight as skills evolve |
| 2–4: stable datasets, history, identity and snapshots | Offline: twelve definitions, stable IDs, content diffs, archive/retry/readback fixtures | Gate: native hosted snapshots and real conditional-write behavior |
| 6–7: zero-call plans and bounded selection | Offline: full plan, repeated filters and cross-phase rejection | None for local planning |
| 8–9: grounded interviewer and current intent | Offline: bilingual tasks, actual governed selector schema/validator, explicit pause/redirect/correction/pacing reasons and foreign-candidate rejection | Gate: useful live questions and independent semantic judgments |
| 10: exact event testimony | Offline: actual wire schema before normalization, strict Unicode quote offsets, source versions and gold minimums; disposable exact-testimony source/event readback | Gate: semantic grounding/correction quality and canonical witnesses for remaining families |
| 11–12: progressive composition and independent quality | Offline: all eight composer families; real orchestration, correction/withdrawal, retained passages, private output | Gate: live output, persisted canonical checkpoints, independent published judge quality |
| 13–14: family identity/direction and unwired reporting | Offline: production marker validation, independent direction/count checks; canonical integration unavailable | Family runner remains unwired by design; isolated proposals never imply integration |
| 15: manual profile values/blanks | Offline: actual profile packet/schema/validator, exact original spans, omission/gold checks | Gate: live model quality and persisted manual-lock readbacks |
| 16–17: place extraction and deterministic grouping | Offline: actual place validation; eight grouping families in both locales, zero skill model dispatch | Gate: live place extraction semantics and visible label quality |
| 18–19: configured photo discovery and honest metadata/rights | Offline: configured leads and inspected HTML; PR88 production capture-year/GPS ranking with independent order gold; PR94 production compound scopes and image-geography precedence | Partial: valid duplicate capture assertions are still dropped by the API on current main; live visual quality and photo persistence/browser acceptance remain open |
| 20–21: source-inspected history and privacy separation | Offline: case-specific production hypothesis/minimization, all eight adversarial source fixtures in both locales, inspected-page validation and conflicting/unsupported/date/injection checks | Gate: live provider/source readbacks and privacy review |
| 22–23: game phases and permission boundaries | Offline: all eight families through actual disposable application authority, generated candidate staging, exact review/publication readbacks, revoked/missing/stale/person-permission denials; real frontend play/recovery/revocation in both locales | Gate: authorized live provider and deployed browser acceptance; no real consent granted |
| 24: equivalent bilingual facts | Offline: 160 paired items; both composer locales and all grouping/profile locale fixtures | Gate: native-speaker semantic review |
| 25–27: twenty evaluators, composed rubrics and evidence citations | Offline: named definitions, draft policy/rubrics, pin gating, strict independent judgment handling | Gate: merged-main prompt publication, deployed evaluator/rule API verification and actual definitions |
| 28–29: separate dimensions and gold exclusion | Offline: separate report columns/denominators, positive-case flags, model packets without gold/rubrics | Gate: full live output coverage |
| 30–31: budgets and exclusive executors | Offline: failed/cancelled dispatch accounting, independent budgets, no dual executor | Gate: provider internal attempts/cost remain unknown absent provider accounting |
| 32–33: version/evidence binding and publication preflight | Offline: source/prompt/compiled hashes, receipt matching, full-content reconciliation including metadata-only updates, bounded installed-SDK IO/metadata/score readbacks | Gate: real numeric evaluator versions and hosted readbacks |
| 34: calibration development/holdout | Offline: separate datasets/items, null human labels, advisory-only scores | Gate: independent human labels, accepted agreement and critical-violation behavior |
| 35–36: incomplete reports and controlled CLI fixtures | Offline: all selected rows retained; service fixtures drive CLI/adapters/contracts/judges/reporting | Gate: live browser/provider delivery is not established by fixtures |

## Validation and remaining gates

The original machine-readable evidence is [issue90-offline-checks.json](test-evidence/issue90-offline-checks.json).
Follow-up review/native/browser evidence is in
[issue90-offline-followup-checks.json](test-evidence/issue90-offline-followup-checks.json).
Selective PR93 integration and updated-main reruns are recorded in
[issue90-integration-checks.json](test-evidence/issue90-integration-checks.json).
The independent native receipt replay finding and its fix are recorded in
[issue90-receipt-replay-checks.json](test-evidence/issue90-receipt-replay-checks.json).
Check counts overlap between runs and must not be added into a campaign count.
Task checks used an external-socket denial guard, the repository's isolated-check
environment allowlist, task-owned outputs, and disposable native PostgreSQL Unix
sockets/allocated loopback ports. The supervisor verified allocation cleanup.
Langfuse SDK 4.18.0 was installed into a task-only dependency directory for offline
regressions and interface inspection; no client connected to a deployed instance.

The broader evaluation selection has ten failures reproduced on unchanged base
`04ed95e258bb25dd1846e931dbaf3948eb1aff5e`: retired trajectory fixtures lack
canonical publication context. A separate background workflow expectation also
fails on that base: it expects `integration_unavailable`, while the game endpoint
returns `authenticated_game_workflow_required`. These eleven baseline failures
are reported separately and were not repaired by changing production behavior.
On updated main `d4c6f58d15450df69742342d1b6104bdf04f4772`, the broader
selections still have those ten evaluation failures and one photo capture failure:
`test_consistent_duplicate_image_records_preserve_all_assertions[app]` drops a
valid image with compatible year/day assertions. All eleven were reproduced in
an unchanged detached main checkout. The original game reason mismatch remains
historical baseline evidence; it is not part of that latest eleven-test selection.

An initial catalogue check lacked the worktree's Node dependency path; sharing
the existing local dependency directory made the catalogue check pass. Two
initial command selections referenced nonexistent filenames and ran no tests;
corrected selections and the original TDD red result are retained in evidence.
No executed test was skipped in the recorded focused checks.

Live model/provider requests, all Langfuse writes, deployment, real consent,
customer data, configured-database changes, merging PR92 and human calibration were
excluded from this execution. Publication is blocked pending reviewed main and
actual pins; the deployed evaluator/rule release is unverified. Full live application
and browser acceptance remain incomplete. PR88 is external-owned
photo work and was neither edited nor duplicated. Its merged ranking API and
PR94's merged locality implementation are reused through updated main. Earlier
locality diagnostics are retained in historical evidence. Current controlled
cases check the new source-role rules: compound query support, rejection of
foreign image geography, and precedence of explicit image geography over a
caption's apparent place name. These local checks do not establish general
provider, visual-quality or deployment acceptance.
