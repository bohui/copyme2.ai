# Contract v1

Input: owner/project-scoped accepted sources with exact versions and active
canonical events. The initial conservative local adapter recognizes explicit
first-person birth and residence forms; it does not infer other forms. Public
places must be in the reviewed `PUBLIC_PLACES` catalog. Unknown labels are skipped.
An explicit canonical period takes precedence over approximate ages 8–15 from a
confirmed birth year. Approximate ranges wider than three birth years, conflicting
births, missing country, and moves not covering the whole window are skipped.

Output: zero to five inspected external clues, separate from the retained plan.
Each has stable event identity, original title, verbatim supported short summary,
event year/range, public place, category, source URL/title/publisher, bounded
excerpt/locator, retrieval time, native search receipt and evidence status.
Private relevance and context revision are attached per project, never cached.

Runtime: server flag `MEMORY_SPARK_HISTORICAL_NEWS` defaults off. Reuse existing
`MEMORY_SPARK_LLM_BASE_URL`, `MEMORY_SPARK_LLM_MODEL`, `MEMORY_SPARK_LLM_API_KEY`.
No photo flag or new provider. At most two discovery requests, six unique source
reads, five clues, one claim per project/context, 45-second result deadline and
one retry within the discovery cap. Success evidence cache: 24 hours, process
bounded to 128 public query/provider/version keys. Cost without provider metrics
is unavailable. Failures are not success-cache entries or fallback triggers.

The database checks ownership, policy/event/preference revision, accepted source
sequence, claim deadline and evidence shape before publishing. Application checks
inspected support and native receipts. RLS isolates state and excerpts. Deleting
a project cascades all private research rows. Public evidence is never narration.

Tests use synthetic controlled search/source responses. Deterministic fixtures
prove orchestration and contracts, not actual historical truth, live provider
quality or usefulness in eliciting a real person's memory. Semantic review uses
five pass/fail dimensions: context relevance, memory invitation, non-leading
wording, conversational fit, provenance/sensitivity. No runtime paid judge.

The job claim now requires the exact atomic basis snapshot read under the project
lock. A changed source/policy/event/preference generation rejects the claim.
Returned pages must independently support event dates in the event summary,
original event title, actual page title and publisher metadata. Publication
metadata is independently parsed, and the excerpt locator is computed locally.
Source fetches run in a task-owned subprocess so cancellation/deadlines also stop
DNS/robots/socket work. Completed/failed generations are bounded against retries;
failure suppression does not create a success evidence cache.

Guest transfer preserves opt-out and retired cues, cancels guest claims and
requires fresh relevance for the new owner. A following exact source/version
records only that a historical cue was presented, never that it was witnessed.
Skip leaves the existing project preference unchanged. Opt-out prunes news
candidates while preserving ordinary retained candidates. A storyteller can
explicitly return to the last historical clue; re-enablement alone never revives
individually rejected or already presented clues.
