# Memoir five-case E2E/evaluation report

Date: 2026-10-03 UTC  
Run: `live-five-case-shared-20261003`  
Runner: `memoir-five-case-runner/2`  
Application revision: `762547e85c527a307dc4c636c3c6045488784bf8-dirty-ebcfd66b5170`

## Outcome

The requested live execution completed all five synthetic biographies with
exactly 50 conversation rounds each: **250/250 rounds**. A round is one
model-visible storyteller response followed by completed assistant handling
through the normal application/runtime boundary. The run is **not a semantic
pass**: deterministic evaluation found 77 failures and 13 unavailable rounds,
and no separate semantic judge was configured.

| Case | Rounds | Pass | Deterministic fail | Unavailable | All seven stages |
|---|---:|---:|---:|---:|---|
| `harbour-copper-notebook` | 50/50 | 25 | 21 | 4 | yes |
| `chengdu-tea-ledger` | 50/50 | 34 | 15 | 1 | yes |
| `perth-workshop-compass` | 50/50 | 31 | 15 | 4 | yes |
| `kunming-garden-lanterns` | 50/50 | 30 | 19 | 1 | yes |
| `sydney-platform-letters` | 50/50 | 40 | 7 | 3 | yes |
| **Total** | **250/250** | **160** | **77** | **13** | **5/5** |

All biographies and project IDs are fictional and isolated (`eval-*`). The
hidden truth file, expected outcomes, judge prompt, and calibration data were
kept separate from model-visible round text. No customer biography, family,
address, private photo, production migration, or shared-service restart was
used.

The earlier `fixture-five-20261003-final` and bounded fixture pilot remain
available as **mock-only** harness/persistence controls. They are not included
in the live pass/fail totals above and do not support a model-quality claim.

## Genuine provider path

The live runner used the configured provider and a private worker; it did not
fall back to a fixture, direct skill invocation, or another model:

- configured gateway: `http://192.168.66.1:4000/v1`
- configured model: `gpt-5.6-luna-pooled`
- configured reasoning effort: `max`
- exact production path: `CodexRuntime.turn -> private codex-worker /internal/codex/turn -> Codex CLI -> llm_provider gateway`
- runner worker endpoint: `http://192.168.66.126:8766`
- photo worker endpoint: `http://192.168.66.125:8767`
- preflight: provider, worker, and photo worker HTTP 200; blockers `[]`
- synthetic inference receipt: [provider-inference-probe.json](../var/memoir-five-case-evaluation/live-five-case-shared-20261003/provider-inference-probe.json), HTTP 200, response `LIVE`, inference model `gpt-5.6-luna-pooled`

The earlier reported `192.168.68.1:4000` gateway was unreachable; the live run
used the currently configured `192.168.66.1:4000` gateway after preflight
verified it. No model/provider change was made by the evaluator.

The saved manifest records host `codex-cli 0.155.1`; the inspected private
worker container ran `codex-cli 0.156.1`. That version skew is recorded as a
reproducibility risk, not hidden. The worker had no fixture/mock environment
flag, and the round traces contain `trace_mode: "codex-worker"` plus private
worker request receipts.

Provider token/cost fields were not exposed. The final regraded manifest and
case summaries retain the sum of per-round receipts: **524 private-worker
requests**, with input/output/total tokens and cost recorded as unavailable.
The original provider probe and every case trace are retained under the run
directory.

## Stage coverage

Counts are observed persisted stage assignments, not merely words in the
prompt. Column order is `baby / toddler / childhood / adolescence /
young_adulthood / midlife / later_life`.

| Case | Observed stage counts |
|---|---|
| Harbour | 3 / 4 / 10 / 5 / 8 / 8 / 12 |
| Chengdu | 4 / 4 / 8 / 7 / 7 / 8 / 12 |
| Perth | 4 / 4 / 8 / 7 / 7 / 8 / 12 |
| Kunming | 3 / 2 / 10 / 7 / 8 / 7 / 13 |
| Sydney | 3 / 5 / 11 / 4 / 7 / 8 / 12 |

## Seven-skill grades

The deterministic contract grades invocation and output/state separately. Each
cell is `required invocation / required output; negative must-not-call pass /
negative scenarios; unavailable`, so optional unasserted calls are not counted
as failures. For `memoir-composer`, the positive contract is three checkpoints
per case; its 0/3 values reflect one deterministic failure and two unavailable
checkpoints, not a skipped test.

| Case | memory-context | place-journey | place-groups | family-tree | author-timeline | photo-research | composer |
|---|---|---|---|---|---|---|---|
| Harbour | 48/50; – | 15/16; 8/9 | 15/16; 8/9 | 5/16; 9/9 | 9/21; 9/9 | 2/2; 10/10 | 0/3; 10/10; U2 |
| Chengdu | 49/50; – | 18/18; 9/9 | 18/18; 9/9 | 3/9; 9/9 | 3/15; 12/12 | 2/2; 12/12 | 0/3; 12/12; U2 |
| Perth | 49/50; – | 17/17; 9/9 | 17/17; 9/9 | 7/15; 8/8 | 12/20; 8/9 | 1/2; 10/10; U1 | 0/3; 10/10; U2 |
| Kunming | 49/50; – | 19/19; 10/10 | 19/19; 10/10 | 0/8; 10/10 | 0/15; 12/12 | 2/2; 12/12 | 0/3; 12/12; U2 |
| Sydney | 49/50; – | 19/19; 10/10 | 19/19; 10/10 | 9/12; 9/9 | 13/17; 9/10 | 2/2; 10/10 | 0/3; 10/10; U2 |

The strongest live results were persisted place journey/group behavior and
memory-context (generally 96–100% positive invocation/output). The main
remaining orchestration/quality failures were missing positive
`memoir-author-timeline` and `memoir-family-tree` invocations, especially
Kunming (0/15 and 0/8), plus a small number of unnecessary negative calls.
Those are actionable failures, not judge-suppressed results.

## Photo-search budget and evidence

The bounded budget was 10 planned calls, one per positive photo scenario per
case, and **10/10 executed**. Negative rounds made no external search call.
Results were recorded as public reference metadata only; unknown rights were
never treated as permission.

| Case | Current-day result | Historical result |
|---|---|---|
| Harbour | Hobart, PARTIAL, 2 items | Hobart 1978, PARTIAL, 3 items |
| Chengdu | 成都, READY, 10 items | 成都 一九八八, NO_MATCH, 0 items |
| Perth | Perth, UNAVAILABLE | Fremantle 1989, PARTIAL, 2 items |
| Kunming | 昆明, READY, 10 items; 7 rights unknown | 昆明 一九九〇, NO_MATCH, 0 items |
| Sydney | Sydney, PARTIAL, 7 items | Sydney 1990, PARTIAL, 1 item |

No source-photo download or rights claim was fabricated. Partial/NO_MATCH /
UNAVAILABLE outcomes remain visible in the per-round UI observation and case
summary.

## Composer and provider failures

The original unbounded live runner stalled in Harbour's first composition
checkpoint after approximately 356 seconds and the worker log showed a real
HTTP 504. I stopped only that local runner after 43 saved rounds, added a
bounded `asyncio.wait_for` composer deadline plus explicit HTTP-status and
timeout classification, and resumed the same run ID. The completed run now
records the following unavailable infrastructure outcomes:

- Harbour: composer HTTP-status/timeout checkpoints at rounds 20 and 25,
  runtime timeout at 40, worker-turn failure at 50.
- Chengdu: worker-turn failure at 50.
- Perth: photo/worker availability at 12, composer timeouts at 20 and 25,
  worker-turn failure at 50.
- Kunming: worker-turn failure at 50.
- Sydney: composer timeout/HTTP 504 at 20 and 25, worker-turn failure at 50.

The deadline fix prevents an unbounded local hang but does not make an
unavailable provider pass. Composition output was not claimed for any failed
or unavailable checkpoint.

## Regrade, judge, and UI status

After the live run, all saved traces were deterministically regraded with the
corrected sparse per-case stage anchors. Regrade is provider-free; each trace
preserves the prior grade in `grade_history`, and the final summary/manifest
preserve usage receipts. One Chengdu stage-contract grade changed from fail to
pass and Harbour's earlier composer error was normalized to unavailable. The
full live cases were not replayed.

The semantic judge is **unavailable**: no judge endpoint is configured and the
calibration manifest is `requires-human-review`/not approved. There is no
semantic pass claim. A read-only CUA inspection observed an existing Memoir
interview page with place-journey, photo-reference, and timeline controls, but
no user/private biography was mutated. The synthetic browser mutation journey
was not run against a serving app; that limitation is recorded rather than
treated as a UI pass.

## Deliverables and evidence

- Design: [memoir-five-case-evaluation-design.md](memoir-five-case-evaluation-design.md)
- Executable runner: [run_memoir_five_case_evaluation.py](../scripts/run_memoir_five_case_evaluation.py)
- Deterministic evaluator: [memoir_five_case_evaluator.py](../scripts/memoir_five_case_evaluator.py)
- Synthetic model-visible inputs: [memoir_five_case_inputs.json](../tests/evaluation/memoir_five_case_inputs.json)
- Expected outcomes: [memoir_five_case_expected.json](../tests/evaluation/memoir_five_case_expected.json)
- Hidden truth: [memoir_five_case_truth.json](../tests/evaluation/memoir_five_case_truth.json)
- Judge prompt/calibration: [memoir_five_case_judge_prompt.md](../tests/evaluation/memoir_five_case_judge_prompt.md), [memoir_five_case_judge_calibration.json](../tests/evaluation/memoir_five_case_judge_calibration.json)
- Completed run: `var/memoir-five-case-evaluation/live-five-case-shared-20261003/`

Each case directory contains 50 redacted round traces, persisted isolated
storage state, a case summary, observable events/trajectory, UI/photo/composer
receipts, timing/error data, and replay metadata. `manifest.json`,
`preflight.json`, `summary.json`, `report.md`, and the saved provider probe are
the run-level receipts.

## Validation receipts

The final focused regression suite was run after the bookkeeping/regrade fix:

```text
python3 -m pytest -q tests/test_memoir_five_case_evaluator.py tests/test_codex_worker.py tests/test_codex_agent.py -> 42 passed
node --test skills/memoir-composer/tests/composer.test.mjs skills/memoir-composer/tests/progressive_e2e.test.mjs -> 62 passed
python3 -m py_compile (runner, evaluator, provider probe, runtime, preview, worker) -> passed
```

The dataset validator returned `[]`. The final command set should be rerun
after any unrelated checkout changes because the worktree contains many
pre-existing user modifications.

## Replay commands

```bash
# Validate dataset contracts without provider calls
python3 - <<'PY'
import json
from scripts.run_memoir_five_case_evaluation import validate_dataset, load_json
print(validate_dataset(
    load_json('tests/evaluation/memoir_five_case_inputs.json'),
    load_json('tests/evaluation/memoir_five_case_expected.json'),
))
PY

# Resume saved live traces and regrade deterministically; no provider calls
python3 scripts/run_memoir_five_case_evaluation.py \
  --mode live --run-id live-five-case-shared-20261003 --resume --regrade \
  --skip-preflight --env-file .env \
  --worker-url "$MEMORY_SPARK_CODEX_WORKER_URL" \
  --worker-secret "$MEMORY_SPARK_CODEX_WORKER_SECRET" \
  --photo-worker-url "$MEMORY_SPARK_PHOTO_WORKER_URL" \
  --photo-worker-secret "$MEMORY_SPARK_PHOTO_WORKER_SECRET"

# New bounded pilot/fixture harness run (mock-only evidence)
python3 scripts/run_memoir_five_case_evaluation.py \
  --mode pilot --run-id pilot-replay --timeout 30
```

## Remaining risks and blockers

- The live provider/worker path is reachable, but composition and some final
  worker turns remain intermittently unavailable. The deadline fix contains
  the problem; it does not solve upstream latency/504s.
- Positive `memoir-author-timeline` and `memoir-family-tree` invocation rates
  are below the contract in several cases. The timeline prompt/skill was
  hardened for explicit undated events and direct smoke-tested, but the live
  model/orchestrator still misses many positive calls; this remains open.
- The host/worker Codex CLI versions differ (`0.155.1` vs `0.156.1`); align
  them before using exact latency/quality comparisons as release gates.
- No semantic judge or human-approved calibration was available, so response
  quality, evidence selection, recovery quality, and prose coherence are not
  scored beyond deterministic state/trace assertions.
- UI mutation evidence is limited to the read-only existing-page inspection;
  no synthetic browser mutation was performed against a serving local app.
- Photo results are honest public metadata only. Partial/no-match/unavailable
  results and unknown rights must not be promoted to source-photo or license
  claims.
