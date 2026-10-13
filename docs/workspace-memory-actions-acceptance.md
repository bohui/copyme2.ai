# Workspace memory actions: implementation and acceptance record

Follow-up to PR #61. Scope approved on 2026-10-13: remove the persistent
comfort/explore/shape selector from chat and expose concrete tasks in the workspace.
Final branch rebased on main `9736a2c`.

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

Section rework admission checks the exact current root, current canonical
partition membership, event/source revision and locale. An active composer lease
or an existing selected-section proposal prevents admission. Each request has an
immutable UUID and payload;
repeating it after a lost acknowledgement creates no duplicate request or new
narration. A pending replay can requeue an idle lane for its edition while
preserving a live lease or unfinished snapshot. Requests
retain only bounded original preview and instruction context, with no direct
authenticated table access. Source changes/withdrawal, event changes/deletion
and changes/removal of a photo link purge dependent requests. Photo invalidation
matches the exact link in the partition key and preserves other photo and
source-only requests. Attaching the first qualifying photo retires pending
requests for the source-only partition it replaces; adding sibling photos
preserves requests for partitions that still exist.

The migration protects the existing section and advances scheduling metadata,
without changing event facts or factual revision. Only the selected partition
receives the editorial request and bypasses reuse. Its versioned request travels
through the canonical bounded input and database publication fence. Model wording
remains grounded in the existing source window. The existing proposal digest/CAS,
privacy checks, stale-output rejection and acceptance flow stay authoritative.

## Initial verification at 072c2569

- 386 JavaScript checks passed. The existing mocked Make runner accommodates
  main's new account-setup prerequisite without executing account operations.
- 139 targeted Python checks passed across phase, interview, read/API and workspace
  contracts; 12 opt-in live model checks were skipped.
- 65 existing composer-capacity and policy tests passed against disposable Linux
  PostgreSQL, including real publication guards, protected prose, checkpoint
  restart, evidence withdrawal and late-output rejection.
- All 12 new workspace checks plus two existing real-composer-chain regressions
  passed in the final PostgreSQL run (14 checks). The workspace suite exercises
  owner/revision checks, exact
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

## Edition handling review fixes

Both reported P2 findings reproduced in regressions. Switching the visible draft
edition previously retained an English rewrite form and submitted its frozen
English snapshot while Chinese was selected. Forms now record their edition,
clear on an edition switch and ignore responses from a replaced form.

The shared composer lane previously completed only its latest selected edition,
leaving an earlier edition's request pending. Root completion now queues the
oldest remaining pending request's edition. A saved page records its output
snapshot while its request stays pending until that complete root is available
for review. Interrupted/stale roots therefore leave the editorial task retriable;
a replay resumes an unfinished edition without switching its language.

The original failing language-switch and two-edition queue scenarios now pass.
Additional checks cover a response arriving after an edition switch, exact
pending-request recovery, live-lease preservation and retry after a yielded page.
The two-edition queue test runs the real bounded composer/publication path with
synthetic model responses and keeps both originals available for review.

The final JavaScript suite passes all 388 checks. All 80 workspace,
composer-capacity and policy Python checks passed against disposable PostgreSQL,
including the 10,000-event capacity case. All 12 browser cases in English desktop
and Chinese phone viewports and the production build pass. No production
migration or deployment was performed for these fixes.

## Photo unlink review fix

Unlinking a photo through `unlink_user_interview_photo` after queuing a rewrite
reproduced the reported loop: the photo partition disappeared, but its pending
editorial request survived and completion immediately queued another empty draft.
The existing prose invalidation handled the changed photo link; workspace request
invalidation previously covered only source and event changes.

The workspace invalidation trigger now retires requests for the exact changed or
deleted photo link, in the same transaction and before completion can reschedule
them. An indexed dependency lookup scopes this to the owner, project and photo
partition. It also covers photo deletion and corrected metadata. Unchanged link
updates preserve requests.

Six new disposable PostgreSQL regressions pass. They exercise the actual unlink
RPC both before composition and after a saved/yielded page, prove the lane becomes
idle without another empty snapshot, and reject replay of the retired request.
The remaining cases cover photo deletion, link editing/deletion, unchanged updates,
unauthorized unlink and unlink replay. Sibling-photo and source-only requests keep
their exact bytes and still receive editorial pages and reach completion.

The final run passed all 133 checks across workspace actions, lifetime review
repairs, interview photos, composer policy and composer capacity, including the
10,000-event case. No production migration or deployment was performed.

## First-photo attachment review fix

The inverse transition reproduced through authenticated `save_user_interview_plan`:
a queued source-only rewrite survived its first qualifying photo attachment even
though the composer now visited a different partition key. Both an unstarted
request and a request with a saved/yielded page remained pending and immediately
requeued the lane after completion. The removal fix did not cover this transition.

A shared current-partition predicate uses the composer's exact evidence and photo
join rules. Admission rejects obsolete identifiers. Photo-link insertion or
confirmation retires pending requests whose partitions have disappeared, scoped
to the affected event and without changing saved original prose. Existing photo
partitions, other evidence inputs and photos outside the composer input remain
eligible. Completion also discards obsolete pending requests before scheduling
another edition, recovering tasks stranded by the earlier code.

Five new disposable PostgreSQL regressions pass. They drive authenticated photo
acceptance and save-plan RPCs, cover attachment before work and after a yielded
page, and independently exercise recovery of a previously stranded request. They
also verify preserved original prose, rejected stale requests, unaffected evidence
in the same event, sibling-photo additions and a photo with provenance outside
the composer input. Surviving requests still receive editorial pages and complete.

The final attachment-fix run passed all 138 checks across workspace actions,
lifetime review repairs, interview photos, composer policy and composer capacity,
including the 10,000-event case. No production migration or deployment was performed.
