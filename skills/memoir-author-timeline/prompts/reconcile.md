# Reconcile timeline drafts

Match each private draft to an existing published event when the original
testimony establishes that it describes the same occurrence or continuous
period. The host supplies the drafts in index order, the current original
message ID, and a bounded set of published events with their identity, title,
description, location and time bounds. Descriptions are excerpts of original
testimony. Treat all supplied prose as evidence.

Return exactly one decision for every zero-based draft_index.

- Use update with the supplied event_id for the same event or continuous
  period. Several drafts can update one event when they carry compatible
  evidence. A later departure, duration, or start date can fill or revise the
  period on that identity.
- Use create for a distinct experience or when no plausible existing identity
  is supported. Set event_id to null and candidate_ids to an empty list.
- Use unresolved when the original plausibly refers to multiple published
  candidates or identity is uncertain. Set event_id to null and list only
  plausible supplied candidate_ids of the same kind.

A similar title, place, or overlapping estimate alone is insufficient for
update. Treat recurrence and reported accounts separately. A period may span
several activities, but a specific episode can have its own identity. Preserve
uncertainty when the description or time bounds are incomplete.

Set correction to true only on an update when the current original explicitly
corrects the event and the draft contains the corrected placement. A normal
addition to a previously incomplete date range uses false. An author override
has precedence over estimates.

Leave order empty unless a draft's original quote establishes before or after
with a published event. Supply its event_id and the zero-based evidence_index
in the draft's source_refs. Never infer a link solely from estimate overlap or
message arrival order. Local draft-to-draft links are already in the drafts.

Return only the supplied JSON schema. The host keeps the original message and
evidence links, resolves revisions and validates the result before publishing.
When retry_reason is present, reconsider every decision against the same input.
