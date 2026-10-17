# Issue 77 local test receipt — 17 October 2026

Base: `60880cf` (main, including merged #75/#78 and phase retirement #79).
Implementation: branch `codex/issue77-attribution`. [Implementation contract](../Memoir_Conversation_Event_Attribution_Implementation.md); [specification](../Memoir_Conversation_Event_Attribution_Spec.md).

All database runs used `MEMOIR_TEST_POSTGRES_BACKEND=native`, task-owned disposable PostgreSQL clusters and synthetic testimony. No configured Supabase data, deployment, production migration or paid/live model was used. External model transport was controlled; authenticated routes, original acceptance, SQL writers, publication guards, receipt broker and Lane B workers were real.

## Passing checks

- Final full conversation-attribution acceptance file: **39 passed** in 84.84 seconds:

  ```sh
  MEMOIR_TEST_POSTGRES_BACKEND=native python3 -m pytest -q --tb=short tests/test_conversation_attribution.py
  ```
- **325 passed** together after rebasing on #79:

  ```sh
  MEMOIR_TEST_POSTGRES_BACKEND=native python3 -m pytest -q --tb=short \
    tests/test_two_lane_memory.py tests/test_background_profile_postgres.py \
    tests/test_background_profile_workflow.py tests/test_lifetime_memory_lane_engine.py \
    tests/test_progressive_composer.py tests/test_canonical_composer_provenance.py \
    tests/test_lifetime_memory_read_api.py tests/test_conversation_phase_retirement.py \
    tests/test_interview_strategy.py tests/test_interview_strategy_postgres.py \
    tests/test_interview_strategy_runtime.py -x
  ```

- **41 passed**: `tests/test_stage_progress_rpc_lifecycle.py`, `tests/test_stage_readiness_provenance.py`, `tests/test_stage_progress_regression.py`, `tests/test_stage_readiness.py`, `tests/test_mobile_openapi_contract.py`.
- **16 passed** in `tests/test_shared_memory_events_postgres.py`: exact test functions `test_changing_placement_or_relation_evidence_reconciles_the_dependent_event`, `test_supported_age_estimates_retain_original_language_expression_and_birth_basis`, `test_a_relatives_birth_does_not_establish_the_narrators_age_based_year`, `test_unsupported_numeric_dates_are_rejected_at_the_public_persistence_boundary`, `test_conflicting_attributed_dates_remain_unresolved_until_an_explicit_author_correction` (including their parameters).
- `python3 scripts/check_mobile_openapi.py`: reviewed **48 operations match**; no native contract expansion.
- Python compilation of changed modules and the new test file; `git diff --check`.

The new acceptance cases cover pending versus attempted/unresolved coverage; non-story/name/thanks/control rules; English/Chinese age evidence; relative/inner-quote birth rejection; mixed privacy and independent testimony; exact Unicode windows and repeated-quote ambiguity; selective event/place roles; episode enrichment; delivered-question-only context without stage credit; responsive A while B is blocked/failed; accepted sources after failed A; retry/restart; atomic malformed-output rejection; edits/withdrawal during extraction; manual timing and removed-link authority; pagination/account/project/Family gates; real composer consumption; and mode-independent outcomes under active comfort/explore/shape decisions.

## Baseline failures, not a green full-suite claim

The broader inherited shared-memory file is not wholly passing. These observations were reproduced on unchanged local main `60880cf` as well as this branch:

- `test_story_workflow_retains_original_testimony_when_provider_delivery_fails` calls `runtime.turn()` without the now-required canonical publication context and raises `ValueError: A canonical publication context is required`.
- The broader selection `-k 'temporal or age or relative or changing_placement or reprocessing or stage or removal or deleted or withdrawal or withdrawn'` yields **15 failed, 12 passed, 84 deselected** on both main and this branch. These legacy draft/history/greeting cases reach retired direct-execution paths (`canonical execution required` or the missing publication context) before this ticket's behavior. No unrelated legacy test migration or execution-gate weakening was included.

Initial red tests and integration-harness issues were corrected during implementation: missing bounded readback, empty extraction misrepresented as pending, absent selective places/delivery context/composer metadata, duplicate overlapping read keys, Python/SQL age-interval mismatch, and test receipt adapters/fixture isolation. Only the final passing runs above count as verification; earlier failed runs are not counted as successes.

No browser/UI rendering check, whole-repository green-suite claim, live-provider semantic-quality measurement, production completeness audit or new orchestration behavior is claimed. #76 remains separate, and merge is left to user review.
