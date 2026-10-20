# Governed selected-source collection work

This additive migration and code path are inactive until explicitly adopted. This change does not authorize a production migration, backfill, rollout, deployment or provider call.

## Compatibility and explicit scope

Mapped accounts use canonical selected-source jobs. Unmapped accounts retain the existing collection queue and organiser. A request can explicitly select at most 1,000 distinct source IDs; this is a per-job resource bound, not a limit on lifetime history. Exceeding it fails validation rather than selecting a prefix. The job manifest freezes owner, project, conversation, source versions/hashes/order, policy epoch, preference revision, edition locale and chosen title. Source text remains in the canonical source table, not copied into job manifests.

Confirmation retains all six period records and their notes. The organiser requires the exact ready collection revision, current source fingerprint and verified paid entitlement. Period traversal order and within-period selected order are retained. As in the legacy organiser, period notes are readable but are not testimony or a model grouping instruction. A confirmed document is not publication approval.

## Bounded processing and complete coverage

Each activity handles at most one source window or one merge. Original windows are at most 2,048 characters. Source versions are checked again at claim, prompt admission, commit and result read/publication. Deterministic preview and source export never invoke a model and retain exact original text.

Outline leaves consume bounded source windows. Hierarchical merges consume exactly two persisted, server-owned child metadata objects, each limited to 12,000 UTF-8 bytes. They can group sections across children, retain up to 100 final sections, and preserve an exact disjoint ancestry for every selected source window. Child IDs, digests and metadata are independently reconstructed at admission. Derived titles and sections remain proposals and never become narrator evidence. An over-budget or invalid output enters durable retry state; no title, group or source is silently clipped. All actual request bytes, schema, purpose-specific privacy pins and framing count against the engine's 65,536 input budget.

The final result preserves the chosen title separately from the suggested title. Root section IDs are stable server IDs. Original source references/text are paginated, with each window linked to its final root section. Coverage metadata says `selected_sources`; it never claims to export unselected lifetime history.

## Safety and recovery

The publication lock order is auth account, project, profile/identity, confirmed collection, entitlement, then job. The result publisher takes the same outer account lock before its generic read fence, and holds one transaction through the bounded actual ASGI send. Cancellation closes that transaction. Source withdrawal, policy/preference changes, confirmation changes and entitlement revocation invalidate applicable jobs and remove disposable generated node/result bytes transactionally. Unrelated tenant jobs remain usable.

Opaque result cursors bind owner, job, root and expiry. Collection task heads have a separate owner/project-scoped keyset cursor and a page size of at most eight. Source pages and task pages advance independently. Explicit browser/native downloads fetch every result page and reject missing cursors or changed roots before producing an artifact.

The shared poller schedules a dedicated Temporal workflow with only an opaque job ID. At most four activities execute concurrently across the existing worker. Each activity reconstructs current canonical authority and sources. Durable SQL progress allows crash/reclaim without repeating committed pages. Workflow history is renewed after 64 activities and contains no source text, generated titles or raw provider/database errors. Failed jobs expose an explicit retry endpoint; stale jobs do not re-enter the pending queue.

`MEMOIR_LIFETIME_GENERATION_PAUSED=true`, or disabling `MEMOIR_LIFETIME_MEMORY`, stops model generation. Existing mapped privacy guards, result reads, deterministic preview/export and required metadata maintenance continue to operate. Rollback does not restore an ungoverned legacy path for mapped accounts.

## Verification

Focused tests cover real PostgreSQL two-tenant authority, selected order, confirmation/paid gates, crash/retry, source and entitlement changes, transactional derived-byte removal, typed leaf/merge admission, complete pagination, 100 final sections, CJK budget failures and actual-send cancellation. The capacity fixture extends a history to 10,000 canonical sources while a selected-source job retains its bounded frozen manifest and exact paginated export.

`tests/test_lifetime_collection_dispatch.py` includes an isolated real Temporal server test for nonblocking dispatch, duplicate workflow delivery, safe retry and absence of private text in history. Browser fixtures use only synthetic responses:

- `python tests/browser_collection_pagination.py --base-url http://127.0.0.1:3010`
- `python tests/browser_collection_review.py --base-url http://127.0.0.1:3010`

Native paging tests additionally cover identity changes, repeated taps, unloaded selections, changed roots and aborting exports before sharing. These fixtures do not authorize live paid-provider testing.

## Isolated Mac/browser verification

Use an isolated checkout of the immutable candidate identified in the review handoff. Do not test a different or moving branch. Prerequisites are a compatible Node installation, the web dependencies installed from `apps/web/package-lock.json`, and a Python environment with Playwright and its Chromium browser. No backend, account credentials, paid model or production data are needed.

From the repository root, start a localhost-only web server in one terminal:

```sh
MEMORY_SPARK_API_ORIGIN=http://127.0.0.1:9 NEXT_TELEMETRY_DISABLED=1 \
  npm --prefix apps/web run dev -- --webpack --hostname 127.0.0.1 --port 3010
```

In another terminal, using that Python environment, run both fixtures exactly:

```sh
python tests/browser_collection_review.py --base-url http://127.0.0.1:3010
python tests/browser_collection_pagination.py --base-url http://127.0.0.1:3010
```

Both fixtures intercept configuration, profile, collection and task requests with synthetic responses. The server's fallback API origin is an unused loopback port, not a live backend. The legacy fixture checks explicit confirmation, all six periods, source selection, a queued result and download. The canonical fixture checks English and Chinese, unloaded selections, selected order, independent source/task pagination, explicit retry without duplicate requests, proposed hierarchical metadata, full paginated download and dismissal. Download contents are parsed and asserted before success is printed.

Successful runs print one `PASS` line per locale and write screenshots below `output/playwright/`: `collection-en-AU.png`, `collection-zh-CN.png`, `collection-pagination-en-AU.png` and `collection-pagination-zh-CN.png`. Record the tested commit/tree, commands, exit codes and screenshots in the review evidence. Stop the local server after verification.

These browser runs have **not** passed in the cloud task environment: the web server starts, but Chromium exits before navigation because its singleton socket is denied with `socket() failed: Operation not permitted`. A second launch attempt hit the same restriction. Unit, React Native UI and API tests do not replace these pending browser checks; no passing browser evidence is claimed here.
