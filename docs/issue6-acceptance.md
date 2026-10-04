# Issue 6 acceptance and verification

Source: [Issue 6](https://github.com/bohui/copyme2.ai/issues/6), authored by `bohui`, labelled `ready-for-agent`. Full body and all comments were read before implementation and rechecked on 2026-10-04; `updated_at=2026-10-04T01:07:30Z`, zero comments. All 56 stories and all Implementation/Testing Decisions remain requirements.

This is local implementation evidence against a pinned dependency, not final integrated acceptance. Independent cloud review, review-clear PR3/current-main integration, overlapping regressions and required CI checks remain gates. Nothing was merged, migrated against production, deployed, or restarted in the shared public stack.

## Dependency and isolation

- Task branch: `codex/issue6-shared-events`; checkout: `/tmp/memoir-issue6`.
- Exact inherited dependency: PR3 commit `d8ef614c0af4a15b41d6cc9b1ed1b1cc9ef35198`.
- Exact task-only diff range: `d8ef614c0af4a15b41d6cc9b1ed1b1cc9ef35198..HEAD`. Cloud reviewers must use this range to distinguish Issue6 work from inherited PR3 work.
- The stacked PR targets `memoir-five-case-evaluation`. That branch's observed integrated head `d67f39085d0fc85f0f6713f66fa9f7bfc3c4a274` is still pending correction/review and is not incorporated here. Parent explicitly authorised publishing the pinned stacked draft.
- Main was observed at `8e61b19b0a223578450684500263e3c7e7a1c010` after PR5's photo changes. Current-main/PR3 integration is a separate, required step before final acceptance.
- The dirty primary checkout and other agents' branches, ports, customer databases and services were excluded. Schema changes are only additive migrations `202610040001_shared_memory_events.sql` and `202610040002_memoir_skill_lanes.sql`; inherited migrations were not rewritten.

## TDD and agreed seams

Actual [/TDD skill](/Users/bohuihan/.agents/skills/tdd/SKILL.md) and its tests/mocking references were applied. The issue agrees authenticated story workflow, shared application RPC/migration, and a small browser workspace seam. Observable regression slices were run red, implemented, then rerun green; existing behavior checks may start green. Fixture/setup errors are not reported as implementation red evidence.

Controlled responses are only at the external model/provider boundary. Authentication/entitlement metadata and the Supabase REST transport are synthetic boundaries backed by real PostgreSQL roles, transactions and application RPCs. Workers, application validation, dispatch, revision fencing, JS validation, rendering and durable outcomes run normally. No live model semantic evaluation, live OAuth, payments, production migrations or rollout is claimed.

The existing disposable PostgreSQL harness has an opt-in `MEMOIR_TEST_POSTGRES_BACKEND=apple-container` backend. Each invocation creates a random `memoir-issue6-pg-*` PostgreSQL 18.3 container with one CPU, 1 GiB memory, no host ports, mounts or inherited credentials, PostgreSQL TCP disabled, and removes only that container in teardown. This avoids the host's exhausted SysV shared-memory resource without changing shared services or kernel limits. Temporal tests launch task-only loopback dev servers with fresh SQLite databases, no UI, SDK 1.34.0, CLI 1.9.1/server 1.32.0; workflow history is checked for private story bytes.

## Exact 56-story matrix

Each row names a scenario selector below. Passing scenarios establish controlled application behavior; final review/integration gates above still apply.

| Story | Required storyteller/operator outcome | Scenario |
| --- | --- | --- |
| 1 | every accepted message processed for life events in the background, so that my timeline grows without a separate recording step. | S01 |
| 2 | conversational acknowledgements to produce no invented events, so that my timeline contains memories I actually described. | S02 |
| 3 | several events from one reply saved separately, so that different stages and years are represented accurately. | S03 |
| 4 | several replies about one event linked together, so that extra details enrich the same story. | S03 |
| 5 | new details to reach an event first discussed much earlier, so that I can revisit memories naturally. | S04 |
| 6 | distinct events with similar descriptions kept separate, so that recurring experiences are not merged accidentally. | S05 |
| 7 | uncertain event matches left unresolved, so that the assistant does not attach my words to the wrong memory. | S05 |
| 8 | events assigned to supported life stages, so that I can navigate my story by period of life. | S03 |
| 9 | each event assigned its supported year or date range, so that capture dates do not become story dates. | S03 |
| 10 | approximate expressions such as around 1970 preserved, so that my memoir reflects my uncertainty. | S03 |
| 11 | an undated memory retained, so that missing timing does not discard an otherwise clear event. | S05 |
| 12 | a year estimate linked to its evidence, so that I can understand and correct its basis. | S06 |
| 13 | long life periods retained as single records with ranges, so that my work or residence history is not fragmented into invented yearly events. | S05 |
| 14 | to correct a previously saved event's life stage, so that its placement matches my recollection. | S07 |
| 15 | to correct a previously saved event's year, so that both the timeline and writing reflect the correction. | S08 |
| 16 | my explicit tag corrections retained during later extraction, so that the assistant does not silently undo them. | S07 |
| 17 | an event's identity retained when its tags change, so that its source and chapter links remain intact. | S07 |
| 18 | conflicting accounts to retain their attribution, so that the system does not silently choose a factual winner. | S09 |
| 19 | access to the original evidence behind an event, so that I can review what supports the timeline and prose. | S03 |
| 20 | event records to survive closing the browser and returning later, so that my work is recoverable across sessions. | S10 |
| 21 | conversation to continue while extraction and writing run, so that background work does not interrupt storytelling. | S11 |
| 22 | the first supported private draft after five completed rounds, so that I can see progress early. | S12 |
| 23 | later five-round checkpoints to update relevant writing, so that the draft grows as I provide more memories. | S04 |
| 24 | failed replies and technical retries excluded from the round count, so that milestones reflect actual conversation. | S13 |
| 25 | editing an earlier message to update affected writing without counting as a new round, so that correcting a memory does not change my allowance. | S14 |
| 26 | unchanged passages preserved exactly, so that new memories do not unexpectedly rewrite earlier writing. | S04 |
| 27 | deleted or withdrawn sources removed from eligible derived content, so that earlier drafts do not continue exposing that material. | S15 |
| 28 | an event moved between stage/year groups to update both affected groups, so that it is neither duplicated nor left behind. | S08 |
| 29 | a checkpoint to include extraction through its stated round, so that its coverage label is accurate. | S16 |
| 30 | the latest validated draft available while a newer version runs, so that I can review saved progress immediately. | S17 |
| 31 | to see the round covered by my saved draft, so that I understand how current it is. | S18 |
| 32 | recoverable failures to show a clear retry state, so that quiet background processing does not conceal a stalled update. | S19 |
| 33 | human-edited or approved writing protected, so that automatic enrichment becomes a reviewable proposal. | S20 |
| 34 | chapters grouped around meaningful narrative transitions, so that event indexing does not turn my memoir into disconnected fragments. | S19 |
| 35 | source language and memoir output language kept distinct, so that indexing does not alter my original testimony. | S06 |
| 36 | Chinese and English memories processed through the same event contract, so that language choice does not change persistence behavior. | S13 |
| 37 | background draft checkpoints kept separate from payment and formal-book readiness, so that routine updates do not initiate a purchase or publication. | S21 |
| 38 | As a Family legacy storyteller, I want explicit relationship mentions to trigger family-tree updates, so that my tree grows when relevant information appears. | S22 |
| 39 | As a Family legacy storyteller, I want relevant corrections to an established relative processed, so that the saved tree remains accurate without repeating the relationship introduction. | S22 |
| 40 | ordinary messages without relationship information to leave the family tree unchanged, so that unrelated conversation does not cause unnecessary tree work. | S22 |
| 41 | my events isolated from other users and projects, so that private memories cannot cross ownership boundaries. | S23 |
| 42 | As a returning guest storyteller, I want an authorised account transfer to preserve event identities and source links, so that signing in does not duplicate my story or milestones. | S24 |
| 43 | As an editor, I want timeline and composer to use the same canonical event IDs, so that a correction has one target throughout the project. | S25 |
| 44 | As an editor, I want stale writes rejected with a recoverable conflict, so that concurrent extraction or editing cannot overwrite newer decisions. | S26 |
| 45 | background intents to survive disconnects and restarts, so that saved narrator messages are eventually processed without asking the storyteller to repeat them. | S27 |
| 46 | retries to reuse completed work, so that a failed render or review does not repeat every successful partition task. | S28 |
| 47 | partition preparation to run with bounded concurrency, so that independent work can finish faster without unlimited provider requests. | S11 |
| 48 | obsolete output rejected after a relevant correction or revocation, so that a late job cannot restore outdated or inaccessible content. | S29 |
| 49 | existing event and manuscript references preserved during migration, so that the shared index can replace duplicate indexes without losing prior work. | S30 |
| 50 | acceptance tests driven through the story workflow, so that refactoring internal storage does not require rewriting tests for every helper function. | S12 |
| 51 | later milestones to wait while an earlier background run is active, so that competing jobs cannot overwrite my event structure or draft. | S31 |
| 52 | the next background run to include all accumulated inputs, so that a slow run can catch up across ten or fifteen conversation rounds. | S31 |
| 53 | inputs from a failed background attempt kept pending, so that an unsuccessful run does not silently lose part of my story. | S32 |
| 54 | my durably accepted message retained as evidence even when an assistant reply fails, so that a delivery error does not discard the memory I supplied. | S33 |
| 55 | a stalled background run to reach a configured timeout, so that queued work can recover without waiting forever. | S34 |
| 56 | output from a timed-out worker rejected after a replacement run starts, so that a late response cannot overwrite newer saved state. | S35 |

## Reproducible scenario selectors

Each selector is an actual collected test. Invoke it with `python -m pytest <file>::<selector>`; parameterised cases run together. P is the PostgreSQL/story file, T actual Temporal/worker integration, B the browser workspace file.

| Scenario | File/seam | Exact test selector |
| --- | --- | --- |
| S01 | [P](../tests/test_shared_memory_events_postgres.py) | `test_existing_worker_boundary_commits_canonical_events_and_successful_empty_processing` |
| S02 | [P](../tests/test_shared_memory_events_postgres.py) | `test_empty_extraction_advances_only_its_committed_input` |
| S03 | [P](../tests/test_shared_memory_events_postgres.py) | `test_one_reply_has_distinct_events_and_later_reply_enriches_the_same_identity` |
| S04 | [P](../tests/test_shared_memory_events_postgres.py) | `test_new_evidence_for_an_old_event_changes_its_passage_and_preserves_unrelated_bytes` |
| S05 | [P](../tests/test_shared_memory_events_postgres.py) | `test_similar_events_ambiguous_matches_and_long_periods_share_originals_without_merging` |
| S06 | [P](../tests/test_shared_memory_events_postgres.py) | `test_supported_age_estimates_retain_original_language_expression_and_birth_basis` |
| S07 | [P](../tests/test_shared_memory_events_postgres.py) | `test_explicit_tag_correction_preserves_identity_and_fences_later_model_estimate` |
| S08 | [P](../tests/test_shared_memory_events_postgres.py) | `test_tag_correction_invalidates_old_and_new_groups_without_changing_rounds` |
| S09 | [P](../tests/test_shared_memory_events_postgres.py) | `test_conflicting_attributed_dates_remain_unresolved_until_an_explicit_author_correction` |
| S10 | [B](../tests/test_shared_memory_browser.py) | `test_saved_coverage_and_timeline_tag_edit_survive_browser_reload` |
| S11 | [P](../tests/test_shared_memory_events_postgres.py) | `test_authenticated_chat_completes_while_independent_partition_preparations_are_held` |
| S12 | [P](../tests/test_shared_memory_events_postgres.py) | `test_existing_composer_worker_uses_shared_event_ids_and_originals_without_reextracting` |
| S13 | [P](../tests/test_shared_memory_events_postgres.py) | `test_authenticated_voice_turn_retains_original_chinese_and_failed_reply_does_not_count` |
| S14 | [P](../tests/test_shared_memory_events_postgres.py) | `test_existing_conversation_memory_edit_and_delete_update_canonical_evidence` |
| S15 | [P](../tests/test_shared_memory_events_postgres.py) | `test_source_changes_immediately_hide_dependent_drafts_and_reject_late_output` |
| S16 | [P](../tests/test_shared_memory_events_postgres.py) | `test_composer_checkpoint_waits_for_extraction_and_coalesces_at_claim_time` |
| S17 | [P](../tests/test_shared_memory_events_postgres.py) | `test_latest_validated_draft_is_available_with_coverage_while_update_is_running` |
| S18 | [P](../tests/test_shared_memory_events_postgres.py) | `test_terminal_composer_failure_exposes_a_retry_instead_of_perpetual_updating` |
| S19 | [P](../tests/test_shared_memory_events_postgres.py) | `test_an_unreviewed_or_oversized_canonical_candidate_never_becomes_a_ready_saved_draft` |
| S20 | [P](../tests/test_shared_memory_events_postgres.py) | `test_protected_draft_keeps_its_bytes_and_saves_enrichment_as_a_revision_bound_proposal` |
| S21 | [P](../tests/test_shared_memory_events_postgres.py) | `test_authenticated_saved_draft_returns_shared_coverage_and_keeps_premium_display_gated` |
| S22 | [P](../tests/test_shared_memory_events_postgres.py) | `test_story_workspace_only_dispatches_relationship_tree_and_never_duplicate_timeline` |
| S23 | [P](../tests/test_shared_memory_events_postgres.py) | `test_event_person_and_chronology_references_cannot_cross_project_scope` |
| S24 | [P](../tests/test_shared_memory_events_postgres.py) | `test_capability_transfer_preserves_canonical_ids_draft_dependencies_and_retry_state` |
| S25 | [P](../tests/test_shared_memory_events_postgres.py) | `test_incremental_composition_retrieves_old_dirty_evidence_with_small_continuity_context` |
| S26 | [P](../tests/test_shared_memory_events_postgres.py) | `test_unchanged_heading_is_restored_before_review_and_rendering` |
| S27 | [P](../tests/test_shared_memory_events_postgres.py) | `test_an_acceptance_outbox_failure_rolls_back_original_evidence_and_replay_remains_unique` |
| S28 | [P](../tests/test_shared_memory_events_postgres.py) | `test_bounded_partition_preparation_reuses_successes_after_provider_failure` |
| S29 | [P](../tests/test_shared_memory_events_postgres.py) | `test_withdrawal_prunes_only_the_owners_legacy_execution_cache_before_outbox_acknowledgement` |
| S30 | [P](../tests/test_shared_memory_events_postgres.py) | `test_saved_legacy_composer_cache_is_imported_with_stable_event_and_section_references` |
| S31 | [T](../tests/test_memoir_lanes_temporal.py) | `test_real_worker_and_temporal_coalesce_busy_lane_to_latest_available_inputs` |
| S32 | [T](../tests/test_memoir_lanes_temporal.py) | `test_real_temporal_worker_interruption_recovers_failed_range_without_new_turn` |
| S33 | [P](../tests/test_shared_memory_events_postgres.py) | `test_story_workflow_retains_original_testimony_when_provider_delivery_fails` |
| S34 | [T](../tests/test_memoir_lanes_temporal.py) | `test_configured_deadline_stops_hung_provider_and_exposes_bounded_retry` |
| S35 | [P](../tests/test_shared_memory_events_postgres.py) | `test_failed_and_timed_out_timeline_ranges_remain_pending_and_late_worker_is_fenced` |

Additional passing cases cover old/new grouping invalidation, stale revision conflicts, narrator birth versus a relative's birth, successful empty/out-of-order extraction, link-removal tombstones and surviving overrides, source history/context sanitisation, immutable unrelated passage and heading reuse, ambiguous legacy aliases, current policy fencing, scope-safe cache pruning, separate milestone history versus actual coverage, and the existing twenty-round sample route consuming the shared draft. Both Temporal skill-lane parameterisations cover held arrivals at ten/fifteen/twenty plus round 21, exactly one catch-up, and failed six-through-ten recovery through twenty.

The existing [composer contract suite](../skills/memoir-composer/tests/composer.test.mjs) and [progressive fixture suite](../skills/memoir-composer/tests/progressive_e2e.test.mjs) additionally cover chronological assembly, exact 7000/7001 word boundaries, Chinese segmentation, original-versus-derived evidence, source/asset rights, protected chapter proposals, runtime counter validation and absence of automatic publication. The browser suite covers actual authenticated typed/dictated sends, desktop/mobile tag editing and conflict reload, bilingual stage display, saved coverage/updating and premium-family display/fallback.

## Independent cloud review repairs

The first independent cloud review of PR9 at `996b0806a344eaa4766d0847449f2aa41b2bee9e` found eight introduced defects. Every reported behavior was reproduced locally through the agreed browser, story API or native PostgreSQL RPC/migration seams before its repair. PGlite probes supplied by the cloud reviewer were diagnostic evidence; they are not counted as native PostgreSQL acceptance.

| Finding | Local red result | Kept regression selector |
| --- | --- | --- |
| Authenticated non-greeting sends reference an undefined `sourceKind`. | Actual typed submit displayed `sourceKind is not defined` before API dispatch. | B: `test_authenticated_browser_send_persists_the_original_and_its_input_kind` (typed/dictated) |
| Separate temporal birth basis, stage and relation evidence are not dependency links. | All six edit/withdraw cases left the dependent event active with obsolete evidence. | P: `test_changing_placement_or_relation_evidence_reconciles_the_dependent_event` |
| Proposal-only evidence survives source/event changes. | All four edit/withdraw/tag/unlink cases returned the obsolete protected proposal. | P: `test_proposal_only_evidence_changes_remove_the_proposal_and_fence_older_workers` |
| Empty candidate arrays are mistaken for ambiguity. | A new event became unresolved; existing-event enrichment was rejected. | P: `test_empty_candidates_are_unambiguous_for_new_and_existing_canonical_events` |
| Storyline samples have no section dependencies or immutable reuse. | Two real validated/rendered `chapters=[]` compositions changed unrelated work prose from “I started work in 1975.” to “In 1975, I began working.”; a withdrawal rebuild retried instead of saving safe survivors. | P: `test_genuine_storyline_enrichment_preserves_unrelated_passages_exactly`; `test_recomposed_storylines_hide_changed_evidence_and_reuse_only_surviving_passages` |
| Stage-only UI edits overwrite unchanged date evidence. | The real form stayed open after a rejected correction whose statement supplied no year. | B: `test_saved_coverage_and_timeline_tag_edit_survive_browser_reload` (stage-only/date-only/both/stale, desktop/mobile) |
| Native serialization conflicts are misclassified at the HTTP boundary. | Native SQLSTATE `40001` with documented PostgREST HTTP500 returned API422. | P: `test_stale_event_edits_recognize_native_postgrest_conflicts_without_misclassifying_internal_failures` |
| Supported legacy periods collapse to their first year. | Both migration paths changed 1986–2005 into 1986–1986. | P: `test_legacy_period_import_preserves_both_supported_range_endpoints_and_original_evidence` |

The storyline repair also covers both legacy cache stores through S30: chapter and genuine storyline bundles now keep evidence sections and exact saved prose. The public story route is exercised after repeated source edits/recomposition; old Brisbane prose is withheld on the second edit, and frozen worker output is rejected. Withdrawal rebuilds retain unrelated section bytes and revisions.

The send tests use the actual local page and shipped client, authenticated agent router/runtime, actual streaming private worker and app-server protocol, plus native PostgreSQL transactions. Only external auth/project metadata, media hardware/transcription and model replies are synthetic. The corrected REST fixture obtains the real SQLSTATE from PostgreSQL instead of guessing from an error message. It models the [documented PostgREST status mapping](https://docs.postgrest.org/en/stable/references/errors.html): `40*` is HTTP500. A live PostgREST server is not part of this fixture; the native database error and actual application's HTTP classification are exercised. An unrelated native `XX000` failure stays a generic correction error and exposes no database details.

Red/green logs use `/tmp/issue6-{send,dependencies,candidates,legacy-range,proposals,storyline,storyline-policy,legacy-storyline,conflict}-{red,green}.log`; desktop/mobile date-only/conflict checks use `/tmp/issue6-edits-regression.log`. Setup failures (including a SQL alias collision, HTTP bridge content type, SQL NULL rendering and receipt-drain setup) were corrected and are not treated as behavioral red evidence or passes.

## Verification record

Run date: 2026-10-04, macOS 26.3.1 arm64, Python 3.12.11, pytest 8.4.2, FastAPI 0.142.2, httpx 0.28.1, psycopg 3.3.5, Playwright 1.62.0, Temporal SDK 1.34.0, Next 16.3.6. Installed Node 20.19.4 exercised the initial integration runs; Node 22.22.0 is used for the final supported-runtime checks. The task's web dependencies were reused read-only via an untracked symlink; neither dependency files nor the symlink are included in commits.

| Check | Current result | Evidence |
| --- | --- | --- |
| Canonical PostgreSQL/story acceptance | 90 passed in 258.31s under Node 22.22.0; zero skips. | `tests/test_shared_memory_events_postgres.py`; `/tmp/issue6-review-pg-final.log` |
| Actual Temporal/outbox/private-worker recovery | 6 passed in 91.81s under Node 22.22.0; zero skips. | `tests/test_memoir_lanes_temporal.py`; `/tmp/issue6-review-temporal-final.log` |
| Relevant API/storage/family/preview/private-draft/runtime regressions | 182 passed in 26.44s under Node 22.22.0; zero skips. | Files in command below; `/tmp/issue6-review-regressions-final.log` |
| Browser workspace/stage/family, including real client sends and correction conflicts | 16 passed in 86.34s; zero skips. | Three browser files below; `/tmp/issue6-review-browser-final.log` |
| Composer contracts and progressive fixtures, Node 22.22.0 | 62 passed, zero skipped/cancelled/todo. | `node --test tests/*.test.mjs` |
| Python compile | Passed. | `python -m compileall -q apps/api scripts tests/fixtures/issue6_controlled_app_server.py` |
| Next production build, Node 22.22.0 | Passed after the client send/tag corrections. | `next build --webpack`; `/tmp/issue6-review-web-build.log` |
| Independent cloud rereview and current-main/PR3 integration | First cloud review found eight defects; repaired head still needs independent rereview, review-clear base integration and CI. | Parent handoff |

Canonical and Temporal commands, from the isolated checkout:
```sh
PATH=/opt/homebrew/bin:$PATH MEMOIR_TEST_POSTGRES_BACKEND=apple-container \
  .venv/bin/python -m pytest -q tests/test_shared_memory_events_postgres.py --tb=short
PATH=/opt/homebrew/bin:$PATH MEMOIR_TEST_POSTGRES_BACKEND=apple-container \
  .venv/bin/python -m pytest -q tests/test_memoir_lanes_temporal.py --tb=short
```

Relevant regression command:
```sh
MEMOIR_TEST_POSTGRES_BACKEND=apple-container .venv/bin/python -m pytest -q \
  tests/test_agent_routes.py tests/test_agent_storage.py tests/test_codex_agent.py \
  tests/test_codex_worker.py tests/test_family_agent.py tests/test_family_context.py \
  tests/test_memoir_preview.py tests/test_private_drafts.py tests/test_private_draft_broker.py \
  tests/test_preview_jobs.py tests/test_temporal_dispatch.py tests/test_task_runtime.py \
  tests/test_workspace_latency.py tests/test_response_stage_index.py tests/test_private_rounds_postgres.py
```

Browser command while the isolated frontend is listening at `127.0.0.1:48166`:
```sh
MEMOIR_BROWSER_URL=http://127.0.0.1:48166 MEMOIR_TEST_POSTGRES_BACKEND=apple-container \
  .venv/bin/python -m pytest -q tests/test_shared_memory_browser.py \
  tests/test_stage_readiness_browser.py tests/test_family_tree_browser.py --tb=short
```

Frontend start/build use the source checkout, `NEXT_TELEMETRY_DISABLED=1`, an unused upstream `http://127.0.0.1:49999`, Node 22.22.0 and `--webpack`. The API bridge in browser tests calls the actual authenticated story/agent routers, private streaming worker and PostgreSQL RPCs; synthetic external auth/project metadata and audio/model boundaries are labelled in the fixture. Screenshots were inspected in `output/preview-debug/issue6-event-edit-form-1440.png` and `issue6-event-edit-form-390.png`. No request is sent to the public application.

Failed aggregate attempts are not counted as passes: the first lost a disposable 512 MiB database, later fixture failures exposed missing spans and outbox state leaking between test cases, a frontend start failed its sandbox loopback bind, and a mobile click exposed shrinking navigation. Only the corrected fresh runs above provide evidence. No skipped/unavailable check substitutes for passing coverage.

## Remaining gates and handoff

1. Independent cloud review of the exact pushed task head using the pinned task-only diff range.
2. Owner fixes and fresh cloud delta review for any findings.
3. Deliberate integration of review-clear PR3/current main, preserving concurrent photo and timeline/private-round changes, then rerun overlapping integration checks and CI.
4. Any merge that has production consequences still needs its applicable approval. This branch must not be self-approved, merged or deployed to bypass those gates.
