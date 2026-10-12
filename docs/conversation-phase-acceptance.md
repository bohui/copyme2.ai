# Conversation phases: implementation and acceptance record

Issue: #59. PR: #61. Base: cc068523208842e2accde8d623a060a04143e78c.
Revised scope confirmed by the user on 2026-10-12: one continuous conversation,
without pause/resume controls or durable pause state. Later rectifications update
only the affected year/event and its dependent material, without resetting the
conversation mode or restarting the interview. This supersedes the pause and
correction-driven mode changes in the original issue.

## Contract and ownership

`conversation_phase` is an application-owned v1 envelope with phase,
automatic/explicit selection, preferred phase, revision, bounded reason and source
turn UUID. It belongs to the existing owned project. Later identity/checkpoint
work must preserve this validated envelope separately from generated summaries.
Life stage, entitlement, language and completed-round accounting remain independent.

GET/PATCH `/v1/agent/projects/{project_id}/conversation-phase` uses typed actions
and an expected revision. Supported actions are comfort, explore, shape, automatic
and skip. Controls create no narration or completed round. Pause/resume actions
are rejected and there is no `paused` field. A storyteller may leave and return
without a resume step. A wish to finish the current exchange still receives an
acknowledgement without another question; it does not create a durable mode.

Automatic guidance can move from comfort to explore as narration develops; an
automatic proposal cannot return exploration to onboarding. Gentler conversation
and shaping remain explicit choices. English/Chinese direct requests after reported
or quoted memories are recognised separately from another speaker's commands.
The existing event/source correction RPCs retain their revision,
ownership, provenance, exclusion and approved-prose protections. This migration
adds no correction trigger or wrapper that changes the conversation phase.
A year correction preserves the unrelated event, saved mode and phase revision.

The migration wraps the existing photo/news/work-plan save validator. Late
proposals fail the phase CAS while retaining accepted narration. Accepted turns
capture an immutable preference revision; retries cannot replay superseded intent.
Saved replies replay without regeneration and read back the current preference.
Guest transfer preserves phase through the existing project mapping. Returning
begin/continue greetings receive the saved mode through the same collector, with
no extra model call. DDL rerun is tested; no production migration was executed.

## Verification of the revised local implementation

Verified the changes on `codex/pr61-smooth-flow`, based on PR head a2a42a1:

- 332 Python checks passed across phase policy/API/runtime, opening, plan validation,
  project recovery, streaming, historical-news behavior and the worker service.
- 90 real PostgreSQL checks passed across phase, work-plan and private-round suites.
  These include restricted-role ownership, concurrent CAS, replay, admission
  ordering, guest transfer and workspace/chat year corrections. The correction
  cases cover automatic exploration and explicit shaping, including a collector's
  attempted reset to comfort. An unrelated event and the complete phase envelope
  stay unchanged. Identical attribution cases exercise both Python and SQL.
- One existing protected-draft PostgreSQL regression passed; 110 unrelated cases
  were deselected in that targeted run.
- All 358 JavaScript checks passed, including 13 phase checks. Removed pause/resume
  actions never write, and saved replies finish without interrupting the flow.
- All 14 shipped-UI browser cases passed in English desktop and Chinese phone
  viewports against a task-owned production frontend with controlled Auth/API.
  They cover accessible controls, reload, stale tabs, project/account switching,
  streamed save readiness, continuing without resume, corrections and the allowance
  boundary. The earlier Chromium-launch blocker did not recur on this host.
- Next production build passed. Both localization catalogues validated (579 keys),
  and the mobile OpenAPI snapshot matched all 36 operations.
- All 16 bilingual synthetic evaluation cases passed deterministic gates.
  The semantic judge was not configured; overall quality acceptance was unavailable.
  These fixture results do not establish live-model naturalness or latency.

SQL checks use disposable task-owned PostgreSQL containers and real authenticated
roles; they never use configured Supabase URLs or existing customer storage.
Native PostgreSQL startup was blocked by this host's shared-memory limit. The
separate native-only historical-news SQL suite could not be verified in the
preceding review (44 setup errors); no pass is claimed for it here.

No full Python aggregate, live paid evaluation, production migration or deployment
was performed for this revision. Prior aggregate counts belong to the earlier PR
implementation and are not evidence for the revised scope.
