# Composer craft integration: review contract 3

This follows the manual-only snapshot `7f2d4169ee0845ed8efa8c165463cd2f10d03749`.
That snapshot and the historical failed Luna comparison remain immutable. The
new change integrates the requested literary criteria into actual writing and
review instructions and the canonical application/worker/SQL path. It is an
offline-tested candidate, not serving activation or live quality acceptance.

## Actual instruction and runtime behavior

Shared narrative enrichment now guides writing and review with focus, scene
craft, author voice, supported vulnerability, retrospective reflection,
transformation, reader resonance and fairness. Respect the author's whole-life
or focused scope, childhood viewpoint, voluntary disclosure and unresolved
ending. Never invent speech, sensory facts, feelings, motives, diagnoses,
admissions, hindsight or redemption to improve a rating. The compiled progressive
writer inherits this shared guidance; there is no additional model phase.

The existing review call returns `contract_version=3` and a private `craft`
report alongside its hard prose/contribution audit. The report has exactly eight
unique ratings, bounded exact source/prose excerpts, applicability, 0–3 score or
null, confidence/basis, reason and optional suggested follow-up. There is no
aggregate or passing craft threshold. All-zero scores and justified NA remain
compatible with ready, source-supported writing. High scores cannot clear a
negative semantic verdict, privacy hold, stale source or invalid SQL proof.

Hard grounding checks still assess actual assertions, attribution, uncertainty
and truthful represented/deferred contributions. Excerpt membership establishes
provenance, not entailment or literary merit. Advisory self-review is not an
independent judge or human acceptance. Actual model quality remains a live gate.

`requirements.craft_context` binds partial/formal stage, selected output kind,
author editorial instruction and follow-up allowance to the host request.
Missing material yields insufficient evidence, not a failing author. Current
canonical composition permits zero follow-up questions, so suggestions must be
null. Excluded/paused topics and explicit refusal also disable suggestions.
Even where a host explicitly permits one, it stays private and never becomes
memoir prose, a queued interview or an automatically delivered question.

Malformed craft metadata or stale/mismatching craft excerpts use review-only
repair of the saved draft. Hard semantic failures retain bounded draft/review
repair. Both share the existing three-attempt ceiling and retain checkpoints.
The worker recomputes requirements/error codes and demands same-page proofs for
the candidate and any prior review supplied as repair feedback. No client may
invent repair instructions or use an assessment from another page.

## Persistence and compatibility

The existing fresh-install SQL baseline gains the pure
`memoir_craft_review_covers(jsonb,jsonb,jsonb,boolean)` helper and a version-3
check in `memoir_review_covers`. It checks complete typed ratings, score/null
consistency, exact current original/prose witnesses and follow-up permission;
it never imposes a minimum craft score. Both existing commit paths already call
the review predicate. There are no new tables, columns or reader response fields.

Version-2 saved drafts and completed bundles remain reusable as writing, but
their reviews cannot authorize a new version-3 commit. Refresh the review alone.
The real worker/SQL restart case saves a version-2 checkpoint and obtains a fresh
version-3 review without another draft. Existing ready roots are readable and
are not retroactively re-certified. Mixed old/new writers fail closed.

Assessment evidence remains in the fenced private compose checkpoint, not each
reader section with narrower dependencies. Bilingual SQL coverage includes a
craft observation referencing a deferred original absent from reader prose;
withdrawal of that original purges the whole dependent checkpoint. Privacy,
ownership, protected text, retries and source manifests retain their prior gates.

An existing **version-2** database would need the new helper and a replacement
`memoir_review_covers` function. A database at serving main `ef42b2b` also needs
the earlier `memoir_review_ready`/`memoir_review_covers` helpers and strengthened
`commit_lifetime_memoir_lane_page_before_rework` and
`commit_lifetime_memoir_lane_page_before_summary_windows` bodies. Such existing
service upgrades require separate approval. Only fresh disposable test databases
were loaded here; the entire baseline must never be rerun on an existing service.

API, worker, published pins and SQL predicates must be coordinated. A code-only
rollback to a version-2 writer against version-3 SQL stops saves. The safe
fallback is to pause composition through the existing approved operational
mechanism and preserve queued work/checkpoints; do not weaken the gate silently.

## Calibration and experimental provenance

The Chinese attributed recollection now retains uncertainty that the father
spoke, not merely uncertainty about his exact words. Declined-disclosure cases
have structured follow-up consent plus a fixed refusal assertion. Known negative
labels are protected against accidental relabeling; these remain controlled
contract replays, not detection of unseen semantic defects. Confidence/basis is
criterion-specific and includes medium/low judgments where context or reader
reception is unknown. The calibration labels still require independent re-review.

The proposed Sol experiment now predeclares n=1 per checkpoint/arm, paired arm
order, fresh application state, provider cache-hit reporting, exploratory analysis
and treatment of failed/censored/unmatched outcomes. The 42-call proposal remains
unapproved; unused historical quota does not transfer without explicit approval.
The old Luna transcripts, receipt hashes, failed quality gate and censored
Chinese-15 baseline row are unchanged. This change establishes no live speedup.

## Validation boundary

TDD receipts preserve the initial rejected version-3 report, the unwanted
craft-only redraft, SQL version mismatch and both calibration defects before
their corrections. Focused tests cover zero scores, NA, exact excerpts, foreign
versions, duplicate/missing criteria, boolean/out-of-range scores, forbidden
follow-ups, private allowed suggestions, actual compiled instructions, same-page
repair proofs and version-2 review-only restart.

The first broad run had 473 passes and one failure: compiled draft instructions
were 10,959 bytes against the existing 10,000-byte guard. The shared wording was
compacted without dropping criteria or source/privacy constraints. The guard and
strict input-budget assertions were retained; the focused budget rerun passed.
The final broad rerun passed **474 Python tests**, with the same 11 independently
confirmed baseline failures explicitly deselected. The final composer evaluation
passed 15; prompt governance passed 31 on each branch; Node checks passed 62.
The focused runtime/SQL boundary cohort passed 81. Full-suite green is not
claimed. Exact commands, source hashes, red/intermediate receipts and verified
cleanup are in the accompanying evidence.

All model outputs in these checks are controlled fixtures. Offline source replay
uses the repository's existing test-only unpublished-source adapter. The real
runtime loader rejects all three edited sources with unchanged receipts. No
Langfuse publication, generation, judge spending, browser observation, existing
service migration or deployed-worker acceptance occurred.

## Publication scope and remaining approval gates

| Managed ID | Source | Existing published pin |
| --- | --- | --- |
| `memoir/skills/memoir-composer/review` | `skills/memoir-composer/prompts/review.md` | 3 |
| `memoir/skills/memoir-composer/shared/editorial-review` | `skills/memoir-composer/references/editorial-review.prompt.md` | 1 |
| `memoir/skills/memoir-composer/shared/narrative-enrichment` | `skills/memoir-composer/references/narrative-enrichment.md` | 1 |

These are three unpublished source edits, not three already published new
versions. Numeric versions must come from genuine receipts. Skill/runtime guides
document the integration but are not additional managed prompts. The source-only
PR #133 counterpart must contain exactly these three files; code, SQL, fixtures
and guides remain in PR #132. Both affected exact-head reviews must be renewed.

AGENTS/README require reviewed prompt sources merged to main before publication.
After explicit approval of this expanded three-source scope, publish only those
IDs from a clean, separate nonserving main clone matching live origin/main.
Preserve hook governance and inspect a scoped preview before publication; do
not trigger an unscoped main-pull hook or pull into the bind-mounted serving
checkout. Review real generated receipt changes and exact remote pin/template
checks before preparing a synthetic isolated candidate. Do not merge the
combined PR merely to test it. No fake receipt or feature-branch publication is
an acceptable substitute.

The final authorized read-only route inspection at 2026-10-25 09:15 UTC found
`gpt-5.6-sol` in the existing Memoir consumer catalog. Its configured target is
`openai/gpt-5.6-sol`, requested effort high, outer retries zero and token prices
zero. No generation verified actual serving, effective effort, internal fallback
or billing. The shared legacy model
setting also affects unrelated skills, so model-phase isolation and a reviewed
Sol bound remain separate prerequisites. No provider access or model setting was
changed here. See the [Sol plan](memoir-composer-sol-plan-20261025.md).

The user subsequently authorized task-related pushes and exact-head conditional
merges after review, plus recoverable cleanup of completed task worktrees. This
does not allow stale-head merging, production migration or serving activation.
The exact expanded three-source publication scope must be returned to the parent
before execution. The new 24+18 Sol budget is conditional on verified subscription
routing, independently reviewed sources and genuine pins; no generation ran.
Both current task worktrees are still needed for review/live validation. Older
unique-content composer worktrees remain untouched. The serving checkout and
unrelated work are unchanged by this task.
