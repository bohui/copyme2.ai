# Parallel review and revisable replies

The optional `MEMORY_SPARK_PARALLEL_POLICY_REVIEW=1` path starts the current
source's privacy review and reply generation concurrently. It streams the reply
immediately using the previously allowed conversation. A new restriction
cancels that generation, erases its current message bubble, reloads the reviewed
context and generates a replacement in that same bubble. Earlier saved replies
and their displayed text remain unchanged. Only the final reviewed, validated
reply is committed.

This is an explicitly approved change in privacy semantics: a draft can mention
a newly excluded topic before the separate review finishes. Retraction cannot
undo reading those words, screenshots, or earlier transmission of context to the
provider. Previously committed restrictions remain in the model's input, and
authentication, source/version, lease, generation and preference checks remain
in force. Privacy review still runs in Lane A because final saving depends on
its result; it is not an eventual Lane B check.

## Execution

1. Accept the current source durably. Resolve any older pending policy first;
   speculative access cannot bypass older pending sources or policy inventory.
2. Select the language, assemble the bounded conversation and capture its exact
   fence. Start the two model requests together from that stable basis.
3. Stream only the top-level acknowledgement and question strings. JSON metadata,
   work proposals and provider reasoning never enter the text bubble.
4. Wait for the completed, exact-source policy decision before saving anything.
   With no restrictions, retain the draft and continue normal validation/save.
5. With any new restrictive control, cancel and settle the old model/worker
   stream, invalidate its revision, discard its queued text, reassemble context
   under the new fence and generate once more. Conservatively restart even if
   the draft happens not to mention the excluded topic; no extra LLM judge is
   added to decide whether it is affected.
6. A validation repair also starts a new visible revision. The existing bounded
   validation/incomplete-output retry policy remains; a revisable draft does not
   freeze its earlier acknowledgement. Failed/ambiguous review, failed generation
   or disconnect cannot commit the draft.

The new `lock_lifetime_draft_reply` admission is separate from normal publication.
It permits the latest exact source's single pending review, never a foreign owner,
stale fence, older pending source or pending policy inventory. After completion,
that draft admission requires an empty restrictive decision. Normal final
publication and database commits still require completed policy. Both API-to-worker
and worker-to-provider admission apply the same distinction.

## Stream and UI

The server sends `reply_revision` with a monotonically increasing integer, then
tags each `text_delta` with that revision. The server drops obsolete queued
envelopes; the browser independently ignores obsolete or untagged deltas once a
revision has started. Revision controls contain only the revision number so a
reset can arrive even after policy invalidates old personal-content sends.

The browser removes the old draft by grapheme clusters, then types the replacement.
Both animations use bounded steps; emoji and Chinese characters are preserved.
Reduced-motion settings replace immediately. Drafts are excluded from both browser
history caches, stale cached copies of the retrying turn are purged, and navigation
or failure clears the provisional bubble. Speech playback is offered only after
the final reply; provisional text is not an ARIA live announcement.

## Rollout and rollback

The flag defaults to `0` in the example environment and all relevant Compose
services. Enable it only with `reply-v2`, two lanes, matching API/worker code and
the updated fresh-install baseline schema. Ordinary JSON responses, cached saved
replies, replay of an already accepted unfinished turn and older contracts retain
the sequential path. This PR changes no model route, reasoning setting, prompt
Markdown or published Langfuse receipt.

Set the flag back to `0` in API and worker to restore sequential privacy review
for new requests. The browser remains compatible with unversioned existing text
events. Disabling it during an in-flight speculative turn can reject a later
dispatch; the original source remains saved for retry.

## Verification

The test suite covers direct and worker request bodies, actual isolated SQL
guards, concurrent dispatch, review-before-save, current-only replacement,
unchanged earlier collector records, cancellation of incomplete and completed
worker streams, Unicode/escaped JSON projection, stale queued revisions,
validation repairs, browser caches and reduced motion. Chromium also exercises
the actual chat stream parser and renderer together with synthetic stream frames.

The [live comparison](test-evidence/issue53-parallel-reply-20261022/report.md)
includes full synthetic transcripts and failure accounting. First draft text, the complete acknowledgement
retained in the final reply, final saving and browser paint are distinct metrics.
Source-backed API runs do not establish deployed-worker or full browser latency.

The candidate remains disabled: ordinary replies improved, but the live cohort
did not pass the full quality or 5/10-second latency gates.
