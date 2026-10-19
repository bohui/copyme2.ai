## Problem Statement

Memoir's Langfuse project makes it difficult to tell whether every product skill
has been evaluated. The standalone live suite discovers nine skill packages and
omits the foreground interviewer, although that interviewer owns published
prompts. Historical and manually named v2 datasets overlap, while only four older
code evaluators appear on the Evaluators page. Existing judge prompts are not
connected to the skill evaluation runner or managed skill evaluators.

A passing instruction probe, correct refusal, unavailable runner, successful
model proposal, saved artifact and usable browser result currently look too
similar. The owner needs visible, reproducible coverage of all ten skills in
English and Simplified Chinese, with independent quality judgments and honest
evidence of what actually ran.

## Solution

Provide one coherent evaluation workflow with a complete product-skill inventory,
stable datasets and case identities, contract checks, independent LLM judges,
and named managed evaluators. Preserve historical experiments while using native
dataset snapshots and numeric prompt/evaluator versions for future changes.

The existing evaluation CLI is the main entry point and test seam. It supports
planning without network/model calls, scoped execution, publication preflight,
evidence-bound results and a coverage report. Every planned skill and item remains
visible when execution is unavailable or the budget prevents dispatch.

## User Stories

1. As the project owner, I want to see every product skill in one inventory, so that the foreground interviewer cannot be silently omitted.
2. As the project owner, I want one stable dataset for each skill, so that I can find its cases without interpreting issue numbers or v2 folders.
3. As an evaluator, I want historical datasets and experiment results preserved, so that comparisons remain reproducible.
4. As an evaluator, I want stable case IDs and timestamp-pinned snapshots, so that a reviewed case update does not erase its identity.
5. As a developer, I want coverage preflight to reject an unmapped runtime skill or prompt owner, so that adding a skill cannot silently reduce coverage.
6. As a developer, I want to inspect the complete plan without credentials or model calls, so that I can review coverage and cost boundaries locally.
7. As an evaluator, I want to select a skill, phase, locale or case, so that I can investigate a bounded regression.
8. As a storyteller, I want the interviewer evaluated for useful grounded questions, so that it follows my actual memories.
9. As a storyteller, I want pause, redirect, correction and pacing instructions evaluated, so that prepared questions do not override my current intent.
10. As a storyteller, I want event extraction evaluated against exact original testimony, so that uncertain or invented personal facts do not become canonical memory events.
11. As a storyteller, I want progressive composition evaluated across checkpoints, so that new evidence is incorporated without unnecessary rewriting of supported prose.
12. As a storyteller, I want chapter quality assessed independently, so that the composer's own self-review is not its only quality check.
13. As a family user, I want family proposals checked for identities and relationship direction, so that distinct people are not merged or invented.
14. As the project owner, I want unwired family execution reported explicitly, so that a good isolated proposal does not imply canonical integration.
15. As a storyteller, I want profile extraction checked against manual values and manual blanks, so that automatic extraction respects my choices.
16. As a storyteller, I want place extraction checked for multiple cities, ambiguity and corrections, so that the map reflects what I actually said.
17. As a user, I want deterministic place grouping evaluated through its actual code, so that an artificial model quiz does not stand in for map behavior.
18. As a user, I want photo discovery evaluated through the configured providers, so that unused native-search capability is not a false prerequisite.
19. As a user, I want photo place, capture period, ranking, relaxed matches, attribution and rights checked, so that reference photographs are described honestly.
20. As a user, I want public historical clues checked against inspected sources, so that plausible model prose is not treated as verified history.
21. As a storyteller, I want public research evaluated for privacy and personal-evidence separation, so that my identity is not leaked or inferred from a public event.
22. As an author, I want game proposal, review, publication and play evaluated separately, so that generation alone does not claim an approved playable artifact.
23. As an author, I want consent, edition and person-permission boundaries checked, so that evaluation fixtures never grant permission on my real account.
24. As an evaluator, I want English and Chinese cases with equivalent facts, so that quality and uncertainty are consistent across languages.
25. As an evaluator, I want named code and LLM evaluators for all ten skills, so that coverage is discoverable in Langfuse.
26. As an evaluator, I want a shared judge policy and skill-specific rubrics, so that judgments are consistent but relevant to each skill.
27. As an evaluator, I want judges to cite supplied evidence and abstain when it is missing, so that fabricated certainty cannot become a quality pass.
28. As an evaluator, I want contract, execution, positive delivery, quality and calibration reported separately, so that correct refusals do not inflate delivery rates.
29. As a developer, I want expected answers and judge rubrics withheld from the evaluated model, so that the evaluation cannot leak its gold answer.
30. As an evaluator, I want separate skill and judge budgets with failed dispatches counted, so that the client cannot silently exceed the reviewed run plan.
31. As a developer, I want managed and SDK judging to be mutually exclusive within a run, so that each case is not charged and scored twice.
32. As an evaluator, I want exact prompt, source, dataset and evaluator versions attached to results, so that I can reproduce a judgment.
33. As an evaluator, I want publication to inspect existing assets and read back writes, so that retries do not duplicate assets or overwrite conflicting work.
34. As an evaluator, I want a separate human-reviewed calibration set and holdout, so that advisory model scores are not presented as calibrated acceptance.
35. As the project owner, I want all planned items retained in incomplete reports, so that unavailable and budget-exhausted cases remain visible.
36. As a developer, I want controlled service fixtures around the existing CLI, so that regression tests cover the complete evaluation flow without spending model credits.

## Implementation Decisions

- The authoritative evaluation inventory is the union of the background skill registry and runtime skill prompt owners. It includes the interviewer and records deterministic, embedded, provider, model and unwired execution correctly.
- Extend the existing skill evaluation runner and case builders. Reuse production prompt composition, output validation, progressive composer orchestration, discovery adapters and controlled application checks.
- Define one stable dataset for each of the ten skills, plus shared workflow and judge-calibration datasets. Keep historical datasets and experiments intact.
- Begin with eight scenario families per skill in both supported locales: 80 families and 160 concrete localized task items. Each item states its action, scope, required and forbidden behavior, expected facts and required witnesses.
- Derive item identity from skill, case and locale; track changed content with hashes and dataset snapshot versions. Preflight reviewed differences before updating the same item or archiving a retired item.
- Dataset items hold tasks and fixtures rather than copied application prompts. The runner builds the production packet. Gold expectations and judge instructions are never part of the evaluated model's input.
- Each skill has a visible managed contract evaluator and managed quality evaluator. Shared implementations are reused behind the twenty named definitions.
- Code checks exact schemas, quotes, IDs, versions, authorization, receipts, counts, budgets, persisted state and browser assertions. Semantic judges assess meaning, grounding, uncertainty and useful output within the declared scope.
- Use a single shared judge policy with ten composed skill rubrics. Managed judges return categorical pass, partial, fail, unavailable or not_applicable plus concise evidence citations.
- Judge prompt content follows Git review and merged-main publication. New receipts come only from actual publication; a feature branch must not fabricate published pins or bypass receipt checks.
- Managed evaluator definitions contain compiled judge text bound to the source prompt versions and hash. A prompt publication alone does not update the evaluator definition.
- Keep contract, execution, positive delivery, quality and human calibration distinct. A negative pass does not count as positive delivery; an unavailable runner or provider stays in the denominator.
- Use real production code for deterministic skills without adding a production model call. An evaluation-only judge may assess visible semantic labels where applicable.
- Record actual response IDs, model identity and usage when supplied. Missing provider accounting remains unknown. Failed calls consume their dispatch allowance.
- Use one judge executor per run. Managed rules and the SDK fallback must not both send judge requests for the same case.
- Preserve all planned items in receipts and reports, including not-run items. Enforce bounded calls, time and evidence sizes before dispatch.
- Bind hosted contract scores to independently produced application receipts and the matching item/input/output identities. Model-provided self-reports cannot establish a pass.
- The deployed Langfuse evaluator and rule interfaces must be verified against the installed release. Rules start disabled and target only the new synthetic experiment datasets after preflight.
- Separate calibration development examples from held-out human labels. Judge scores remain advisory until review establishes accepted agreement and critical-violation behavior.
- This feature requires no application database schema change and does not wire missing product capabilities or change storyteller-facing behavior.

## Testing Decisions

- The user confirmed the existing evaluation CLI as the primary seam. Tests invoke dataset selection, adapters, contract validation, judge handling and final reporting together, replacing only external services with controlled fixtures.
- Test observable results, emitted packets, dispatch counts, evidence bindings, written receipts and reports. Avoid tests that assert internal helper names or duplicate implementation logic.
- Preserve prior art from the existing mocked provider transport tests, hosted dataset conflict/readback tests, controlled trigger runs, progressive composer tests and semantic evaluation fixtures.
- Verify complete inventory coverage, unique stable case IDs, both locales, gold exclusion, safe phase selection and zero-call planning.
- Exercise dataset updates, partial writes, readback conflicts, archived items, empty experiments and matching score identities through a controlled Langfuse boundary.
- Exercise judge completion, malformed output, missing citations, unavailable evidence, injection-bearing input, critical failures, budget exhaustion and mutually exclusive executors through a controlled model boundary.
- Verify a deterministic grouping case dispatches no skill model call and an expected refusal cannot count as positive delivery.
- Verify incomplete reports contain every selected skill and planned case, with separate contract, execution, delivery and quality results.
- Reuse actual application validators for interviewer, event, profile, relationship, place, research, composer and game artifacts. Use independent gold constraints to catch omissions and unsupported semantic claims.
- Run the repository's focused place-research command for evaluation changes involving photo, place, historical research or localization. Broader baseline failures must be reported separately rather than hidden by selected tests.
- Live runs validate actual provider and Langfuse readbacks after reviewed prompt publication. Controlled test success is not reported as live acceptance or human calibration.

## Out of Scope

- Deleting, renaming or rewriting historical datasets, experiments or scores.
- Publishing model prompt versions from a feature branch or inventing receipts.
- Implementing the unwired family-tree runner or changing production skill policies.
- Granting real author consent, permissions, entitlements or publication authority.
- Changing production rollout flags, model connections or default evaluation models without a separate requested configuration change.
- Claiming completed live model delivery, browser acceptance, human calibration or an entire fifty-round campaign from isolated or controlled checks.
- Expanding evaluation to real customer testimony or private photographs.

## Further Notes

The current nine-skill suite and historical v2 assets remain useful regression
evidence, but they are not complete coverage of the ten current prompt owners.
The current project has four published judge prompt components but no managed
LLM judges. The complete implementation must connect prompts, evaluator
definitions, dataset rules, actual execution and score readbacks explicitly.

The owner confirmed the proposed CLI test seam in this conversation. Start with
the reviewed design's inventory and evidence boundaries, and retain honest
unavailable results while adapters or published judge pins are not yet ready.
