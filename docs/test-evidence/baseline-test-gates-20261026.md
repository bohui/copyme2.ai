# Baseline test-gate repair and combined validation

Task branch: `fix/baseline-test-gates-20261026`.
Published code commit: `6b6858af78b1400ee6c0bc372dcfe689d991f432`.
Base: `93d5b383b8aed9fd9b7c206a68187f4b68410281`.

This evidence record is a documentation-only follow-up. Test results refer to
the exact code commit and tree recorded below; the implementation remains unchanged.

## Scope and diagnosis

The authorized repair changes checkout fingerprinting and one stale regression
fixture. It does not change the privacy or age corrections.

The wording-correction test initially failed on main: it expected
`Correction requires timeline placement fields`, but its source contained no
explicit correction wording and correctly hit
`Correction requires explicit correction wording` first. Commit `ac6a149` had
added that earlier guard to match the canonical SQL correction writer. The
fixture now supplies an exact, complete current original containing `Actually,
I meant`, preserving the placement-error assertion. It also proves that removing
`correction` accepts the same ordinary title update, with the original event ID,
expected revision and source evidence. No validator, SQL guard or retry contract
was weakened.

All twelve plan failures came from the new `deps/novel-to-game` Git gitlink.
`git ls-files` returns that directory as one tracked entry; the previous
fingerprinter accepted only files, symlinks and deleted paths. Both plan
launchers therefore raised `Local checkout snapshot requires ordinary files`.
The repair fingerprints an uninitialized gitlink's index pin and initialization
state. An initialized submodule additionally binds its actual HEAD and a
recursive fingerprint of Git-visible contents, preserving ignored-file
exclusion. Arbitrary contents without a submodule Git checkout and substituted
symlinks are rejected. The provenance schema and execution admission remain
unchanged.

Ten new synthetic Git regressions cover pin changes, initialization, tracked
edits/deletions, untracked additions, committed edits, HEAD-only changes,
ignored private environment files, Git-file metadata, nested gitlinks and
invalid directory/symlink substitutions. The first six selected regressions
failed before the implementation, then the complete provenance suite passed.

The exact inherited JavaScript failure names were:

```text
remote Make plan for all cases requires no credentials or native executable pins
remote Make plan for harbour-copper-notebook requires no credentials or native executable pins
remote Make plan for chengdu-tea-ledger requires no credentials or native executable pins
remote Make plan for perth-workshop-compass requires no credentials or native executable pins
remote Make plan for kunming-garden-lanterns requires no credentials or native executable pins
remote Make plan for sydney-platform-letters requires no credentials or native executable pins
Make plan discovers local metadata for all five cases without executing binaries
Make plan discovers local metadata for harbour-copper-notebook without executing binaries
Make plan discovers local metadata for chengdu-tea-ledger without executing binaries
Make plan discovers local metadata for perth-workshop-compass without executing binaries
Make plan discovers local metadata for kunming-garden-lanterns without executing binaries
Make plan discovers local metadata for sydney-platform-letters without executing binaries
```

## Exact inputs and isolation

The fresh supplied standalone checkout initially had clean branch `work` at
`292b71018bbb3a306954e66e7fb30820479153a0`. Fetching the authorized
`https://github.com/bohui/copyme2.ai.git` remote verified main at
`5604571ce41713e3e78eca0d4699fc6ea057e2b8`. The initial task-only code commit was
`5b44bfcb535cfff096390f98a2778af7b626faf4` on that base.

PRs #154, #156 and #155 were externally merged while validation was running.
After fetching and verifying current main, only the unpublished repair was
rebased, then pushed once. Neither the age branch nor the privacy branch/PR
metadata was changed by this task.

| Final input | Exact commit |
| --- | --- |
| Current main, including age, localization and privacy corrections | `93d5b383b8aed9fd9b7c206a68187f4b68410281` |
| Separate published repair | `6b6858af78b1400ee6c0bc372dcfe689d991f432` |
| Reviewed privacy head | `f7a2ce60416f1d17a685775bc7b68d7c743ef625` |
| Reviewed age head, verified ancestor of main | `651b61cba108e4a238cc7f67bc1298885a1f9a14` |
| External localization head, verified ancestor of main | `e20338d2323c19237a3eef3ff92c4499893be543` |
| Final combined checkout commit | `6b6858af78b1400ee6c0bc372dcfe689d991f432` |
| Final combined checkout tree | `cd51181bf6dd26a9e4cd12600a4a361c3c8910b3` |

`git merge-tree --write-tree` and local `git commit-tree` constructed the earlier
assemblies, checked out detached in a disposable standalone local clone at
`/tmp/copyme2-baseline-combined`. After both corrections were externally merged,
the final clone simply checked out the exact task-only repair commit on current
main. No Git worktree was created; no assembly merge commit was published. The
privacy and age patches were not applied again to current main.

The initial four-input assembly, before the age merge was observed, was commit
`ec461bac697ae9e6c0c7929dca32aaf26352fc90`; its tree is byte-for-byte identical
to the second assembly `a778acb6189efa4778d141a738ba085672e959e0`, built from
main `fcfcb0132327d2eee71e5cf0c591ab4698b05daa`, repair
`b26bf78b84adc929c836f0b8c9cef12206a80267` and the exact privacy head. Both trees
are `f2499f8bd0017499b6f279ff89c6fdb00571d3e9`; both complete Make runs are
retained. The final tree differs from them only in the two localized message
files and `tests/js/background-skills.test.mjs` from external PR #156.

Tools: Python 3.12.14, Node 26.11.1, native PostgreSQL 17.11, Chromium
154.0.8037.57. Each database fixture owned a fresh temporary cluster and
loopback port with synthetic data. Only one heavy test command ran at a time.
External provider dispatch was denied by the repository fixtures. Existing web
dependencies were reused in a real ignored `node_modules` directory through
package symlinks. No packages or privileged dependencies were installed.
LayerFS and `/dev/fuse` were absent; no mount or LayerFS usage is claimed.

## Commands and outcomes

Activate the saved environment in each shell:

```bash
source /workspace/.setup/copyme2/activate.sh
```

Initial negative controls, from the task checkout on main `5604571`:

```bash
python3 -m pytest -q tests/test_lifetime_memory_lane_engine.py::test_wording_correction_requires_an_ordinary_event_update_instead_of_an_empty_placement_patch
node --test --test-name-pattern='remote Make plan|Make plan discovers local metadata' tests/js/memoir-subscription-report.test.mjs
# After adding the first six synthetic regressions, before the implementation:
python3 -m pytest -q tests/test_subscription_local_checkout.py -k gitlink
```

Results: **1 expected transport failure**; **12 expected plan failures**;
**6 expected new-regression failures, 11 deliberately deselected**. The later
age merge changed none of the files responsible for these baseline failures.

The repaired branch before rebase passed the entire subscription-report file
with **41 passed**, and provenance plus lane/publication/policy/SQL-definition
checks with **145 passed**. The final combined commands below include these
checks again, including all twelve originally failing plan cases.

From `/tmp/copyme2-baseline-combined`, the preceding assembly used these exact
selections. The final published repair runs all three pytest selections together
as one 341-case aggregate; its exact full command is retained in `commands.txt`.

```bash
python3 -m pytest -q tests/test_interview_guidance_privacy.py \
  tests/test_interview_guidance_derived_privacy.py \
  tests/test_interview_guidance_remaining_privacy.py --tb=short

python3 -m pytest -q tests/test_subscription_local_checkout.py \
  tests/test_lifetime_memory_lane_engine.py tests/test_lifetime_memory_transport.py \
  tests/test_lifetime_memory_publication.py tests/test_lifetime_policy_atomic_postgres.py \
  tests/test_database_baseline.py::test_all_function_definitions_validate_with_their_final_dependencies \
  tests/test_shared_memory_events_postgres.py::test_new_stage_evidence_is_an_ordinary_update_without_explicit_correction_wording \
  --tb=short

# Restore only the committed source dependency, without upgrading it:
git submodule update --init -- deps/novel-to-game

python3 -m pytest -q tests/test_novel_game_journey.py tests/test_novel_game_assets.py \
  tests/test_novel_to_game_experiment.py tests/test_memoir_story_game.py \
  tests/test_story_game_runtime.py tests/test_higgsfield_game.py --tb=short

python3 /tmp/copyme2-baseline-repair-evidence/age_browser_probe.py
make test-place-research
node --check experiments/novel-to-game/runtime/journey-runtime.js
git diff --check
```

Final published-code aggregate, on `6b6858a`:

```bash
python3 -m pytest -q tests/test_interview_guidance_privacy.py \
  tests/test_interview_guidance_derived_privacy.py tests/test_interview_guidance_remaining_privacy.py \
  tests/test_subscription_local_checkout.py tests/test_lifetime_memory_lane_engine.py \
  tests/test_lifetime_memory_transport.py tests/test_lifetime_memory_publication.py \
  tests/test_lifetime_policy_atomic_postgres.py \
  tests/test_database_baseline.py::test_all_function_definitions_validate_with_their_final_dependencies \
  tests/test_shared_memory_events_postgres.py::test_new_stage_evidence_is_an_ordinary_update_without_explicit_correction_wording \
  tests/test_novel_game_journey.py tests/test_novel_game_assets.py tests/test_novel_to_game_experiment.py \
  tests/test_memoir_story_game.py tests/test_story_game_runtime.py tests/test_higgsfield_game.py --tb=short
make test-place-research
```

| Completed preceding-assembly check | Outcome |
| --- | --- |
| Original and both independent-review privacy modules | **41 passed**, 116.28 s |
| Provenance, lane engine, ASGI transport, native publication/policy, SQL definitions and correction contract | **180 passed**, 19.54 s |
| Age/journey/asset/adapter/story-game selection after source dependency restoration | **120 passed**, 2.55 s |
| Native whitebox browser probes | **2 viewports passed**, 1280×900 and 390×844 |
| Required `make test-place-research`, first four-input assembly | **608 web + 619 Python + 95 packaged-skill passes**, one Python cleanup warning |
| Required `make test-place-research`, second assembly on main `fcfcb01` + privacy | **608 web + 619 Python + 95 packaged-skill passes**, one Python cleanup warning |

| Final published-head check | Outcome |
| --- | --- |
| Privacy + transport/provenance + age aggregate on `6b6858a` | **341 passed**, 151.00 s; 41 privacy + 180 transport/provenance + 120 age |
| Native whitebox browser probes on `6b6858a` | **2 viewports passed**, 1280×900 and 390×844; zero page errors/external requests |
| Required `make test-place-research` on `6b6858a` | **610 web + 619 Python + 95 packaged-skill passes**, one Python cleanup warning; Python 208.33 s |
| JavaScript syntax and diff whitespace | **Passed** |

All completed successful aggregates have zero failures, skips or deselections.
No fixture-deadline recovery has been needed. The latest complete Make run and
both preceding complete runs emitted the same single Python subprocess-cleanup
warning; it was not suppressed or treated as a failure. The initial equivalent-tree Make
run passed **608 web + 619 Python + 95 packaged-skill tests**; it emitted one
`PytestUnraisableExceptionWarning` about subprocess cleanup after an event loop
closed in `test_current_api_photo_keeps_its_normalized_day_in_the_client`.

Environment recovery is recorded separately from clean aggregate runs:

* The first age run had **113 passed, 7 failed** because this fresh container
  had no initialized NovelToGame dependency and the linked skills were absent.
  Restoring exactly `c3075f35cc14d4bc94e2829df2bfcc0d9971229e` through the existing
  repository dependency command left the assembly clean. The full 120-case
  command was then rerun and passed; no test or assertion was changed.
* The first browser attempt was blocked before application execution by managed
  Chromium's `file://` navigation policy. The successful probes served the same
  generated fixture from a task-owned ephemeral loopback HTTP port, preserving
  browser security settings and aborting any external request. Both viewports
  verified one shared scene, a child avatar, Age 8 → Age 9 → Age 8, unique-memory
  counts 1 → 2 → 2, exact source fidelity, full-source reading and restart, with
  zero page errors or external requests. Physical touch input was not tested.

## Remaining limits and review

The separate native failures previously reported in PR #155 (author-correction
policy maintenance, legacy prepared-question contracts, and database baseline
index/reset/bucket coverage) were not reopened or repaired. They concern other
contracts and schema coverage and require separately scoped authorization.
The full repository Python suite is not represented as green.

The privacy SQL was tested only through fresh installs in disposable databases.
The required single baseline migration remains in place. No production upgrade
artifact was added or applied. No live provider, production database, prompt
publisher, deployment, workflow trigger, merge or auto-merge was invoked.

The task-only branch and [draft PR #157](https://github.com/bohui/copyme2.ai/pull/157)
are published for independent cloud review.
Subsequent repair changes should return to this coding owner. Raw logs, exact
assembly manifests, the runnable browser probe, screenshots and repair patch are
retained in the task evidence archive identified in the final handoff.
