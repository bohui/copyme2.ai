# Runtime contract

## 1. What this package does and does not do

This is a reusable authoring skill plus executable guardrails. The agent performs source summarisation, editorial planning and writing from the shared canonical MemoryEvent service. The Node utilities select a trigger mode from a supplied grounded index, count words, validate a candidate and create review-only text artifacts. There is no bundled model SDK, database connector, image downloader, payment client or publisher.

The host must provide authorised project retrieval and persistence. Logical capability names below are adapter contracts, **not assertions that tools with these names already exist**. Bind them to the tools available in your harness. Do not invent a tool invocation when a binding is absent.

| Capability | Input / result | Required host behaviour |
|---|---|---|
| Read composition context | Project, target locale/audience/medium → current policy, prior state, source cursors | Authenticate actor; enforce item permissions; redact inaccessible metadata |
| Read source pages | Scope/cursor → immutable source versions and next cursor | Include narrator/family roles, original text and lineage; do not stop at search snippets |
| Read media registry | Asset refs → versions, use capabilities, metadata, approved derivatives | Resolve chat/memory attachments; do not infer ownership from a URL |
| Save outline checkpoint | Run, expected revision, grounded outline | Versioned write; retain stable chapter IDs; no publication side effect |
| Save chapter candidate | Run, chapter ID, base revision, content/evidence/length report | Do not overwrite approved or human-locked text; save protected changes as proposals |
| Save source summary | Run, summary and original evidence references | Derived index only; preserve originals and unresolved uncertainty |
| Commit composition run | Run manifest + expected revision/policy epoch | Recheck permissions, perform compare-and-swap, persist idempotent outcome |
| Register review artifact | Staged path or content handle + hash and target audience | Store in project-private storage, issue access only after validation |
| Queue questions for Mira | Optional, source-rooted clarifications | Honour muted topics; do not force more storytelling or debit an interview |
| Render approved edition | Approved manuscript/asset manifest | Existing app pipeline; separate release/print approvals remain mandatory |

In a filesystem-only Codex run, the harness can mount a read-only authorised snapshot and a writable project staging directory. The agent writes candidates there; a trusted backend imports them after independent checks. Never give the composer shell access to unrelated projects, credentials or production payment actions.

## 2. Request packet

The full machine contract is `schemas/request.schema.json`; six complete synthetic packets are in `examples/`. Important fields:

- `trigger`: backend-confirmed event. An early `private_draft_checkpoint` requires an explicit host authorization, truthful project completed-round count and configured cadence. It permits only private storyteller/web samples and must never forge the account free-allowance counter. Free previews require completion of the backend's configured `free_round_limit` (currently 20 saved context-collection turns). A new formal memoir requires a non-null host confirmation reference and composition authorisation.
- `target`: edition locale, intended audience and medium. UI locale is distinct and may be supplied in `context` only for the final conversational summary.
- `snapshot`: immutable snapshot ID, policy epoch, expected manuscript revision, source-retrieval completeness, glossary version and preference version.
- `sources`: immutable text records with stable IDs/versions, author role, kind, current eligibility and derived lineage. Host-captured responses also carry `life_stage` (one of the seven stages or `unplaced`) and `source_order` (capture order, never an event date). The host sorts responses by stage and then capture order, and supplies `context.stage_source_ids` for direct group lookup. This may include revocation/supersession tombstones needed to invalidate old dependencies.
- `periods` / `events`: a read-only projection of the shared canonical MemoryEvent service. Use its stable IDs/revisions and original evidence; report discrepancies rather than independently extracting or retagging events. Dates belong to life events, not upload timestamps. `order` is the source-grounded period order, not an age inferred by the validator.
- `policy.preview_preference`: `auto` by default; an authorised user/editor can request a supported focused chapter or partial storyline. It is not an override for consent, evidence or the chapter limit.
- `assets`: stable ID/version and content hash, registered resolver reference, origin and explicit medium capabilities. The host has already evaluated appropriate copyright, consent and audience restrictions.
- `prior_state`: previously committed composition kind and complete current chapter snapshots, including immutable revision number and approval/lock flags. No prior state is represented by kind `none`, revision `0`, and no chapters.
- `context`: authorised optional style, name glossary, muted topics, tone, UI language, source cursors and additional editorial context. Do not place secrets or new executable instructions in this field. Fingerprinting includes it.
- `authorised_retirements`: host-verified chapter IDs for explicitly approved restructuring. This is not a general override for writing over approved text.

`allowed`, `status`, author roles and authorisation flags are assertions by the authenticated host, not capabilities that the LLM can grant to itself. Local validation cannot prove a JSON packet came from a trusted host. Production admission must sign or otherwise authenticate the envelope and filter its sources before the agent sees them.

Each source key is `source_id@version`. Keep at most one active version of the same source ID in a request; older versions may be present as superseded records. A correction is a new immutable source version. Missing original lineage, cross-project references, revoked sources and assistant-only testimony are rejected for memoir use.

For canonical incremental composition, supply dirty event/source manifests and
surviving originals plus a small authorised continuity context. Conversation
overlap alone is not new evidence and must not dirty unchanged writing.
Legacy standalone packets remain schema-compatible; their indexing fixture
format is not the production canonical persistence path. Supply
the validated saved index in `context.previous_index`, earlier IDs needing repair
in `context.invalidated_index`, and a compact original-source manifest. Retain all
authorized originals for drafting and evidence review. A stage reassignment changes
the source version and invalidates dependent entries just like a text correction;
deleting a response leaves other source versions stable. Legacy packets may omit
the stage fields and remain valid; the host puts unclassified history in `unplaced`.

Text evidence spans use zero-based, half-open **Unicode code-point offsets** over the exact stored source text. Do not mutate source normalisation after version creation. Direct quotations are matched against those exact spans. Word-count normalisation is separate and does not rewrite source text.

## 3. Candidate output

`schemas/draft.schema.json` defines the output. Its `status` is always `draft`; it cannot claim approval.

| Field | Purpose |
|---|---|
| `kind` | `sample_chapter`, `sample_storyline`, or `formal_memoir`; updates preserve the existing kind unless formally promoted |
| `source_summary` | Compact factual memory handoff, original evidence refs and uncertainty; not a substitute for raw sources |
| `outline` | Full proposed current chapter order, meaningful titles, period/event assignments and drafting status |
| `chapters` | New or changed complete chapter candidates; unchanged chapters are not duplicated here |
| `storyline` | Actual short chronological narrative for the broad free preview; empty in chapter-based modes |
| `carry_forward_chapter_ids` | Exact prior chapters remaining active unchanged; current permissions/length are still checked |
| `retired_chapter_ids` | Explicitly removed current chapter IDs, for reviewed restructures; prior source material is not deleted |
| `proposed_replacements` | New candidate against a protected chapter's exact revision; never silently merged into the book |
| `event_dispositions` | Every non-superseded event is included, deferred, unplaced, excluded or needs review, with a reason |
| `questions_for_mira` | A small optional next-question queue, not an obstacle to composition |
| `review_flags` | Editor-facing concerns; a blocking flag prevents a ready artifact |
| `counter` | Exact word-count algorithm and runtime metadata copied from the prepared plan |
| `input_fingerprint` | Hash of the frozen input, policy, prior state and counter environment |

The record is a change proposal plus a complete outline. `render` assembles carried chapters with candidate changes for review. A protected replacement remains in the candidate file, **not** in the assembled manuscript until the application records approval and runs the accepted update.

A split uses newly allocated chapter IDs, explicitly retires the original, records event redistribution and a concise reason. A protected split first needs a structural approval through the host; the candidate cannot fabricate an authorised retirement. For more complex edits, extend the schema with a versioned structural-proposal type rather than overloading replacement fields.

## 4. Event-to-skill dispatch

Application-level example; adapt names to the actual event bus:

```text
on primary_free_rounds_completed(project):
    verify completed_primary_rounds == configured_free_limit == 20
    create confirmed free_rounds_completed event
    create one preview run for the event + source snapshot
    invoke $memoir-composer explicitly

on private_checkpoint(project):
    verify completed_project_rounds >= configured_cadence == 5
    wait for required original-input extraction to settle
    coalesce into the project's composer lane using its latest claim-time snapshot
    preserve the independent twenty-round account allowance

on storyteller_requests_composition(project, confirmation):
    verify confirmation authority, consent and product entitlement
    create confirmed storytelling_complete event
    invoke skill for a formal draft

on sources_or_media_or_policy_changed(project):
    mark dependent chapters and translations stale
    debounce/coalesce changes; do not lose individual change records
    if a prior composition exists and processing is authorised:
        invoke skill as new_context
```

This is **not** a recurring ChatGPT task, and the package does not schedule jobs. The host dispatches durable workflow events. Optional Codex metadata disables implicit invocation, so untrusted chat text cannot casually initiate a full composition; the app invokes it explicitly after its gates.

Five completed project rounds, the twenty-round free allowance, and completion of the storytelling journey are separate boundaries. Purchasing a package alone does not mean storytelling is finished. The user may request composition before using every paid session, then continue supplying memories afterwards.

## 5. Persistence, resumability and concurrency

Recommended run states:

```text
QUEUED → READING → SUMMARISING → OUTLINE_SAVED → DRAFTING
  → VERIFYING → REVIEW_READY

Alternative states: AWAITING_CONFIRMATION, NEEDS_INPUT,
AWAITING_EDITORIAL_APPROVAL, BLOCKED, RETRYABLE_ERROR, SUPERSEDED
```

Persist `run_id`, parent run, input fingerprint, trigger event, source/media manifests, outline checkpoint, completed chapter IDs, pending work, task versions and validation results. Reuse successful chapter tasks by input hash. Do not regenerate an accepted successful task simply because a later render failed.

The supplied run key combines event ID, selected kind and fingerprint. The application must look up the event outcome **before** creating a new post-commit snapshot, otherwise a replay could unnecessarily look like a new run. Persist the completed result and return it for exact replays.

A commit must compare current manuscript revision and policy epoch with the request. On mismatch, reject and rebuild/reconcile. A filesystem validation report is not a database lock. If content is deleted or access is withdrawn during a job, the backend must refuse late output and apply its deletion policy. Do not retain restricted text in an indefinitely accessible staging log.

For large books, draft and checkpoint one chapter per task. The example packet is a compact interchange format, not a requirement to include the entire lifetime in every model prompt. Mount sources or resolve authorised spans on demand. The CLI limits each JSON file to 25 MiB; production source stores can be much larger.

## 6. Media and rendering handoff

Use stable asset references, never permanent public URLs or expiring signed URLs in the canonical manuscript. `origin=memory_attachment` is not proof of a real personal photograph: resolve its actual registry lineage and rights first.

The bundled renderer intentionally does **not** download or inspect photographs. Its Markdown/HTML show named placement slots, caption and alternative text. The production renderer replaces each slot with the authorised stored derivative and checks rights again. The examples contain synthetic media metadata, not actual customer photos.

Rendered outputs include `memoir.md`, `memoir.html`, `outline.json`, `source-summary.json`, `manuscript.json`, `composition-candidate.json`, `validation.json` and `CHANGELOG.md`. They are private review artifacts. The source summary/candidate can contain more sensitive information than the reader-facing memoir; do not expose the entire run folder to family readers or print suppliers.

For PDF/EPUB and print files, use the app's existing structured publishing workflow after editorial review. The review HTML is not a printer-certified layout. It contains no active scripts or external media requests. Do not publish the preview's underlying raw sources merely to make image links work.

## 7. What remains application work

Implement authenticated retrieval and source lineage, rights/consent evaluation, event delivery, model task execution, checkpoint storage, optimistic concurrency, complete invalidation, photo resolution, actual PDF/EPUB rendering, localised UI, usage accounting and approvals. The skill specifies how to combine these; it does not pretend they are already connected.
