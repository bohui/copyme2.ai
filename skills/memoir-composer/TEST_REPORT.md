# Local verification

Date: 30 September 2026

Environment: Node v22.16.0, ICU 77.1. No model provider or network service was called by the test suite.

Command: `npm test`

Result: **55 tests passed, 0 failed** at the time this bundle was built.

## Tested categories

- Focused and broad free-preview selection; incomplete trial and retrieval gating.
- Explicit storytelling confirmation and full-composition authorisation.
- A short, one-period formal memoir; no forced complete-life requirement.
- Progressive preview versus paid full-draft mode preservation.
- Unique event IDs; invalid or cross-project references; source revocation.
- Derived-memory lineage resolution, orphan summaries and lineage cycles.
- Separation of assistant/historical material from personal testimony.
- Medium-specific image eligibility and missing-media failures.
- Exact quotation spans, fabricated dialogue rejection and Unicode code-point offsets.
- Exactly 7,000 accepted and 7,001 rejected; captions/alternative text included.
- Chinese segmentation without whitespace and punctuation handling.
- Counter-runtime mismatch and stale input fingerprints.
- Protected chapter edits, unapplied proposals, stale revisions and dropped-chapter prevention.
- Chronological order against supplied grounded period order.
- Complete event dispositions, formal outline/chapter consistency and carried over-limit chapters.
- Review-only artifact status; same-request idempotency key; policy/media invalidation.
- HTML escaping, restricted output content, unknown-field rejection and no arbitrary image fetching.

## Deliberate limitations

The test suite validates deterministic behaviour, not factual entailment or book quality. The 7,000-word boundary tests use synthetic repeated words to exercise the counter; they are not sample memoirs to publish. Small fixture narratives deliberately stay as short as their evidence.

No production database transaction, permission service, distributed event delivery, original photo resolution, real model composition, full PDF/EPUB build or printer submission was tested. Those integrations remain the application's responsibility. `references/editorial-review.prompt.md` specifies the separate source-to-prose review pass.

The JSON schemas are also checked against all example request/candidate packets during packaging. The CLI implements only the JSON Schema subset used in this bundle; it is not a general JSON Schema library.

## Private checkpoint extension (2 October 2026)

The suite now passes 57 tests, including an explicitly host-authorized five-round private sample with a truthful twenty-round free allowance, denied missing authorization, denied formal composition, and the unchanged free-limit gate. These synthetic tests do not establish live model availability.

## Response-stage extension (2 October 2026)

The suite now passes 58 tests. The additional case accepts optional stage/capture-order
metadata, checks fingerprint invalidation after stage reassignment, and rejects an
unknown stage. Existing packets without these fields still validate. Host integration
tests separately cover ordered retrieval, bounded incremental indexing, changed/deleted
dependencies and atomic PostgreSQL stage assignment. These checks use synthetic sources
and a disposable database; the new deployment migration remains unapplied.

## Progressive memoir extension (2 October 2026)

The suite now passes 60 tests. The progressive case adds ten distinct 31-round lives
across five China `zh-CN` profiles and five Australia `en-AU` profiles. It exercises the
private five-round checkpoint, twenty-round free-preview gate, review-only formal draft,
stable chronological chapter IDs, source-backed updates, photo rights metadata and
progressive enrichment. The browser companion checks both localized 31-round journeys
and the stage-3 structured delivery workspace. The worker responses are deterministic;
live model quality and semantic entailment remain separate review concerns.


## Sample title rendering (3 October 2026)

The suite passes 62 synthetic checks, including shared sample titles rendered once
in Markdown and HTML, distinct section titles retained, and canonical candidates
left unchanged. Backend checks also cover clean cached/private reader previews
without rewriting saved manuscript revisions or original testimony.
