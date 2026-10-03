# Family-tree skill contract

The server enables `memoir-family-tree` only for a paid Family entitlement
backed by `STRIPE_PRICE_FAMILY`. The skill emits one bounded
`MEMORY_SPARK_FAMILY_TREE` marker with `people` and `relationships` only.

Marker IDs are temporary. A persisted record is revised only with an explicit
`existing_id`; the server never performs fuzzy identity matching. Invalid
markers are discarded as a unit and removed from the visible reply.

People may carry an optional `introduction` of at most 1,200 characters.
It contains only storyteller-grounded details, preserves uncertainty, and is
shown when the person is selected in the tree. Older records without it remain
valid and show their recorded names, family titles, aliases, and dates.

The marker is merged into the shared `user_family_context` document:

~~~json
{
  "schema_version": 2,
  "project_id": "project_123",
  "revision": 2,
  "updated_at": "2026-09-26T00:00:00Z",
  "people": [],
  "relationships": [],
  "timeline": []
}
~~~

The agent response includes the canonical document and an update envelope:

~~~json
{
  "family_context_update": {
    "schema_version": 2,
    "project_id": "project_123",
    "changed": true,
    "persisted": true,
    "revision": 2,
    "skills": ["family_tree"],
    "added": {"people": 1, "relationships": 1, "timeline": 0},
    "updated": {"people": 0, "relationships": 0, "timeline": 0}
  }
}
~~~

The Supabase RPC is keyed by authenticated user and project, checks the
expected revision, and treats a replay as a no-op.
