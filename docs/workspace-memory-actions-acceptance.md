# Workspace memory actions: implementation and acceptance record

Follow-up to PR #61. Scope approved on 2026-10-13: remove the persistent
comfort/explore/shape selector from chat and expose concrete tasks in the workspace.

## Product behaviour

- **Add a memory** starts a conversation around the selected life stage and keeps
  any unsent words. Selecting it creates no narrator source or completed round.
- **Explore this memory** starts from an active, owned canonical event and its
  exact revision. Existing details guide the next question without becoming new
  testimony.
- **Rework this section** accepts a bounded writing instruction for saved prose.
  It runs the existing canonical composer for that partition and presents a
  proposed replacement. The current text remains available until the storyteller
  accepts the proposal through the existing review flow.

Workspace focus is temporary, scoped to the current owner/project/navigation.
It seeds the first accepted turn, then subsequent turns follow the conversation
without resending an obsolete event revision. A visible topic cue can be cleared
with **Finish this topic**; reload clears it. Selecting a task does not insert
synthetic narrator words. Retries preserve the original turn and frozen focus.

Collector guidance adapts warmth and depth to the latest message, follows topic
changes and honours a wish to finish. The backend phase API, saved preferences
and direct spoken/typed requests remain compatible. Workspace tasks do not write
those preferences, alter the completed-round count or grant draft access. The
existing workspace/draft visibility and allowance rules remain in force.

## Storage and composition contract

Focus reads require an owned project. Event exploration checks the active event
revision and every original source dependency. Validation precedes new source
acceptance and is repeated before building model context. A saved reply replays
before optional focus validation, so a later event correction cannot prevent
recovery of a previously accepted turn.

Section rework admission checks the exact current root, partition, event/source
revision and locale. An active composer lease or an existing selected-section
proposal prevents admission. Each request has an immutable UUID and payload;
repeating it after a lost acknowledgement does not reschedule the work. Requests
retain only bounded original preview and instruction context, with no direct
authenticated table access. Source changes/withdrawal and event changes/deletion
purge dependent requests.

The migration protects the existing section and advances scheduling metadata,
without changing event facts or factual revision. Only the selected partition
receives the editorial request and bypasses reuse. Its versioned request travels
through the canonical bounded input and database publication fence. Model wording
remains grounded in the existing source window. The existing proposal digest/CAS,
privacy checks, stale-output rejection and acceptance flow stay authoritative.

## Verification

- 383 JavaScript checks passed. Targeted workspace/pagination checks also passed
  after the final UI adjustment.
- 136 targeted Python checks passed across phase, read/API and workspace contracts.
- 65 existing composer-capacity and policy tests passed against disposable Linux
  PostgreSQL, including real publication guards, protected prose, checkpoint
  restart, evidence withdrawal and late-output rejection.
- All 12 new workspace checks plus two existing real-composer-chain regressions
  passed in the final PostgreSQL run (14 checks). The workspace suite exercises owner/revision checks, exact
  request replay, selected-partition work, source withdrawal, stale roots,
  literal focused narration and saved-reply recovery. Its real composer test
  checks preparation/draft/review, authoritative editorial context and a proposed
  replacement before explicit acceptance.
- 10 browser cases passed against a task-owned production frontend with controlled
  Auth/API in English desktop and Chinese phone viewports. They cover stage/event
  actions, preserved input, temporary focus, review before replacement, exact
  retry after a lost acknowledgement and horizontal layout bounds.
- Next production build passed. Localization validated both catalogues (635
  messages); the mobile OpenAPI snapshot matched all 43 operations.

Database checks use disposable task-owned storage and synthetic model responses.
No full Python aggregate, live-provider naturalness evaluation, production
migration or deployment was performed. Browser evidence validates the shipped
interaction against controlled APIs; database/composer tests validate storage
and publication separately.
