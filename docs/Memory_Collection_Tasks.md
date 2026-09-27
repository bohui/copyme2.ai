# Memory collection and deterministic tasks

## Product flow

1. The collector keeps gathering the storyteller's memories. The memory-context,
   place-journey, family-tree, timeline, and place-photo capabilities support this
   stage; a populated timeline alone never triggers book organisation. Existing
   Family-package gates remain unchanged. `app-auto-localization` is a development
   skill supporting the product's UI, not a separate storytelling agent.
2. The user reviews seven life periods. Each is recorded with selected saved
   memories, explicitly skipped with a reason, or marked not yet applicable.
   At least one recorded period and explicit confirmation are required.
3. The organiser starts a separate Codex thread with the confirmed sources. It
   proposes a JSON book title and sections, retaining all chosen source IDs.
   Unknown or omitted sources cause rejection, not silent fabrication.
4. `codex-worker` publishes the validated outline task. Temporal schedules an
   ordinary worker to assemble its deterministic artifact. The user can refresh
   status or download the JSON from the review window. This is a proposed book
   structure, not a finished book, PDF, publishing or printing workflow.

The readiness review is distinct from the paid Family timeline feature. It can
be saved during collection, but starting the organiser still requires the
existing paid-memoir entitlement. Review updates and agent turns share the user's
Supabase lease, preventing concurrent confirmation changes during organisation.
New collector turns clear the project's confirmation and advance its revision.
The organiser also checks a fingerprint of the saved sources against the
confirmation, so changed memories require review even if an invalidation update
was interrupted or the new memory was collected in another project.

## Publishing without an LLM

Trusted application code sends `POST /internal/tasks` to the private
`codex-worker:8766` with the server-only `X-Codex-Worker-Secret` header:

```json
{
  "user_id": "11111111-1111-4111-8111-111111111111",
  "project_id": "my-memoir",
  "task": {
    "kind": "BuildSourceExport",
    "title": "Collected memories",
    "sources": [{"id": "saved-memory-id", "content": "Authorised storyteller text"}]
  }
}
```

The caller must authorise every source first. Never expose this secret or
publisher to a browser or a tenant subprocess. A model can suggest only allowlisted
task kinds and saved IDs; the API chooses the authenticated owner and resolves
the actual text. Publication happens only after a collector turn is saved.
Publication failures are reported to the browser; the user must request the task
again if it never reached the durable outbox. Repeating an identical accepted
snapshot returns the same task ID, including after a container restart.

The Codex supervisor forwards publication over authenticated HTTP to the API's
`/internal/tasks` persistence ingress. Only API and deterministic workers mount
the task volume. The logical publish arrow in the architecture diagram goes
through this API-owned ingress; it is not a Codex filesystem mount.

| Kind | Deterministic result | Current entry point |
| --- | --- | --- |
| `BuildFreePreview` | Verbatim source-linked blocks | Collector or authenticated task request |
| `BuildSourceExport` | Authorised source JSON | Collector or authenticated task request |
| `BuildOutline` | Validated sections with memory IDs | Confirmed organiser handoff |
| `BuildChapter` | Verbatim source-linked blocks | Trusted publisher; chapter UI is not yet connected |

These are active job types, not deprecated jobs. The old `MemoryStore` project
routes remain a separate specification adapter and are not the connected
Supabase conversation/task path.

## Public interface

All routes require the storyteller's bearer token. The canonical prefix is
`/api/v1/memoir/agent`; `/v1/agent` remains compatible.

- `GET /collection/{project}`: review, authorised memory index and recent results.
- `PUT /collection/{project}`: periods, `expected_revision`, `confirm_ready`.
- `POST /collection/{project}/organise`: confirmed revision and language.
- `POST /collection/{project}/tasks`: preview/export kind, saved memory IDs, title.
- `GET /tasks/{id}`: owner-scoped status/result; another owner receives 404.

The former `/story/full-memoir` placeholder now returns
`COLLECTION_REVIEW_REQUIRED` instead of falsely claiming to have generated a book.

## Persistence and limits

`memoir-tasks` is both the Temporal task-queue name and the local task-volume
name; they are different things. Temporal coordinates execution. SQLite stores
private payloads/results and readiness reviews; Supabase remains the source of
truth for saved user memories and authentication. There is no Redis queue.

The worker starts stable `memoir-task:{id}` workflows from the durable outbox.
Activities claim tasks transactionally, retry up to three execution attempts,
and fence expired completions. Temporal activity retries recover busy leases;
terminal workflow failures are reflected back into the task store. Replayed
successful activities return the stored status without redoing the work.

Named volumes survive `container-up` and normal `container-down`. Back up both
volumes together. The task database is mode 0600, but the security guarantee is
mount isolation: **the Codex container does not mount the database at all**.
An integration probe found that Mocker's virtiofs sharing did not enforce these
file modes against tenant UIDs, so modes alone must not be treated as isolation.
Local operators/root can read it; it is not encrypted at rest by this application. The reset utility for
Supabase does not yet remove these new task snapshots. Do not assume a Supabase
memory deletion removes an already-enqueued snapshot or result.

This single-host implementation intentionally uses Temporal's persistent dev
server. Production rollout needs a production Temporal service and a shared
database adapter, backup/retention/deletion integration, task quotas, and
operational monitoring. Do not spread these SQLite volumes across hosts.

Memory selection is user-scoped because existing `user_memory` rows are
user-scoped; the user explicitly assigns saved memories to each project's
review. Reviews accept at most 1,000 source rows; organiser input is capped at
120,000 characters and rejected if larger, never silently truncated. Task
payloads are capped at 2 million characters. Generated book artifacts and the
assistant's questions are not reused as storyteller evidence.

## Verification

- `python3 -m pytest -q`: queue, source validation, owner isolation, readiness and
  organiser contract tests plus existing regressions.
- `python3 tests/browser_collection_review.py`: synthetic English/Chinese browser
  confirmation, period coverage, task polling and JSON download.
- `make container-health`: running frontend/API, Codex worker and Temporal connection.
- `mocker compose exec -f compose.yml -i -T api python - < scripts/verify_task_pipeline.py`:
  real private publishing and Temporal execution, duplicate handling and owner isolation;
  leaves a synthetic non-customer receipt.
- `mocker compose exec -f compose.yml -i -T codex-worker python - < scripts/verify_task_isolation.py`:
  verifies no task mount exists in Codex and an unprivileged tenant cannot read
  the database or publish directly to the API without supervisor credentials.
