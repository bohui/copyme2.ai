---
name: memoir-author-timeline
description: Use only when the server has enabled the paid Family legacy memoir feature. Extract the author's explicit life events and life periods for the Memoir timeline workspace while preserving storyteller uncertainty, privacy, and links to confirmed family-tree identities.
---

# Memoir Author Timeline

## Activation

The server loads this skill only after confirming a paid Family legacy
entitlement backed by `STRIPE_PRICE_FAMILY`. The entitlement decision is the
authority; never infer access from profile data, request fields, or browser
state.

## Workflow

1. Read the storyteller's current message and identify only events or life
   periods the author explicitly described or corrected.
2. Preserve expressions such as “around 1970”, “the late 1950s”, “when I was
   young”, and “I think”; use precision metadata without inventing exact dates.
3. Keep a life period separate from a point event. Include a broad place only
   when the storyteller stated it, and never store an exact private address.
4. Link an event to a family-tree person only with a canonical person ID from
   the saved workspace document or an explicit confirmed identity. Do not infer
   people from names, titles, photos, public history, geography, or culture.
5. Ask one short clarification when the event, date, or person is ambiguous and
   emit no marker for that detail. Put one machine marker on its own line after
   the visible reply.

## Marker

Emit compact JSON between these exact delimiters only when the turn adds a
clear, explicit author timeline item:

~~~text
[[MEMORY_SPARK_AUTHOR_TIMELINE]]{"timeline":[{"id":"e-school","title":"Started school","date_expression":"around 1964","precision":"approximate"}],"life_periods":[]}[[/MEMORY_SPARK_AUTHOR_TIMELINE]]
~~~

The top-level keys are only `timeline` and `life_periods`. IDs are temporary
correlation keys for this marker, not database IDs. Timeline items require
`id` and `title`; they may include `date_expression`, `precision`, `place`,
`person_ids`, `visibility`, and `include_in_print`. Life periods require `id`,
`title`, and at least one of `start_expression` or `end_expression`; they may
include `precision`, `place`, `person_ids`, `visibility`, and
`include_in_print`.

For both item types, `precision` accepts only `unknown`, `day`, `month`,
`year`, `range`, `approximate`, `age`, or `season`. Use `year` for an explicit
year such as 1960, `range` for a stated interval, and `approximate` for
“around 1964”. Omit precision when uncertain; `exact` is not a supported value.

`person_ids` must be canonical IDs from the saved family-tree document. This
skill does not create people. If the same turn explicitly introduces a new
relative, emit a separate `MEMORY_SPARK_FAMILY_TREE` marker for the tree skill
and use the saved canonical ID on a later timeline update.

When revising a saved event or period, include its canonical `existing_id`.
Omit it for a new record. Do not put Markdown, raw chat text, payment
identifiers, exact private addresses, inferred facts, or extra top-level keys
inside the marker. The application runtime validates and strips it before returning the
reply.

## Persisted workspace contract

The application runtime merges this update into the shared, versioned `family_context`
document for the authenticated user and Memoir project. It returns the
persisted document plus `family_context_update`; the envelope includes
`skills: ["author_timeline"]` when this skill changed the document. The browser
renders the persisted document directly and uses the semantic list fallback
when a visualization adapter is unavailable.

The database boundary is user-scoped by RLS, checks the expected revision, and
makes retries idempotent. The storyteller remains the authority for every date,
place, event, and life-period assertion.
