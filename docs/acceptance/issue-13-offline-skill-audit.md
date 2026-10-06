# Issue #13: offline skill and source-claim audit

Base: `291622826cdfb776e946dcd92b65d2fdaf4923ad` (2026-10-06).
Status: **partial, evaluator corrections proposed for independent review**.
This does not close [#13](https://github.com/bohui/copyme2.ai/issues/13),
[#2](https://github.com/bohui/copyme2.ai/issues/2), or
[#6](https://github.com/bohui/copyme2.ai/issues/6).

## Observed evaluator defects and corrections

The existing design says only declared required and negative scenarios
contribute to contract rates; optional behavior is not a failure.
The offline regression tests demonstrated three discrepancies:

1. Optional UI skills returned `not_run` before examining `not_applicable`;
   optional browser/composer failures also returned `unavailable`. This made a
   completed required protocol round unavailable solely because an optional
   skill had no receipt. The grader now checks applicability first.
2. Aggregate invocation/output numerators counted optional passes, while the
   denominator counted only required and negative scenarios. A three-round
   replay with two contract rounds reported 150%. Both numerators now use the
   same required/negative scope as the denominator.
3. Merging browser receipts updated individual skills but only recomputed the
   round status for failures. Successful receipts left stale `unavailable`
   rounds, and missing receipts could leave stale `pass` rounds. Initial
   grading and browser merging now share one status combiner. Unrelated state
   failures, unavailable state, and provider evidence gaps remain blocking;
   fixture execution remains `mock_only`.

`pass` in these helpers means the deterministic protocol contract only. It is
not a semantic, human-review, loaded-skill-version, or live acceptance verdict.
No extraction model, application source validator, live launcher, provider
budget, or original input/truth/expected dataset was changed.

## TDD evidence

- [Initial red output](../test-evidence/issue13/evaluator-red.log): seven
  failures and two passing guard cases on the base evaluator
- [State-gap guard red output](../test-evidence/issue13/state-gap-red.log): the
  first merge-status fix was prevented from clearing unavailable state
- Initial implementation focused check: `160 passed, 4 skipped`; the four skipped tests are the
  intentionally opt-in configured-provider interview cases
- [Focused output](../test-evidence/issue13/focused-green.log)
- Initial implementation full isolated offline suite: `1086 passed, 183 skipped, 1 warning`;
  [raw output](../test-evidence/issue13/full-offline-green.log). Browser, local
  PostgreSQL, live-provider and other explicitly gated checks remain skipped
- An earlier run with inherited proxy settings stopped 26 checks at missing
  `socksio` imports (6 failures, 20 setup errors). The documented repository
  offline runner scrubbed those settings; no dependency or runtime change was
  used to obtain the clean rerun
- Original test module and new regressions are additive; existing expectations
  and calibration fixtures were not relaxed

Replay with the repository's test dependencies installed:

```sh
python scripts/run_isolated_check.py --output-dir /tmp/issue13-checks \
  --name skill-source-acceptance --timeout 120 -- python -m pytest -q \
  tests/test_memoir_skill_acceptance.py \
  tests/test_memoir_source_claim_pilot.py \
  tests/test_memoir_five_case_evaluator.py \
  tests/test_integrated_timeline_contracts.py \
  tests/test_interview_followups.py tests/test_install_codex_skill.py \
  tests/test_codex_agent.py tests/test_trajectory_evaluation.py
```

## Eight bilingual source-claim protocol probes

`tests/test_memoir_source_claim_pilot.py` checks four synthetic patterns in
both `en-AU` and `zh-CN`, using exact original statements and explicit proposed
outputs. All eight pass offline:

- Attributed school memory: preserve the original quote, attribution, original
  source identity/version and timing basis
- Unsupported evidence: reject a foreign source ID, stale source version, or
  quote absent from the original statement
- Same-year purchase/sale with an item veto: retain the purchase, reject the
  sale and vetoed timing basis, associate legacy items with `c0`/`c1`, and strip
  private association metadata before accepted output
- Explicit null legacy claim metadata: reject both `source_claim_id: null`
  and `_source_claim_id: null`; do not fall back to title/date matching

These are validator probes, **not** eight live provider turns. They do not
show that a model selects the right skill, extracts the expected proposal,
loads references, or writes grounded final prose. The source-claim live pilot
remains open and must use the approved exact-main launcher and enforced budget.

## Acceptance disposition

| Issue #13 criterion | Evidence here | Remaining gate |
| --- | --- | --- |
| Eight bilingual source-claim inputs | Eight offline protocol probes; original attributed/timing references, cN veto/stripping, invalid/null rejection | Live extraction and original raw outcomes |
| Four configured-provider follow-ups | Existing deterministic question oracle retained; four live tests skipped | Authorized bounded provider run in both locales/current-versus-earlier context |
| Required/negative/optional invocation and output | Three evaluator defects fixed; original per-skill output grades retained | Explicit loading versus natural selection receipts, actual loaded references, grounded output quality |
| `install_skill` refresh/readback | Installer unit test and build recipe inspected | Actual loaded-version readback from both running skill-bearing runtimes; no restart performed |
| Exact-main canonical/source/date/relationship/photo/collection coverage | Existing integrated canonical and source-claim contract tests pass | G1 exact-main application run, five distinct 50-round datasets, browser state and source-language preservation receipts |
| Reviewed rubric/calibrated judging | Existing calibration remains `requires-human-review` with no reviewer | Human-reviewed calibration and semantic review; prior unsupported "peaceful old age" finding remains unresolved |
| Durable evidence and rerun | Raw offline failures and focused pass output recorded; immutable dataset hashes below | G4 durable trace/observation/score links, exact landed-head affected rerun, all live invocation/output totals |

The filesystem manifest currently hashes checked-in skill/reference files.
That is reproducibility evidence, not proof those bytes were loaded by a
running skill-bearing process. `make install_skill` rebuilds and recreates
both `api` and `codex-worker`, but its recipe alone does not supply the required
runtime readback. This audit does not claim otherwise.

## Immutable fixture hashes

| File under `tests/evaluation/` | SHA-256 |
| --- | --- |
| `memoir_five_case_inputs.json` | `e7f705bc4a96537b01cb5cde7d412972bdd929de49d339bc6b1a95bc9cb43927` |
| `memoir_five_case_truth.json` | `b85bab534e1f3ef0e9d730debc8baefa3fc3eb5cfab2731f6565de9be6f4abf9` |
| `memoir_five_case_expected.json` | `9391515876dc2f346291e9ecca653e3710a1497d6a03961291cebb8f01d1c242` |
| `memoir_five_case_oracle_corrections.json` | `81e5d0e833915235848ca981dae0c98fd0075028fc85163e9596032f8ad5f4fc` |
| `memoir_five_case_judge_calibration.json` | `8383b58ecc354f16e8b1c151a0f5758d4998a1097c510e0149251fd31f328b25` |

The new evaluator correction evidence is separate from the earlier life-stage
oracle correction. Acceptance of these changes requires independent review;
no previous raw artifact is rewritten or reclassified as a live quality pass.


## Independent review correction: receipt status provenance

Review of `be0b9ef95ef57b999f99b5a458b776733c3d1b61` reproduced six
fail-open cases: a required UI receipt explicitly marked `not_run`, `unknown`,
or `mock_only` could certify a live pass when its boolean fields were true.
Both initial evaluation and browser-receipt merging were affected.

The correction checks explicit receipt status before using those booleans for
required or negative contracts. Nonterminal/unknown/null/malformed statuses
remain unavailable; `not_run` remains not run; `mock_only` is accepted only in
fixture mode. Explicit failed receipts remain failed, with invocation and
output grading kept separate. Optional receipts remain `not_applicable`.
Legacy receipts with no status field and valid live `pass` receipts retain
compatibility. The same validation now protects composer receipts, which had
the identical fail-open condition.

- [Expanded test-first summary](../test-evidence/issue13/receipt-status-red-summary.log):
  84 failed, 37 passed on the reviewed head
- [Focused correction run](../test-evidence/issue13/receipt-status-focused-green.log):
  271 passed, 4 live-provider cases skipped
- The reviewer's six exact public-entry-point reproductions now pass
- These checks use synthetic receipts only; no live requests were made

The independent full-suite run on the earlier head is retained separately:
[1085 passed, 183 skipped, 1 warning, 1 failure](../test-evidence/issue13/independent-be0b9ef-full.log).
The failure was in the unchanged
`test_failed_postgres_startup_and_stop_cannot_report_no_allocation_or_closed`.
Its [isolated rerun passed](../test-evidence/issue13/independent-be0b9ef-lifecycle-rerun.log).
The rerun does not change that aggregate run into a pass. This is distinct
from the implementation's earlier full-suite pass; independent review and
exact-head verification of the correction remain separate gates.
