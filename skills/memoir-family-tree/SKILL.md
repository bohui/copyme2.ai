---
name: memoir-family-tree
description: Use only when the server has enabled the paid Family legacy memoir feature. Extract explicit storyteller-grounded people and relationship assertions for the Memoir family-tree workspace while preserving uncertainty, privacy, and canonical identity rules.
---

# Memoir Family Tree

## Activation

The server loads this skill only after confirming a paid Family legacy
entitlement backed by `STRIPE_PRICE_FAMILY`. The entitlement decision is the
authority; never infer access from profile data, request fields, or browser
state.

## Workflow

1. Read the storyteller's current message and use only the smallest private
   context needed to resolve an already-established person.
2. Extract only people, aliases, family titles, and relationship assertions the
   storyteller explicitly stated or clearly corrected.
3. Preserve uncertainty and distinguish parent, child, spouse, sibling,
   adoptive, step, guardian, and other assertions.
4. Never infer a relationship from surnames, titles, photos, public history,
   geography, age, or cultural convention. Ask one short clarification when
   identity or kinship is ambiguous and emit no marker for that detail.
5. Keep living-relative visibility and print inclusion explicit when supplied.
   Put one machine marker on its own line after the visible reply.

## Marker

Emit compact JSON between these exact delimiters only when the turn adds a
clear, explicit tree item:

~~~text
[[MEMORY_SPARK_FAMILY_TREE]]{"people":[{"id":"p-mum","name":"Mei","family_title":"mother"}],"relationships":[]}[[/MEMORY_SPARK_FAMILY_TREE]]
~~~

The top-level keys are only `people` and `relationships`. IDs are temporary
correlation keys for this marker, not database IDs.

People require `id` and `name`. They may include `aliases`, `family_title`,
`birth_date_expression`, `death_date_expression`, `living_status`,
`visibility`, and `include_in_print`.

Relationships require `from_person_id`, `to_person_id`, and
`relationship_type`. Supported types include `parent`, `child`, `spouse`,
`sibling`, `adoptive_parent`, `adopted_child`, `step_parent`, `step_child`,
`guardian`, and `other`; `direction` and `maternal_paternal` are optional.

When revising a saved record, include its canonical `existing_id` and include
every person referenced by a relationship. Omit `existing_id` for a new
record. Never match people only by similar names, titles, ages, or surnames.

Do not put Markdown, raw chat text, payment identifiers, exact private
addresses, inferred facts, or extra top-level keys inside the marker. The
The application runtime validates and strips it before returning the reply. If the same turn
also contains an explicit author-timeline item, emit one separate
`MEMORY_SPARK_AUTHOR_TIMELINE` marker for that domain.

## Persisted workspace contract

The application runtime merges this update into the shared, versioned `family_context`
document for the authenticated user and Memoir project. It returns the
persisted document plus `family_context_update`; the envelope includes
`skills: ["family_tree"]` when this skill changed the document. The browser
renders the persisted document directly and uses the semantic list fallback
when a visualization adapter is unavailable.

The database boundary is user-scoped by RLS, checks the expected revision, and
makes retries idempotent. The storyteller remains the authority for every
relationship and identity assertion.
