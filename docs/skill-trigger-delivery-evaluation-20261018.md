# Memoir skill trigger and delivery baseline

Evaluated on 18 October 2026 against the existing Langfuse project `memior`
(`cmut9t75w00071z02n8bdv7it`). All inputs were fictional or public research queries.

The initial corrected trigger suite passed **54 assertions** across all nine registered
skills. Seven skills have implemented runners; family-tree is **unwired** and
story-game is **unavailable**. Their rejection checks pass, but successful
production execution cannot be certified. Independent live delivery probes
finished **16 passed, one failed, two unavailable** across 19 cases.

| Skill | Current trigger checks | Live delivery probes |
| --- | --- | --- |
| `memoir-author-timeline` | Passed: accepted-source processing, reply-only exclusion, delivery/replay authority | English and Chinese grounded extraction passed |
| `memoir-composer` | Passed: five-round cadence, empty checkpoints, preservation of unchanged prose | English and Chinese round 5 → 10 pipelines passed |
| `memoir-family-tree` | Entitlement and admission checks passed; production runner is unwired | Explicit mother/biographical introduction probe passed in isolation |
| `memoir-historical-news-research` | Passed: after-delivery scheduling, lease release, negative gates, cache/deduplication | Unverified-lead rejection passed; native search unavailable |
| `memoir-memory-context` | Passed: SQL checkpoints, manual locks, stopped parsing, empty/protected targets | All seven profile probes passed, including both languages |
| `memoir-place-groups` | Passed: grouping, project ownership, independent pins, completed-work receipts | Instruction probe passed; production grouping remains deterministic |
| `memoir-place-journey` | Passed: shared extraction pass, absent/uncertain/unmentioned-place exclusions | Both named places were delivered |
| `memoir-place-photo-research` | Passed: independent work, cache reuse, scoped pagination, authorization | Unverified-lead response failed JSON framing; native search unavailable |
| `memoir-story-game` | Negative admission checks passed; production generation unavailable | Missing-authority rejection passed; no game-generation claim |

## Findings

1. **Two skill packages cannot currently run successfully in the canonical
   application.** `apps/api/background_skills.py` marks family-tree `unwired` with
   no runner and story-game `unavailable` with no runner. The standalone family
   output and game rejection probes do not establish production integration.
2. **The gateway rejected both native search probes.** Each returned HTTP 400
   classified as `max_tool_calls_rejected`. No completed native search or
   independently verified historical clue/photo was produced in those cases.
3. **A photo response was not one JSON document.** The unverified-lead probe
   returned five concatenated copies of the otherwise expected JSON object.
   The validator rejected it as `repeated_json_documents`; it was not repaired
   or counted as a pass. This establishes a response-framing failure, not its
   root cause inside the gateway/model path.

Both composer pipelines retained an unchanged passage and incorporated new
original evidence. Their synthetic prose and source links were inspected;
the contract scores do not constitute calibrated human editorial acceptance.

## Langfuse evidence

Two new datasets were created and read back:

- `memoir/evaluation/skill-triggers`: nine groups, each invoking actual
  application checks with controlled provider replies and disposable PostgreSQL.
- `memoir/evaluation/skill-deliveries`: 19 cases using real gateway replies,
  independent validators, bilingual composition, and native-search requirements.

All **69 managed prompt artifacts** matched their exact pinned Langfuse versions
before execution. Expected outputs were withheld from model packets. Dataset
contents were checked before dispatch, and each experiment used a timestamp-pinned
snapshot. Credentials were read privately from the existing files.

| Experiment | Langfuse ID | Items | Interpretation |
| --- | --- | ---: | --- |
| Initial trigger baseline | `20e6b8bc73955097` | 9 | Preserved; includes stale-test failures |
| Initial live deliveries | `28f78dbb29825152` | 19 | Real responses; three cases stopped before dispatch at the original call cap |
| Corrected current trigger suite | `d1a42b11b55b7808` | 9 | Authoritative trigger baseline; 54 assertions passed, two capabilities unavailable |
| Remaining profile deliveries | `0850785799475a83` | 3 | Only the three previously unexecuted cases; all passed |

All **40 experiment items** were verified through the Langfuse v4 experiment API:
dataset identity, exact inputs, expected outputs, actual outputs, and matching
scores. Unavailable cases receive categorical availability results instead of
numeric passing credit. See the [machine-readable receipt](test-evidence/skill-evaluation-20261018.json).

The first trigger selection mistakenly included retired runtime methods and an
outdated profile fixture. Only this evaluation's new trigger dataset was revised;
the original timestamp snapshot and experiment remain available. The corrected
suite uses current canonical admission and profile scheduling checks.

The first live run used a 32-dispatch cap. Composition required 18 calls, leaving
three profile cases unexecuted. Those three were completed separately; the actual
photo/search failures were retained. Across the live experiments there were
**35 HTTP dispatches**, **33 provider response IDs**, and reported usage of
**156,392 input / 38,811 output tokens**. Internal gateway retries and monetary
cost are not established. The reusable runner now allows 48 dispatches, with one
case at a time, no transport retries, 120 seconds per call, and a 30-minute live
deadline. Each trigger group has a five-minute bound.

## Reproduce

```sh
# Inspect dataset coverage and hashes without network or model calls.
python3 scripts/run_memoir_skill_evaluation.py

# Verify/pin the hosted datasets and run both phases.
python3 scripts/run_memoir_skill_evaluation.py --execute

# Trigger checks only, with controlled replies and isolated local databases.
python3 scripts/run_memoir_skill_evaluation.py --execute --phase triggers

# Recheck one delivery from the hosted dataset.
python3 scripts/run_memoir_skill_evaluation.py --execute --phase deliveries \
  --case photo-reject-unverified-lead

# Offline runner/evidence-boundary checks: 61 passed.
python3 -m pytest -q tests/test_memoir_skill_evaluation.py tests/test_memoir_live_skills.py
```

Local full outputs, checkpoint documents, JUnit reports and receipts are under
`var/skill-evaluation/skills-20261018T044320Z/`,
`var/skill-evaluation/skills-20261018T044657Z/`, and
`var/skill-evaluation/skills-20261018T044917Z/`.

This baseline separates controlled application checks from live isolated output
checks. It does not certify live end-to-end scheduling or production persistence
of model-generated artifacts. It changes no production skill, gateway setting,
entitlement, deployment, or user data.


## Follow-up after game integration

The original results above describe the frozen baseline. Follow-up work added a
private game runtime with exact-original validation, person/candidate approval,
server-owned jobs, guarded delivery and a fixed browser renderer. Two real
browser flows and 15 PostgreSQL checks passed using controlled external models;
this does not claim completion of the live five-case game goal.

The new versioned datasets preserve the original prompt-bearing dataset:
`memoir/evaluation/v2/skill-triggers` and
`memoir/evaluation/v2/skill-deliveries`. All 70 managed prompt artifacts were
verified. Experiment `1435168b1e0d6f2e` contains nine trigger groups and 79 passing
assertions: all eight implemented skills pass, while family-tree remains
categorically unavailable because its runner is unwired.

The unsupported `max_tool_calls` parameter was removed from the evaluation
harness and production photo adapter. Native search probes still failed:
experiment `44c4ffe697da7051` recorded a completed photo response without the
required search receipt and a news timeout; experiment `b9e18a87d6e5e81c`
recorded the low-reasoning follow-up.
The low-reasoning follow-up timed out on both probes. These remain failed or
unavailable results. No URLs or model prose were promoted to verified sources.

Experiment `3b3cc834ee8d7d53` rechecked the changed game admission prompt and the
photo negative probe: missing-authority game rejection passed; the photo response
again contained repeated JSON documents and failed. The machine-readable receipt
contains the exact experiment identities and results for every follow-up.

Experiment `00c4d72e3e789cf9` then exposed a concrete decoder defect: the gateway
returned two completed native search calls, but the news adapter required exactly
one. The adapter now accepts up to four completed calls and keeps each source
bound to the call that actually discovered it. Production photo requests also
use the supported flat search protocol and preserve long, bounded receipt IDs.
The affected photo/protocol checks passed (160 checks); news provider, validation
and PostgreSQL checks passed (138 checks).

The bounded follow-up `a59294cef64248fd` completed native news discovery, but
neither returned Wikipedia page could be independently fetched by the production
verifier. Its result remains `no_independently_verified_historical_clue`.
Photo discovery in the preceding run timed out. Native discovery is therefore
still not certified as a successful delivered photo or historical clue. No
source-validation requirement was weakened and no blind retry was counted as
passing evidence.

The source failure was subsequently reproduced as a 512 KB HTML limit: both
returned pages were larger. A separate 2 MB source limit now admits ordinary
article pages; the 512 KB gateway-response limit, public URL/robots rules and
source-process output/time limits remain enforced. Its regression was observed
failing first; 235 affected checks now pass. Reinspection of the retained native
output made no new model calls and fetched both pages successfully, but their
claims still failed the independent evidence validator. The original failed
experiment was not rewritten. Reinspection metadata is retained under
`var/skill-evaluation/skills-20261018T060706Z/historical-source-reinspection-2mb.json`.

The final trigger rerun at this stage, `f64778dd2ade1edc`, uses the updated code
and all 70 pinned prompts. All eight implemented groups pass again (79 assertions
across nine groups, including family-tree's negative admission checks). Family-tree
remains categorically unavailable. All nine experiment items and scores were read
back successfully; this run dispatched no live model calls.

## Judge prompt update and reset preparation

After those experiments, all four `memoir/evaluation/` judge prompts were updated
in Langfuse to v2: `five-case-judge`, `five-case-judge/guard`,
`trajectory-judge/system` and `trajectory-judge/rubric`. Trigger gating and verified
delivery are assessed separately, with actual saved-state, provider/source and
browser witnesses required for delivery claims. Unobserved categories receive no
numeric score. Calibration remains pending human review; no historical experiment
is relabeled as having used these new prompts. All 70 managed artifacts matched
their exact remote versions. The game runtime contract is v3.

The Supabase migrations are consolidated into `202610180001_initial_schema.sql`.
Two disposable databases confirmed equivalent catalogs for the original chain
and merged baseline, including all 362 functions, 111 relations and their access
controls. The Supabase CLI fresh/repeat push and disposable reset/reapply passed.
Both complete browser game flows also passed against the consolidated schema.
Broader checks retain nine legacy execution-contract fixture failures and three
canonical background-lane retry failures; the full evaluation is not all green.
See `docs/five-case-full-e2e-20261018.md` for the preserved 49-reply campaign state
and reset handoff. The configured database was not reset.
