# PR #150 guidance privacy correction — native validation

Base: `292b71018bbb3a306954e66e7fb30820479153a0` (current `origin/main` when work began and when validation completed).
Task branch: `fix/guidance-private-spans`.
Worktree: `/workspace/copyme2-guidance-privacy`; the original `/workspace/copyme2.ai` checkout was left unchanged.

## Reproduction and correction

An isolated archive of the exact base, with only the new regression test copied
in, reproduced native publication and next-turn delivery of:

> How did the bicycle accident affect your carpentry work?

The controlled guidance response cited only `I worked as a carpenter in Hobart.`
The accident passage was separately marked `withheld` / `privacy_withheld` by
native attribution. This is entirely synthetic data; no real-user disclosure
was observed or used.

The correction subtracts the union of `withheld` and `non_story` attribution
spans before copying guidance evidence. Each surviving fragment is an exact,
contiguous slice of the active source version with original Unicode offsets.
The same helper covers latest/head/tail, canonical and indexed older-window
expansion, fallback evidence, and recent-dialogue response excerpts. Retrieval
terms and canonical event evidence also exclude restricted spans. The native
citation writer retains exact-window validation and rejects restricted quotes.
No text is concatenated across a private gap. Existing context budgets,
publication guards, source high-water marks, receipts and turn snapshots remain
in force. Allowed fragments remain usable without canonical events.

Per `AGENTS.md`, the fresh-install baseline was edited in place. No additive
migration was created or applied to any shared/production database. No prompt,
receipt, deployment, rollout, access configuration or provider was changed.

## Environment and reproducible commands

Existing tools only: Python 3.12.14 from the saved virtual environment and
PostgreSQL 17.11 from `/workspace/.tools/postgresql/usr/lib/postgresql/17/bin`.
No packages were installed. The worktree temporarily reused existing web
dependencies from the original checkout. All database fixtures create their own
temporary local clusters; model/public-source responses use controlled HTTP
fixtures, with external provider dispatch denied by `tests/conftest.py`.

Commands below run from the task worktree unless otherwise noted:

```bash
export PATH=/workspace/copyme2.ai/.venv/bin:/workspace/.tools/postgresql/usr/lib/postgresql/17/bin:$PATH

# Negative control: exact main archive, new regression only (expected failure).
# Ran from /tmp/guidance-privacy-baseline after git archive of the base above.
python -m pytest -q tests/test_interview_guidance_privacy.py \
  -k 'guarded and latest' --tb=short

# Final corrective suite: actual guarded HTTP bodies and native writes/delivery.
python -m pytest -q tests/test_interview_guidance_privacy.py --tb=short

# Repository target, including all JavaScript checks.
make test-place-research

# Its Python portion was run separately after the inherited web failures stopped make.
python -m pytest -q \
  tests/test_place_research_context.py tests/test_place_photo_discovery.py \
  tests/test_place_photo_browser.py tests/test_place_groups.py tests/test_place_geocoding.py \
  tests/test_place_photo_fallback.py tests/test_place_photo_pages.py \
  tests/test_place_photo_persistence.py tests/test_photo_worker.py \
  tests/test_lane_clarifications.py tests/test_timeline_reported_places.py \
  tests/test_lane_b_question_priorities.py tests/test_lane_b_question_priorities_postgres.py \
  tests/test_interview_guidance.py tests/test_interview_guidance_workflow.py \
  tests/test_recall_limit_questions.py tests/test_recall_limit_postgres.py \
  tests/test_two_lane_memory.py::test_confirmations_rank_first_and_survive_the_ordinary_hint_expiry \
  tests/test_two_lane_memory.py::test_confirmation_from_an_earlier_source_window_stays_queued \
  tests/test_background_skill_workflow.py::test_lane_b_confirmation_preempts_the_next_question_and_is_consumed_once \
  tests/test_background_skill_workflow.py::test_model_recognized_control_overrides_a_saved_lane_b_confirmation \
  tests/test_background_skill_workflow.py::test_restored_chengde_period_drives_both_photo_and_news_research \
  tests/test_database_baseline.py::test_one_fresh_baseline_has_no_upgrade_or_backfill_statements \
  --tb=short

python -m unittest discover -s skills/memoir-place-photo-research/tests

# Extended native/engine checks.
python -m pytest -q tests/test_conversation_attribution.py tests/test_two_lane_memory.py \
  tests/test_lifetime_memory_lane_engine.py tests/test_derived_evidence_spans.py \
  tests/test_lifetime_memory_publication.py tests/test_lifetime_policy_atomic_postgres.py \
  tests/test_database_baseline.py --tb=short

git diff --check
```

## Results

| Check | Result |
| --- | --- |
| Exact-base negative control | 1 expected failure, 20 deselected; unsafe question reached the next reply |
| Final privacy suite | **21 passed**, 105.33 seconds |
| Place/research Python portion | **619 passed**, 391.48 seconds |
| Packaged photo-skill unittest suite | **95 passed**, 0.952 seconds |
| Full web prerequisite | 596 passed, 12 inherited failures; 0 skipped |
| Extended native/engine suite, after bounded reruns | 268 passed, 18 inherited failures; no remaining deadline errors |
| Whitespace validation | Passed |

The privacy suite covers mixed passages, Unicode offsets, overlapping and
adjacent restrictions, complete withholding, full source withdrawal, latest
fragments without events, long tails, older canonical evidence, fallback,
indexed retrieval beyond eight recent events, hidden query terms, dialogue
copies, forbidden/cross-gap citations, policy/preference/classification changes
before dispatch and commit, schema retry, and native receipt replay. The broader
guidance workflow suite includes in-flight publication/next-turn snapshot races.

The first extended run reported 219 passed, 19 failed and 48 setup errors. The
publication fixture applies a 180-second deadline to an entire module; two tests
and the following 48 setups hit that deadline. Those 50 cases were rerun in ten
fresh groups of five: nine groups passed 5/5, and one passed 4/5 with the inherited
author-correction failure below. Thus the recovered selection is 49 passes and
one inherited failure. The interrupted launcher was resumed only for groups
whose output files had not been created; completed groups were not duplicated.

### Failures independently checked against pristine main

These are outside the corrective diff and were left unchanged:

* Two attribution tests return HTTP 503 after an author correction because
  policy maintenance is pending:
  `test_unrelated_event_correction_preserves_non_story_and_withheld_classifications`
  and `test_author_removed_links_and_corrected_time_remain_authoritative`.
  Both fail identically when run individually on the exact base.
* `test_derived_evidence_spans.py` has 12 legacy prepared-question contract
  failures; the lane-engine wording-correction test has one expected-error-text
  mismatch. The three database-baseline failures concern pre-existing story-game
  foreign-key indexes, reset coverage and bucket counts. Running these files and
  that one lane-engine test on the exact base yields **16 failed, 27 passed**,
  matching the corrective checkout.
* Twelve `memoir-subscription-report.test.mjs` Make-plan checks reject the
  uninitialized `deps/novel-to-game` gitlink directory while fingerprinting a
  checkout (`Local checkout snapshot requires ordinary files`). The same file
  on a pristine detached base worktree yields **29 passed, 12 failed**. This
  prevents `make test-place-research` from advancing past `test-web`; its Python
  and packaged-skill portions were therefore run explicitly as listed above.
  An initial missing-module error in the new worktree was resolved by reusing
  installed dependencies, without installation or dependency changes.

No selected checks were silently skipped. The entire repository Python suite,
real providers, production databases, managed-prompt publication and deployment
were not run. The inherited failures mean the full repository is not reported
as green.

## Tested code fingerprints

* Baseline SQL SHA-256:
  `2ee9c8a1a4f191a097e207b4ac0c086ec6b67a706af620330a9cc81a77c22fd8`
* Privacy test SHA-256:
  `9f587f3c1545ba59fa0ebd375801d3c3b3781acf5daa1477d436807cc47b062b`

The draft PR records the exact corrective head and the base above for independent
review. Production application and merge remain outside this task.
