# Conversation attribution implementation (#77)

Implements [the specification](Memoir_Conversation_Event_Attribution_Spec.md) after #75 and #79. Attribution remains in the existing Lane B timeline writer; no new skill, worker, classifier, periodic schedule, or composer authority is introduced. Comfort/explore/shape are independent interviewing strategies, not attribution dispositions or admission controls.

## Ownership and persistence

- Accepted narrator sources retain the existing stable ID, version, sequence and original text, even when Lane A fails before saving a reply. Completed rounds still require a saved conversation.
- The canonical timeline pass commits exact primary event/source evidence through the existing writer. New `user_memory_attribution_window` rows account for remaining spans, without copying their text. `user_memory_attribution_receipt` fences duplicate page effects and the full auxiliary result.
- Passage decisions follow the immutable source version, not the project-wide policy epoch (which also advances on unrelated author corrections). Edits/withdrawals invalidate their own versioned decisions. Current-policy admission/read/publication fences remain mandatory; keeping a classification does not authorize evidence use.
- `user_memory_event_place` attaches coarse setting/origin/destination claims to one canonical event and its own exact primary passage. A shared source is insufficient. Changed place claims advance the canonical event revision; unchanged replay does not. Source-keyed place journeys remain separate workspace navigation, not biographical evidence.
- Actual delivered-question receipts live in `user_memory_delivered_context`; `user_memory_reply_context` connects the immediately following accepted source to that delivered reference. Current source, event revision, execution, preference and policy checks determine whether it is still usable. Recent-event order alone confers no authority. Context-only associations cannot become testimony, stage credit or a fresh map cue.
- Migration: `supabase/migrations/202610170004_conversation_attribution.sql`, ordered after phase retirement. It adds no production backfill. Existing primary evidence is projected conservatively; processed legacy gaps remain unresolved, not implicitly linked.

## Admission and outcomes

The small exact-match rules recognize greetings, thanks, pauses, literal name-only introductions and vague confirmations. A mixed story/control or new/corrected fact still enters bounded reconciliation, including when A suggested `reply_only`. Privacy withholding is separate from non-story. Profile parsing remains independently eligible under #75.

| Disposition | Meaning |
| --- | --- |
| `pending` | This current source range has not been reconciled. |
| `linked` | Exact current primary evidence connects the passage to a canonical active event; optional time/place may remain unknown. |
| `non_story` | A bounded explicit non-story/control decision, without an invented event. |
| `unresolved` | Work was attempted/accounted for, but event identity or supported meaning remains unresolved. No automatic retry spin. |
| `withheld` | Privacy excludes the passage. It is neither non-story nor resolved testimony. |

Empty extraction accounts for attempted windows but leaves unsupported testimony unresolved. Accepted sources are processed independently of five-round composer milestones. Existing bounded windows, per-lease page limits, retry/restart behavior, expected event revisions, author overrides and removed-link exclusions remain authoritative.

## Authorized readback and downstream contract

- `GET /v1/story/sources/{project_id}/{source_id}/attribution`: owner/project/current-source read under the existing Family timeline-display gate, checked before canonical retrieval. At most eight items per page, exact Unicode offsets, canonical event context or a distinctly labeled `context_event`. `complete` means whole-source decision/attempt coverage, **not** semantic resolution. `resolved` requires every passage to be linked or genuine non-story. `page_complete` and `next_cursor` describe pagination separately.
- Existing source-list items retain a free-access bounded per-source `attribution` summary with counts and a Family-gated retrieval pointer, without embedded event/time/place details. Worker outcomes include `attribution_pages` with truthful coverage and `timeline_method` (`rule` or `model`). These are the integration inputs for #76; this ticket does not render thinking-step UI.
- `GET /v1/story/events/{project_id}/{event_id}/places`: at most eight current evidenced associations per page, under the existing Family timeline-display gate. Each row has `status: supported | conflicted`. Distinct places for the same event/role are conservatively treated as unresolved alternatives, not two established locations. Repeated support for one place and distinct origin/destination roles are not conflicts. No automatic winner or destructive supersession is inferred.
- Inline event context contains at most two unconflicted places, `place_conflicts` listing unresolved roles, and an explicit completeness/retrieval pointer. Conflicted roles are omitted from authoritative places and set `places_complete=false`; the paid paged read retains the evidenced alternatives for inspection. Timeline and composer receive the same uncertainty. Optional unresolved placement does not undo a supported passage-to-event link. Cursors reject changed source, event, policy, preference or attribution state.
- Both reads use the existing canonical read-publication fence, not a relabeled post-hydration snapshot. Source edits/withdrawal delete new derived source associations and invalidate context; author-removed primary links cannot keep place claims visible.
- Composer requests include `context.attribution_coverage`: summaries for the bounded sources (at most 21) and canonical context for the bounded events (at most eight). Its scope is explicitly not lifetime-complete. Source/evidence citation guards remain unchanged. The metadata is not additional testimony, and optional unknown placement does not forbid supported prose. Attribution accounting alone does not change the prose dependency/event manifests.
- Numeric age estimates retain original age wording and permit only the supported birth-year-plus-age result with at most a one-year uncertainty interval. Both validation layers reject relative-attributed birth anchors; SQL also rejects an inner narrator-looking quote inside reported speech. Missing/unsafe anchors leave years unknown. UI/profile guesses are not substitutes for original evidence.

These new provenance reads are backend interfaces for #76; no native/web UI or mobile operation allowlist is expanded here. Existing rollout flags remain unchanged/default-off.

## Verification scope

`tests/test_conversation_attribution.py` crosses the confirmed authenticated conversation → real Lane B worker → disposable PostgreSQL → authorized HTTP readback seam. Only external model/PostgREST transports are controlled; actual canonical SQL and publication guards execute. Composer coverage is exercised via the real receipt broker and composer worker. The tests do not seed final attribution links or dispatch through an alternate test-only worker.

Covered behavior includes empty/partial extraction, Unicode/repeated spans, selective multi-event geography, continuing episodes, delivered versus merely recent context, blocked/failed B with responsive A, failed A with accepted evidence, worker restart, malformed auxiliary evidence, source edits/withdrawal during extraction, author corrections/removal, read scope/pagination, narrator age anchors and automatic strategy independence.

No production migration, deployment, real memoir audit, paid provider evaluation or live-model semantic-quality measurement is performed. Broader legacy-test failures, if any, are recorded in the PR separately from passing targeted checks.
