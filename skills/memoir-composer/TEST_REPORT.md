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
