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

The first envelope audit reproduced two further copies in continuity pins and
delivered-question evidence. Private continuity records are omitted and marked
incomplete. Independent review then established that even an allowed citation
does not authorize stored event/continuity prose. Guidance now omits event
titles, uncertainty and temporal-expression prose; it rebuilds continuity text
from an authorized original quote and clears free-form uncertainty. Question
prose/evidence, active-question wording and optional unresolved-reference labels
are omitted. Delivered question IDs are stable opaque hashes bound to their
actual delivery, so arbitrary collector strings cannot carry private prose into
cadence context. The original canonical records and delivered IDs are unchanged.
If a mandatory restriction itself quotes a withheld span, the optional
guidance page completes without model dispatch. Its original mandatory policy
remains intact. This fail-closed case deliberately produces no new Lane B
guidance rather than weakening a restriction or sending its private prose.

| Model-visible field | Boundary checked |
| --- | --- |
| `source`, `guidance_context.source_windows` | Exact contiguous authorized originals and canonical Unicode offsets |
| `events` | Bounded identity/typed context and authorized source references; generated title, uncertainty and temporal-expression prose omitted |
| `recent_dialogue.response` | One authorized excerpt with truthful completeness/offsets |
| `recent_dialogue.question` | Generated prose/evidence omitted; a stable opaque delivery alias supports cadence and replay |
| `preferences.known_continuity` | Unavailable records omitted; allowed text rebuilt extractively; generated uncertainty omitted |
| `preferences.active_question`, `unresolved_references` | Optional generated wording omitted |
| Mandatory policy pins | Original controls preserved; guidance skips if mandatory policy needs a withheld quote |
| Name/language/mandatory manual policy pins | Existing authoritative user preferences remain unchanged |
| `news_clues` | Existing public-field allowlist and exact news revision/digest checks; personal hypotheses/relevance are not included |
| Retrieval terms / IDs | Terms use authorized originals; returned event IDs contain no original prose |
| `lane_context` / fence / retry | Same filtered pins and evidence; fixed retry code; no free-form error feedback |

Per `AGENTS.md`, the fresh-install baseline was edited in place. No additive
migration was created or applied to any shared/production database. No prompt,
receipt, deployment, rollout, access configuration or provider was changed.
These tests install the complete baseline into empty disposable databases.
An existing database that already records `202610180001` as applied will not
receive these edited function definitions from an ordinary migration push.
Applying the correction there requires a separately approved upgrade artifact
containing the reviewed definitions and validation for that existing schema.
That upgrade/application was neither performed nor claimed by this task.

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

# Independent-review regressions, including normal reply-v2 continuity output.
python -m pytest -q tests/test_interview_guidance_derived_privacy.py --tb=short

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

# Final envelope revision: transport/publication/policy and native SQL definitions.
python -m pytest -q tests/test_lifetime_memory_lane_engine.py \
  tests/test_lifetime_memory_publication.py tests/test_lifetime_policy_atomic_postgres.py \
  tests/test_database_baseline.py::test_all_function_definitions_validate_with_their_final_dependencies \
  -k 'not wording_correction' --tb=short

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
| Initial core privacy suite, retained as requested | **21 passed**, 105.33 seconds |
| Privacy suite at reviewed head `262fafa9`, including first envelope audit | **24 passed**, 144.88 seconds |
| Original privacy suite after independent-review correction | **24 passed**, 173.47 seconds |
| Added independent-review regressions | **13 passed**, 122.95 seconds |
| Place/research Python portion on the initial core correction | **619 passed**, 391.48 seconds |
| Packaged photo-skill unittest suite | **95 passed**, 0.952 seconds |
| Full web prerequisite | 596 passed, 12 inherited failures; 0 skipped |
| Extended native/engine suite on the initial core correction, after bounded reruns | 268 passed, 18 inherited failures; no remaining deadline errors |
| Transport/publication/policy and SQL definitions at `262fafa9` | **123 passed**, 1 explicitly deselected inherited wording test, 25.31 seconds |
| Full transport/publication/policy and SQL definitions after review correction | **123 passed, 1 inherited failure**, 28.11 seconds; no deselection |
| Whitespace validation | Passed |

The privacy suite covers mixed passages, Unicode offsets, overlapping and
adjacent restrictions, complete withholding, full source withdrawal, latest
fragments without events, long tails, older canonical evidence, fallback,
indexed retrieval beyond eight recent events, hidden query terms, dialogue
copies, forbidden/cross-gap citations, policy/preference/classification changes
before dispatch and commit, schema retry, and native receipt replay. The broader
guidance workflow suite includes in-flight publication/next-turn snapshot races.
The three added envelope cases first failed on the core correction, then passed
with native continuity, delivered-question and mandatory-policy fixtures.
The same 619-case Python selection is being rerun on the envelope revision;
its completed result is recorded in the draft PR and retained command logs.

## Independent-review correction on `262fafa9`

Review identified three remaining privacy paths despite the passing 24-case
suite: canonical event title/uncertainty with allowed evidence, continuity
uncertainty through normal reply-v2 extraction output, and arbitrary collector
question IDs. It also demonstrated that eight early authorized fragments could
exhaust the window budget before an authorized tail containing a recall limit.

The new regression module reproduces native publication and next-turn delivery
of the unsafe question with allowed citations. It includes verbatim and
paraphrased private prose, continuity text and uncertainty, the normal reply-v2
model-output path, three deliveries using a private sentence as their ID,
repeat page reads, native commit replay and valid cadence using opaque aliases.
Two tail cases cover both a full eight-window budget and a tail already present
later in the window list. The corrected reader reserves/promotes the latest
authorized tail before filling the remaining slots, still capped at eight.

Negative control against the exact reviewed SQL used the existing workspace and
test harness, without a new worktree or file rollback. A process-local read seam
supplied `git show 262fafa9b705b9603ea0efd9a52f758861da8a7e:supabase/migrations/202610180001_initial_schema.sql`
only when the native fixture read that migration. Its SHA-256 was
`f53c534e52dffc0d0b96e3518cfd4690890f8c3dd81ab6c0350243e549f88981`.
Running the new module with `-k 'True or collector_ids or fragmented'` produced
**5 expected failures, 8 deselected** in 39.78 seconds. These are the two normal
reply-v2 cases, two tail cases and the collector-ID case. Earlier verbatim and
paraphrase event/continuity probes also failed before the correction. No keyword
filter is used: optional generated prose is omitted or reconstructed from the
authorized originals regardless of whether it literally matches a withheld span.

The required `make test-place-research` gate was run again after this correction:
**596 web passes and the same 12 inherited Make-plan failures**, with zero skips;
Make therefore exits at `test-web`. Its full 619-case Python selection is run
separately. The full 124-case transport selection now reports its inherited
wording assertion failure explicitly rather than deselecting it.

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
  `abddf5fbc9096ed9ddf4d1669d9dade16c6e7c2ad63a0f568e74c2f6870f1917`
* Privacy test SHA-256:
  `b968488df81a26c7a422cf7e52ad9848abbf59ea20139d35b708ecee8c84fa55`
* Independent-review regression SHA-256:
  `c8f54d0248aa6efcfe1dd7fb8e07cd0509219481c6eac59862c271e6f157ba41`

The initial core run is commit `9d47e199c2d121ba34b0d410184df8b01e410cbb`.
Its 21-case test file was used for the exact-base negative control above. Raw
command logs are retained outside the checkout under
`/workspace/guidance-privacy-validation-20261026/` for the coordinating reviewer.

The draft PR records the exact corrective head and the base above for independent
review. Production application and merge remain outside this task.
