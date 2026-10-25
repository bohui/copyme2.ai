# Composer review repair: offline validation and activation plan

This follows the failed live quality gate at PR #132 head
`71371668d5b6bd99e62bba1870ef51ae6ec01136`. That head's comparison, transcripts
and both raw live receipts remain unchanged. This repair has **no live model
measurements** and does not turn that failed comparison into acceptance.
Independent review and renewed live validation are still required.

Tested repair source commit: `747aff54f9bf4148054bf2de45af5976d001b27e`.
Subsequent report-only commits do not alter the tested source.

## Change and evidence boundary

The review prompt already said unsupported assertions block readiness, but its
strict schema excluded the editorial component's `verdict` field. Python and
SQL accepted `ready_for_user_review=true` with a nonblocking removal warning.
English-10 also saved an unsupported spatial detail with no findings. A citation
on the held-out Chinese paragraph did not express the omitted caption conflict.

Version 2 now has one strict typed contract for findings, per-field prose checks
and original contribution coverage. Unsupported, contradicted, uncertainty-lost
or attribution-lost verdicts cannot be cleared by warning/info severity or a
contradictory ready flag. Editorial warnings remain permissible. The host checks:

- Every rendered nonempty title/subtitle/text/caption/alt field, plus the draft
  title, has exactly one check with the exact text and valid current references.
- Every canonical original span has exactly one contribution entry containing
  the exact source version/span/quote. It is represented with actual matching
  prose excerpts, or explicitly deferred with a reason. A reference alone is
  insufficient. Irrelevant material is not forced into a focused sample.
- Worker admission recomputes these requirements from the fenced request and
  validated candidate; repair codes are recomputed from the same-page review.
- Both progressive and single-partition SQL commits recheck the semantic verdict
  gate and the exact saved prose/source witnesses before readiness.

These checks establish complete, correctly bound review evidence. **They cannot
independently prove entailment.** A model can still misclassify an assertion or
misdescribe a deferral; renewed live semantic review remains an acceptance gate.
The expanded review adds input/output bytes and may add latency; the earlier
fast-path deltas cannot be applied to this head. Existing budgets remain fixed.
The exact English-10 case is retained as an offline fixture. Tests reject both
its legacy empty-findings response and an empty-findings response whose complete
prose audit identifies the unsupported spatial assertion.

Rendering is performed after deterministic validation and before semantic review
so the requirements describe the actual assembled manuscript, including carried
text. The accepted rendering is reused for saving. Rendering remains private;
SQL commit still follows semantic acceptance. Existing three-attempt repair,
source/policy/ownership guards and generation pause remain enforced. No provider,
model effort, entitlement, consent, route or service settings changed.

## Persistence and compatibility

Version-1 reviews cannot authorize new version-2 commits. A saved legacy draft
is retained and reviewed again; successful preparation and drafting are not
repeated solely to upgrade the review. The unchanged-bundle reuse path also
requires a current complete review rather than trusting a legacy ready flag.
Legacy repair packets without the new optional host error codes remain readable.

Full review witnesses and original quotes remain in the existing fenced private
compose checkpoint. They are not duplicated into reader sections with narrower
source dependencies. The existing checkpoint source manifest includes every
batch original; a correction or withdrawal purges the corresponding checkpoint.
Bilingual SQL tests verify durable deferrals, reader output and this purge.
Existing stored ready roots are not retroactively re-reviewed or certified.

Public reader response shape and section storage remain unchanged. New review
JSON adds `contract_version=2`, `prose_checks` and `contributions`; findings now
require a typed verdict and bounded severity. The API and worker must agree on
this schema and the new host `requirements`/`review_errors` packet fields.
Mixed versions fail closed: an old worker rejects the new packet, and an old
writer's version-1 result is rejected by version-2 SQL. Do not roll out either
side independently and expect composition to continue.

## Offline checks

All provider outputs in these checks are controlled fixtures. Tests use the
repository's existing `tests/conftest.py` source-only adapter for unpublished
prompt edits. No application generation or paid judge ran in this repair.

Final applicable results: **377 Python tests passed, 11 explicitly deselected
pre-repair failures; 15 composer evaluation tests, 62 Node tests and 31 prompt
governance tests passed.** Full-suite green is not claimed.

The combined final results and exact commands are retained in the accompanying
[evidence](memoir-composer-review-repair-20261025.evidence.json). Coverage includes
real disposable PostgreSQL, canonical application/worker HTTP, privacy and exact
references, editorial warnings, contradictory verdicts, bounded repair, legacy
restart/reuse, explicit bilingual deferral, Unicode/boundary cases, large source
capacity, protected writing and reader persistence.

The three handoff failures were test-fixture contracts, corrected without
weakening product assertions:

1. Manual SQL lane seeding uses the table's English default; the bilingual
   fixture now explicitly initializes its selected edition before claiming.
2. Review metadata belongs to the fenced private checkpoint, not each reader
   section. The fixture now exercises the real checkpoint save RPC (boolean
   result), verifies its durable contents and verifies withdrawal purges it.
3. The Mandarin budget test implicitly inherited the existing 98,304 default
   while asserting 65,536. It now explicitly selects the supported 65,536 input
   setting; its original stricter budget and repair assertions are unchanged.

The broad run also exposed 11 workspace/consent/policy failures that were
independently reproduced at unchanged reviewed head `71371668` in a clean
temporary checkout. Their product assertions remain intact. The final scoped
cohort explicitly deselects only those cases; the full failing run and exact
baseline failure set remain in evidence. Fixture reviews are refreshed only
after their controlled final prose/references change. Short-batch dispatch
expectations now count the host preparation proof separately from model calls;
provider-reply fault tests retain the >4,000-character model fallback.

Original TDD failures, intermediate fixture errors and cleanup receipts are
preserved under `var/composer-response-optimization/20261025-quality-repair/`.
The initial directory-only Node invocation was invalid; its corrected explicit
file invocation runs the original 62 checks. No production database was used.

## Exact prompt changes and publication prerequisite

| Managed ID | Source | Existing pin | Source change |
| --- | --- | --- | --- |
| `memoir/skills/memoir-composer/review` | `skills/memoir-composer/prompts/review.md` | v3 | Version-2 response, exhaustive prose checks, represented/deferred coverage, negative-verdict precedence and editorial distinction |
| `memoir/skills/memoir-composer/shared/editorial-review` | `skills/memoir-composer/references/editorial-review.prompt.md` | v1 | Removes the incompatible example fields; aligns verdict/severity semantics and requires truthful complete audit/coverage |

`references/runtime-contract.md` documents the host behavior; it is a guide,
not a managed prompt. No receipt was changed and no version was fabricated.
Draft and pinned hashes are recorded in the evidence. The production loader was
checked read-only and rejects both edited managed files with
`Invalid Langfuse prompt artifact`, as intended until governed publication.

[AGENTS.md](../AGENTS.md) explicitly requires: **“Review prompt Markdown in Git
and merge it to `main` before publishing. Do not create Langfuse versions from
feature branches.”** [README's workflow](../README.md#versioned-prompt-artifacts)
and `scripts/publish_langfuse_prompts.py:main_revision` additionally require
local main to match live origin/main and a clean tree except generated receipts.
`--check` previews work only from eligible main; it is not a feature-branch
staging publisher. Publication must use real generated receipts and pin checks.

Supported preview now is offline source replay with real isolated SQL and
controlled HTTP/Node, plus the unit-tested publication guards. No supported live
unpublished-source staging mode was found in the inspected loader/publisher.
Do not patch the runtime loader, use fake receipts, or change serving services
to get around this prerequisite.

## SQL activation and rollback

Only `supabase/migrations/202610180001_initial_schema.sql` was edited, following
the repository's fresh-install rule. Disposable tests load it into new databases.
No migration was applied to an existing service, and there is no new migration
file. Fresh test databases already receive version 2 from that baseline.

An existing database needs an explicitly approved, transactional function upgrade:

1. Create `public.memoir_review_ready(jsonb)` and
   `public.memoir_review_covers(jsonb,jsonb)` from the reviewed baseline source.
2. Replace the same signatures of
   `public.commit_lifetime_memoir_lane_page_before_rework(uuid,uuid,bigint,jsonb,text)`
   and `public.commit_lifetime_memoir_lane_page_before_summary_windows(uuid,uuid,bigint,jsonb,text)`
   with their version-2 gate calls.
3. Verify both commit paths, current grants/owners/search paths and negative
   cases in a disposable/staging database before any serving activation.

No table/data transformation or new credentials is needed for this change, but
upgrading existing SQL functions is still a migration and needs authorization.
The entire fresh-install baseline must not be rerun against an existing database.

Coordinate API, worker, published prompt pins and SQL while composer work is
paused/drained through the existing operational mechanism, if separately
approved. Preserve originals and checkpoints. A code-only rollback to a
version-1 writer against version-2 SQL will stop saves. The safe immediate
fallback is to pause composition and preserve queued work; do not weaken the
semantic gate automatically. Any coordinated rollback of code/functions/pins
would restore the known old quality defect and needs an explicit decision.
None of these serving operations happened in this task.

## Safe next sequence and proposed live budget

1. Review this exact offline head independently. Keep PR #132 draft and keep
   the earlier failed comparison immutable. Resolve any offline findings first.
2. Obtain explicit authorization for the required governed merge/publication
   sequence and for any existing database/service upgrade. A fresh disposable
   database can load the reviewed baseline within the existing isolated-test
   scope. No merge is implied by the publication prerequisite. One possible sequence is a separately
   reviewed prompt-only main publication from a non-serving checkout, leaving
   existing serving checkouts/pins untouched, then using the genuine published
   receipts with the feature code in the disposable runtime. That sequence
   itself needs approval and compatibility review; it was not performed here.
3. After real pins and matching isolated API/worker/SQL are verified, obtain the
   renewed live call/deadline authorization. Do not spend the ten remaining
   candidate submissions during preflight.
4. Run the same six frozen bilingual checkpoints with each arm's own saved
   state, both restarts and withdrawal controls. Count every generation and
   repair, preserve failures, audit actual prose and explicit deferrals, and
   report new latency/usage without calling structural fixtures live evidence.
5. Return the new exact-head results for review. No merge or deployment follows
   automatically; the old Chinese-15 baseline remains censored and receives no
   successful-before latency percentage.

Proposed bounded revalidation is **16 future application submissions**: 12
nominal (draft+review for six eligible short batches) and four repair submissions.
Fourteen candidate calls were already consumed; ten remain under the original
24 cap. This proposal therefore needs **six additional authorized submissions**
and a new 30-minute revalidation deadline, for cumulative candidate cap **30**.
It uses zero judges and no additional baseline calls. The original aggregate
input/output token caps can remain: prior use plus 16 maximum-size calls stays
below 24×98,304 input and 24×16,384 output tokens. Per-call limits, route verification
and the stop on unexpected cost/route remain unchanged. This is a proposal,
**not permission**; no renewed calls or publication are authorized yet.
