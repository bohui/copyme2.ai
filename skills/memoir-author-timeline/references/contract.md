# Shared MemoryEvent service, version 1

`apps/api/memory_events.py` defines the schema-bound proposal contract. The model
has no database capability; trusted backend services resolve authenticated owner
and project scope and commit validated changes to PostgreSQL.

`read_user_memory_events` returns stable opaque IDs, event/period kind, revision,
lifecycle, supported stage/temporal placement, uncertainty, change sequence and
exact many-to-many source-version links. New proposal IDs are correlations only;
the server allocates identity. Existing proposals require `existing_id` and
`expected_revision`. Legacy mappings use stable aliases and honest unresolved
provenance rather than title-based merging.

`accept_user_narrator_source` commits the original source/version and its outbox
intent before optional reply delivery. `apply_user_memory_events` validates the
source manifest, quotes/spans, scope, placements, corrections and revisions, then
commits event revisions, links and processing together. `finish_memoir_timeline`
also checks the lane's expiring ownership token and total deadline. Empty results
advance processing; pending gaps cannot be skipped by the extraction cursor.
Validated proposals that repeat the same saved facts and evidence links also
advance processing without changing event revisions or the event change sequence.
New source links remain changes even when their words repeat an earlier account.

Author edits use `correct_user_memory_event`, `change_user_narrator_source` and
`unlink_user_memory_event_source`, with expected event revision/source version.
Corrections retain actor/origin, identity and authority, invalidate former/current
stage/year/event groups, and may refresh prose between checkpoints without adding
rounds. Original deletion/withdrawal invalidates dependent derived content and
restricted caches immediately; surviving evidence is reconciled honestly.

Composer reads these same canonical event IDs and original sources in a frozen
snapshot, never a second index. Source/event/policy manifests and manuscript
revision are rechecked at commit. Internal extraction applies to every authorised
narrator; premium timeline display and relationship-driven family-tree access
retain their server-owned entitlement checks. The private writing checkpoint is
five completed rounds by default, independently of the twenty-round allowance.
