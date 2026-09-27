# Author-timeline skill contract

The server enables `memoir-author-timeline` only for a paid Family entitlement
backed by `STRIPE_PRICE_FAMILY`. The skill emits one bounded
`MEMORY_SPARK_AUTHOR_TIMELINE` marker with `timeline` and `life_periods` only.

Marker IDs are temporary. A persisted record is revised only with an explicit
`existing_id`; the server never performs fuzzy matching. `person_ids` refer to
canonical people already saved by the family-tree skill. Invalid markers are
discarded as a unit and removed from the visible reply.

The marker is merged into the same user/project `user_family_context` document
used by the family-tree skill. The response update envelope identifies the
source skill:

~~~json
{
  "family_context_update": {
    "schema_version": 1,
    "project_id": "project_123",
    "changed": true,
    "persisted": true,
    "revision": 2,
    "skills": ["author_timeline"],
    "added": {"people": 0, "relationships": 0, "timeline": 1, "life_periods": 0},
    "updated": {"people": 0, "relationships": 0, "timeline": 0, "life_periods": 0}
  }
}
~~~

The workspace reads the canonical document, not the marker or a renderer's
private state. Uncertain dates, visibility, and print-inclusion remain in the
stored records.
