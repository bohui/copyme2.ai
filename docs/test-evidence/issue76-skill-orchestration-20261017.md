# Issue 76 local test receipt — 17 October 2026

Base: `533e7a4` (main after merged #75/#78 and #77/#80). Branch: `codex/issue76-orchestration`; [PR 81](https://github.com/bohui/copyme2.ai/pull/81). [Implementation](../Memoir_Skill_Execution_Map_Implementation.md); [specification](../Memoir_Skill_Execution_Map_Spec.md).

These runs use synthetic testimony, disposable native PostgreSQL clusters and controlled model/provider transports. Authenticated application routes, canonical claims/publication guards/writers, existing Lane B runners and persisted progress readback are real. Browser checks render the source UI; authentication/history and external model boundaries are controlled. No production migration, deployment, paid/live model, feature enablement or merge was performed.

## Final implementation checks

```sh
MEMOIR_TEST_POSTGRES_BACKEND=native python3 -m pytest -q --tb=short \
  tests/test_background_skill_workflow.py tests/test_formal_memoir_postgres.py \
  tests/test_lifetime_memory_read_api.py tests/test_progressive_composer.py \
  tests/test_lifetime_memory_lane_engine.py
# 182 passed in 134.77 seconds.

MEMOIR_TEST_POSTGRES_BACKEND=native python3 -m pytest -q --tb=short \
  tests/test_conversation_attribution.py tests/test_background_profile_postgres.py \
  tests/test_two_lane_memory.py tests/test_interview_strategy_postgres.py \
  tests/test_interview_strategy_runtime.py
# 161 passed in 199.74 seconds.

MEMOIR_TEST_POSTGRES_BACKEND=native python3 -m pytest -q --tb=short \
  tests/test_memoir_story_game.py tests/test_lifetime_turn_progress.py \
  tests/test_historical_news_canonical_postgres.py tests/test_historical_news_runtime.py \
  tests/test_photo_worker.py tests/test_place_photo_pages.py \
  tests/test_photo_progress.py tests/test_place_groups.py
# 72 passed in 26.98 seconds.

node --test --test-reporter=spec tests/js/*.test.mjs
# 542 passed in 17.95 seconds.

python3 scripts/check_mobile_openapi.py
# Reviewed mobile snapshot matches: 48 operations.
```

The new workflow file has 13 cases, including all three delivered interview modes, actual first-source/profile saves, reply-only skips, blocked B with responsive A, independently blocked photo work while memory saves, cached photos and deterministic grouping, the actual round 1–30 schedule, paged receipt recovery, browser-role write denial, embedded places without another model call, failed commits/fresh-worker retries and missing optional invocation telemetry.

The composer retry case uses the real authenticated retry endpoint after an injected commit failure. It first exposed failed old phase receipts surviving a successful cached retry. Saved transitions now use stable snapshot/page identities rather than attempt-sensitive digests. Actual prepare/draft/review request counts remain unchanged on checkpoint reuse; saved phase receipts and a separate zero-call cached-checkpoint receipt are read back from PostgreSQL. Profile/manual controls and #77 attribution/publication authorities are retained.

The round-matrix fixture grants controlled paid access after the free allowance; this is not a production allowance change. Controlled outputs prove routing, cadence, contracts and persistence, not live semantic mode selection or extraction quality.

## Browser and production build

From `apps/web`, with existing installed dependencies:

```sh
MEMOIR_TEST_POSTGRES_BACKEND=native \
MEMOIR_BROWSER_URL=http://127.0.0.1:3126 \
MEMOIR_BROWSER_EXECUTABLE='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' \
PYTHONPATH="$PWD/../.." \
python3 /Users/bohuihan/.codex/skills/webapp-testing/scripts/with_server.py \
  --server 'node node_modules/next/dist/bin/next dev --port 3126 --hostname 127.0.0.1 --webpack' \
  --port 3126 --timeout 60 -- \
  python3 -m pytest -q --tb=short ../../tests/test_background_skill_browser.py -x
# 3 passed in 38.23 seconds; the helper stopped its server.

node node_modules/next/dist/bin/next build --webpack
# Production compilation, TypeScript, page generation and build traces succeeded.
```

English, Chinese and thinking-off cases send a real authenticated A request while B remains delayed, release the real worker, attach saved timeline/profile receipts to the original history turn, reload and recover them. The dedicated shape-mode button calls the actual game endpoint, explains the unavailable integration and admits no model work. The UI does not display private question pools. JavaScript checks also cover late updates without an initial trace, upserts/replay, real coverage, queue cleanup, foreign-project rejection, independent draft/thinking flags, workspace-only service receipts, server work IDs replacing temporary browser IDs, and stale photo results unable to restore a canonically removed place.

Changed Python modules compile; changed browser modules pass syntax checks; `git diff --check` passes. No CI success is inferred from these local checks.

## Broader-suite limits

The expanded check finished with **160 passed, 16 failed in 209.62 seconds**:

```sh
MEMOIR_TEST_POSTGRES_BACKEND=native python3 -m pytest -q --tb=short \
  tests/test_background_profile_workflow.py tests/test_background_profile.py \
  tests/test_lifetime_composer_policy.py tests/test_canonical_composer_provenance.py \
  tests/test_lifetime_composer_capacity.py tests/test_lifetime_composer_clearance.py \
  tests/test_formal_memoir_routes.py tests/test_formal_memoir_worker.py
```

Every failing case was then selected explicitly and rerun on unchanged main **`533e7a4e28b372c08171a8f3f4dba21c4c23cfdc`**: **the same 16 failed in 6.87 seconds**, with an identical set of failed test IDs. No baseline test or execution gate was changed to hide these failures:

- `test_lifetime_composer_policy.py`: `test_policy_pending_at_any_lane_boundary_is_safe_metadata_deferral` for `extract`, `draft`, `review`, `commit`, `complete`.
- `test_lifetime_composer_capacity.py`: `test_bounded_worker_never_uses_legacy_finish_and_resumes_after_quantum`, `test_invalid_extraction_retries_the_same_bounded_source_before_commit`, `test_extraction_retry_reports_rejected_quote_without_replacing_original`, `test_composer_partition_retains_absolute_original_span_and_current_identity`, `test_real_composer_resume_reuses_completed_phases_after_lease_token_renewal`, `test_rejected_extraction_logs_only_fixed_reason_codes`.
- `test_lifetime_composer_clearance.py`: `test_cancelled_composer_releases_its_lease_and_preserves_saved_checkpoint` and `test_remote_clearance_preserves_bounded_work_and_completed_phases` for `extract`, `prepare`, `draft`, `review`.

These synthetic direct-worker fixtures encounter existing evidence/schema contract failures (for example, “Extraction payload differs from authoritative page evidence”) before their intended transport, policy or cancellation assertions. The new authenticated API/actual-worker/canonical-save retry tests pass without weakening those contracts. Repairing unrelated inherited fixtures is not included in this issue.

Across the four backend groups above there are 575 passing cases and these 16 reproduced baseline failures, not a whole-repository green-suite claim. Previously established retired-path failures remain documented in the [Issue 77 receipt](issue77-conversation-attribution-20261017.md#baseline-failures-not-a-green-full-suite-claim). Production migration and real-provider semantic/performance behavior remain unverified; unavailable integrations and existing rollout defaults remain unchanged.

## PR 81 review fixes — 18 October 2026

Reviewed head: `5e584dd`. Each of the four reported symptoms was reproduced before its fix:

- Pagination scope: `node --test --test-name-pattern='progress pagination cannot publish' tests/js/stage-readiness.test.mjs` failed for project and account switches. An old private profile replaced the newly selected project's profile after the awaited continuation read. Readiness now revalidates scope and newer-save requests after pagination, before applying any profile, mode, stage or workspace state. Regression cases cover project/account/navigation transitions and an intervening newer save.
- Browser-cache duplicates: `node --test --test-name-pattern='later browser-cache hit' tests/js/place-photo-pagination.test.mjs` observed two trace entries after one provider lookup and one browser-cache hit. Photo-cache metadata now retains the actual server work ID and originating turn. Cache reuse upserts the original step, including after reload or a later reply; it does not dispatch another lookup or attach the old operation to a new stream.
- Terminal service receipts: `MEMOIR_TEST_POSTGRES_BACKEND=native python3 -m pytest -q --tb=short tests/test_background_skill_workflow.py -k completed_optional_service_receipts` failed after aging actual successful authenticated photo/grouping receipts six minutes. The readback expiry predicate now applies only to unfinished optional work. Completed service receipts remain completed; the same test proves stale running work still becomes interrupted/failed. Canonical model completion still needs its separate save boundary.
- Commit replay: the same workflow command with `-k committed_page_replay` failed twice: replaying the first page's exact committed request returned `replayed: true` while incorrectly marking the second page saved before its commit. Page/profile/summary receipt wrappers now leave lifecycle metadata unchanged on replay. The actual-worker regression verifies page two remains completed until its own canonical commit, then both sources have saved receipts.

Final post-fix checks on disposable native PostgreSQL and controlled external boundaries:

```sh
MEMOIR_TEST_POSTGRES_BACKEND=native python3 -m pytest -q --tb=short \
  tests/test_background_skill_workflow.py tests/test_formal_memoir_postgres.py \
  tests/test_lifetime_memory_read_api.py tests/test_progressive_composer.py \
  tests/test_lifetime_memory_lane_engine.py
# 184 passed in 131.31 seconds.

MEMOIR_TEST_POSTGRES_BACKEND=native python3 -m pytest -q --tb=short \
  tests/test_conversation_attribution.py tests/test_background_profile_postgres.py \
  tests/test_background_profile_workflow.py tests/test_two_lane_memory.py \
  tests/test_canonical_composer_provenance.py
# 168 passed in 197.78 seconds.

node --test --test-reporter=spec tests/js/*.test.mjs
# 549 passed in 20.42 seconds.
```

The three English/Chinese/thinking-off browser cases passed again in 33.97 seconds using the source-UI command above. The production webpack build passed again; the mobile OpenAPI snapshot still matches 48 operations. Browser syntax, changed Python test compilation and diff checks pass. The initial JavaScript run lacked this worktree's installed-dependency link; after restoring that local test setup, the complete run above passed. No dependency/version change was made.

The unmerged migration was updated in place and applied only to fresh disposable test clusters. No production migration, deployment, live-provider run or merge was performed. The 16 previously reproduced baseline failures are not reclassified as passing; unrelated broad legacy fixtures were not rerun in this focused review-fix pass.

### Follow-up P2 — completed services must not keep readiness pending

Reviewed head: `887b34e`. The remaining readiness aggregation treated all `completed` receipts as unfinished, even though photo/grouping completion is terminal. The API now excludes completed services from its pending predicate while retaining queued/running work, SQL-owned canonical pending state, profile automation and model completion awaiting a save. No scheduler, SQL migration or browser implementation changed in this follow-up.

The parameterized regression drives the authenticated conversation API, drains the actual B worker, then invokes a real authenticated photo/grouping service and reads readiness. Both service cases failed with `pending=true` before the fix (**2 failed in 7.28 seconds**). Both passed after the fix (**2 passed in 8.18 seconds**), asserting completed receipts remain visible while `readiness.pending=false`. Each case then accepts another source, verifies pending becomes true again, drains B and verifies false again.

```sh
MEMOIR_TEST_POSTGRES_BACKEND=native python3 -m pytest -q --tb=short \
  tests/test_background_skill_workflow.py -k completed_optional_services_do_not_keep_readiness_pending
# 2 passed, 15 deselected in 8.18 seconds.

MEMOIR_TEST_POSTGRES_BACKEND=native python3 -m pytest -q --tb=short \
  tests/test_background_skill_workflow.py tests/test_background_profile_workflow.py \
  tests/test_lifetime_memory_read_api.py
# 55 passed in 116.20 seconds, including the two new service regressions.

MEMOIR_TEST_POSTGRES_BACKEND=native python3 -m pytest -q --tb=short \
  tests/test_stage_readiness.py tests/test_stage_progress_regression.py \
  tests/test_stage_progress_rpc_lifecycle.py
# 26 passed in 15.67 seconds.

node --test tests/js/stage-readiness.test.mjs
# 31 passed; includes stopping recovery when readiness is no longer pending.
```

Python compilation, diff checks and the reviewed 48-operation mobile OpenAPI snapshot pass. External model/photo discovery remains controlled; the actual grouping service, canonical workers, PostgreSQL and readiness route are exercised. No full browser/build or live-provider rerun is claimed for this API-only follow-up. No deployment, migration or merge was performed.
