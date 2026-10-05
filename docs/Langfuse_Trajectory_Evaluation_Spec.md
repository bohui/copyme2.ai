# Langfuse trajectory evaluation for the Codex worker

## Problem Statement

The Memoir application can run a Codex turn through the private `codex-worker`,
but its current visible trace is a hand-built summary of expected phases rather
than an observed record of the agent loop. It does not preserve the ordered
actions, arguments, tool results, failures, retries, or application state
changes needed to judge a trajectory. A good spoken reply can therefore hide a
wrong skill choice, an unsupported tool action, a missed recovery, or an
incorrect persisted result.

The separate local `codex-harness` service added another execution path for
developer checks without giving Langfuse the product's real worker behavior.
The service is being removed so local evaluation can exercise the same
application and worker boundary used by the storyteller experience.

The team needs a repeatable local developer test and evaluation workflow that
can compare skill versions and model configurations, preserve enough evidence
to explain failures, and use Langfuse for traces, scores, judges, and
experiment comparisons. Evaluation must remain separate from runtime loop
control, privacy boundaries, and application authorization.

## Solution

Use the Langfuse control plane already hosted by `llm_provider`, while keeping
the Memoir-specific experiment runner and instrumentation in this repository.
The runner's task callback invokes the normal Memoir application and private
`codex-worker` path for one isolated synthetic case. Instrument that path to emit a normalized, ordered trajectory containing
the context available before each action, the selected action and arguments,
the complete result or error, subsequent application actions, and the final
state and response. Attach the trajectory to the root evaluation observation
or assemble it in the external evaluator so a judge receives the evidence it
needs; do not assume that a trace viewer's child observations are automatically
available to a managed judge.

Run deterministic evaluators for permissions, schemas, marker validation,
step/retry budgets, skill loading, and persisted state. Run calibrated LLM
judges for tool appropriateness, evidence use, recovery, unnecessary
repetition, stopping behavior, and final response quality. Send run-level and
step-level scores to Langfuse with stable score identifiers. Keep all runtime
timeouts, cancellation, authorization, maximum iterations, and tool permissions
in the application and worker.

The local Compose stack contains the API, private `codex-worker`, Temporal,
background worker, and web services. `install_skill` validates the checked-in
skill bundles, rebuilds the API and worker images where skill text is loaded,
and recreates those services so cached skill loaders reload. Repository checks
run through ordinary local or CI commands.

## User Stories

1. As a developer, I want one local evaluation command, so that I can run a skill-enabled Memoir case without starting a second agent runtime.
2. As a developer, I want the evaluator to invoke the same API and `codex-worker` boundary used by the product, so that evaluation results predict product behavior.
3. As a developer, I want every case to use an isolated synthetic storyteller and project, so that evaluation cannot read or modify customer data.
4. As a developer, I want a case to declare its user message, prior memories, profile, entitlement, language, enabled skills, and expected outcome, so that a run is reproducible.
5. As a developer, I want the runner to pin the application revision, skill manifest, model, provider configuration, and evaluator version, so that two experiment runs can be compared fairly.
6. As a skill author, I want to test a skill when it is explicitly enabled, so that instruction-following failures are separated from discovery failures.
7. As a skill author, I want to test ordinary requests with the normal skill catalogue, so that inappropriate activation and missed activation are visible.
8. As a skill author, I want the run to record which skill version and reference materials were loaded, so that loading failures are distinguishable from adherence failures.
9. As a developer, I want the trajectory to show the context available immediately before each action, so that a judge does not penalize or excuse a decision using information the agent did not have.
10. As a developer, I want each model action to include its selected tool, normalized arguments, and action category, so that tool choice can be checked independently of the final prose.
11. As a developer, I want each tool result, error, timeout, and retry recorded in order, so that recovery and repetition can be evaluated from evidence.
12. As a developer, I want application-side validation, entitlement checks, marker parsing, persistence, task publication, and artifact commits recorded as trajectory steps, so that a successful reply cannot conceal an invalid state change.
13. As a privacy reviewer, I want private reasoning excluded from the trajectory, so that evaluation records contain observable inputs and actions without claiming access to chain-of-thought.
14. As a developer, I want the final visible response, stop reason, terminal status, and resulting application state captured, so that answer quality and task success can be scored separately.
15. As a developer, I want deterministic checks for tool permissions, schema validity, marker grounding, entitlement gates, source ownership, retry limits, and saved-state revisions, so that objective failures do not depend on judge variability.
16. As a reviewer, I want a trajectory-quality score for the whole run and targeted scores for failed steps, so that a run can be triaged without treating every defect as an answer-quality problem.
17. As a reviewer, I want separate scores for skill selection, skill adherence, execution quality, state correctness, and final response quality, so that the team can fix the right layer.
18. As a reviewer, I want judges to assess tool appropriateness, evidence use, recovery, unnecessary repetition, and stopping behavior, so that trajectory quality is broader than exact-sequence matching.
19. As a developer, I want equivalent valid paths to receive credit, so that evaluation does not require one arbitrary tool sequence when the resulting behavior is safe and grounded.
20. As a developer, I want the evaluator to distinguish a sensible retry after a transient error from repeating a successful action, so that recovery is measured accurately.
21. As a developer, I want to compare a new skill revision with a previous revision and a no-skill baseline on the same cases, so that improvements and regressions are visible.
22. As a developer, I want to compare model and provider configurations while keeping the case and rubric fixed, so that quality and latency trade-offs are attributable.
23. As a developer, I want local experiment results to remain useful when managed judging is asynchronous, so that runtime behavior does not depend on a Langfuse worker being available during the turn.
24. As an operator, I want runtime timeouts, cancellation, maximum iterations, and permissions enforced before evaluation, so that a judge cannot become a loop-prevention mechanism.
25. As a privacy reviewer, I want sensitive storyteller content redacted or minimized before it is sent to Langfuse, so that evaluation retention follows the application's data policy.
26. As a developer, I want each Langfuse score write to be idempotent, so that retries do not create duplicate or conflicting evaluation results.
27. As a reviewer, I want a trace or run identifier linked to the local case result, so that a failure can be inspected in Langfuse without searching by free text.
28. As a developer, I want deterministic artifact and persisted-state checks to inspect the real output, so that a plausible final answer cannot substitute for a missing file or incorrect workspace revision.
29. As a skill author, I want explicit cases for current-day versus historical place-photo searches, uncertain dates, unrelated requests, and ambiguous place cues, so that the place-photo and place-journey contracts remain grounded.
30. As a Family feature developer, I want cases for paid, unpaid, pending, and revoked entitlements, so that premium skill activation and persisted Family context remain server-controlled.
31. As a collection developer, I want cases for collection review, organiser handoff, source ownership, and deterministic task results, so that the background workflow is evaluated beyond the organiser's proposal.
32. As a developer, I want a failed case to preserve enough local evidence to reproduce it without uploading unnecessary content, so that debugging remains practical and privacy-aware.
33. As a maintainer, I want repository checks to run directly on the host or in ordinary CI, so that removing the dedicated harness does not remove regression coverage.
34. As a maintainer, I want `install_skill` to refresh every runtime that caches skill text, so that an evaluation never silently uses an older skill bundle.
35. As a reviewer, I want the accepted rubric and dataset version recorded with every run, so that score changes caused by rubric edits are not mistaken for agent improvements.

## Implementation Decisions

- Use one high-level seam: a local evaluation task callback around the existing
  application/worker turn boundary. The callback receives a case and returns a
  normalized run result; Langfuse experiment orchestration, deterministic
  evaluators, and LLM judges consume that result rather than reimplementing the
  agent loop.
- Split ownership at the existing consumer boundary. `llm_provider` owns the
  self-hosted Langfuse stack, LiteLLM `langfuse_otel` generation export,
  consumer-project routing, evaluator-model connection, and generic Langfuse
  control-plane activation. Memoir owns the task callback, Codex/application
  trajectory instrumentation, skill manifests, synthetic cases, semantic
  deterministic gates, redaction policy, and Memoir-specific scores. The
  provider must not learn Memoir's skills, markers, Supabase schema, or Family
  entitlement rules.
- Reuse the provider's managed-evaluation pattern: the consumer contributes the
  cleared dataset projection, application task, deterministic product gates,
  and payload-minimized evidence; the provider supplies the Langfuse project,
  hosted evaluator connection, and storage/control-plane lifecycle. Keep the
  experiment runner invocation in the consumer repository so it can reach the
  real `codex-worker` and inspect application state.
- Keep the local runner separate from the web request lifecycle. It creates a
  synthetic authenticated identity and project, invokes the same worker
  contract, waits for the complete turn and any required deterministic task
  result, then cleans up or isolates the fixture.
- Version the case input and rubric independently. A case records the user
  message, relevant private context, language, entitlement state, enabled or
  available skills, expected state assertions, and allowed outcome variants.
  The runner records the case version, application revision, model/provider,
  skill manifest hash, and evaluator version as run metadata.
- Normalize observed events into an ordered trajectory. Each step contains a
  stable step identifier, phase, pre-action context, action kind, tool name and
  arguments when applicable, result or error, timing, and the observation
  identifier. External worker steps retain their original step ID, trace/span
  IDs, parent observation, and normalized arguments when the API assembles the
  application trajectory. The sequence also records application validation,
  persistence, publication, artifact, and terminal events. Results and errors
  are retained; tool names alone are insufficient for recovery evaluation.
- Capture events at the Codex protocol and application boundaries. The worker
  records observable model/tool lifecycle events, while the application records
  authorization, marker validation, state commits, and task outcomes. The
  normalizer combines them by turn and sequence rather than relying on the
  generated UI trace.
- Attach a compact, redacted trajectory and final outcome to the root Langfuse
  observation or build the judge input in an external evaluator. Child and
  sibling observations remain useful for navigation and step-level scoring, but
  are not assumed to be automatically supplied to a managed judge.
- Use Langfuse SDK experiments for local and CI runs. Use Langfuse traces and
  observations for run evidence, experiment comparisons for dataset-level
  analysis, and scores for run-level and step-level results. Give each score a
  stable idempotency key derived from the run, evaluator version, and target
  step. The five-case runner publishes one isolated root observation per round;
  a worker-provided observation ID is used as the step-score target, otherwise
  the publisher creates a child span under the root when supported by the SDK.
- Define deterministic evaluators for skill manifest/version, allowed tools,
  argument schemas, marker syntax and grounding, entitlement enforcement,
  source/project ownership, maximum steps and retries, stop status, artifact
  existence, and persisted revision/state assertions.
- Define LLM-judge rubrics for tool appropriateness, evidence use, recovery,
  unnecessary repetition, stopping behavior, instruction adherence, and final
  response quality. Judges must grade each decision against the pre-action
  context and allow multiple safe paths. Rubrics are versioned and calibrated
  against manually reviewed examples before being used as gates. The local
  runner records judge status and usage separately from deterministic
  acceptance evidence: an unavailable or unconfigured judge is unavailable,
  not a pass, and judge scores remain advisory.
- Keep runtime controls in the application and worker: authorization, tool
  allowlists, cancellation, timeouts, iteration/retry budgets, and safe failure
  behavior are enforced inline. Langfuse evaluation is asynchronous and never
  blocks or terminates a live storyteller turn.
- Minimize and redact Langfuse payloads. Do not record private chain-of-thought,
  credentials, exact private addresses, unnecessary raw memories, or unrelated
  customer data. Preserve full-fidelity evidence only in the local isolated
  fixture when needed for debugging and permitted by policy.
- Treat skills as repository-owned bundles. `install_skill` validates their
  packaged form, rebuilds the API and Codex worker images, and recreates those
  services so module-level skill loaders use the new bundle. It does not install
  into a separate harness or into a root Codex home that the application does
  not read.
- Replace the removed developer harness checks with direct local/CI commands
  for acceptance evidence, the Python suite, and the route audit. The
  evaluation runner is for agent behavior and trajectory quality; it is not a
  general-purpose shell execution service.

## Testing Decisions

- Test externally observable behavior at the highest available seam: a complete
  evaluation case through the normal application/worker contract. Avoid tests
  that merely assert an internal event list was assembled in one implementation
  method.
- Unit-test trajectory normalization with protocol fixtures containing tool
  calls, successful results, errors, retries, interleaved events, cancellation,
  and terminal failures. Verify ordering, redaction, and omission of private
  reasoning.
- Contract-test deterministic evaluators with valid and invalid marker payloads,
  unauthorized tools, malformed arguments, wrong-project sources, repeated
  successful calls, bounded retries, missing artifacts, and stale revisions.
- Integration-test the local runner with a fake model/provider and the real
  application/worker boundary. Assert that a case returns a final outcome,
  ordered trajectory, metadata, and state assertions without requiring a live
  Langfuse judge.
- Test Langfuse publishing with a mock client for trace/observation linkage,
  redacted payloads, run-level and step-level score targets, and idempotent score
  identifiers. Keep network-dependent experiment tests opt-in and clearly
  marked.
- Exercise skill fixtures for explicit loading and natural selection separately.
  Include the present-day place-photo default, explicit historical period,
  uncertain source date, unrelated request, place-journey grounding, and Family
  entitlement cases.
- Preserve existing runtime and application regression coverage for Codex
  connection behavior, worker isolation, marker extraction, Family gating,
  collection review, organiser handoff, task ownership, and deterministic task
  execution. Add no test that depends on the removed `codex-harness` service.
- Verify the operational change with Compose configuration validation, focused
  Makefile/skill-install tests, the Codex worker tests, and the full local
  repository checks before enabling Langfuse scores as release gates.

## Out of Scope

- Replacing Codex execution or the private `codex-worker` with Langfuse.
- Moving Memoir-specific trajectory instrumentation, skill semantics, or state
  assertions into the shared `llm_provider` gateway.
- Using Langfuse managed evaluators as inline loop prevention, authorization, or
  runtime cancellation.
- Requiring exact tool sequences when multiple paths are safe and grounded.
- Capturing or exposing private model chain-of-thought.
- Building a production human-review dashboard or a new customer-facing
  trajectory UI.
- Making Langfuse the source of truth for storyteller memories, Family context,
  task payloads, artifacts, or entitlement state.
- Automatically discovering and executing arbitrary skill folders from Langfuse.
- Adding production telemetry retention, regional deployment, or compliance
  policy beyond the redaction and minimization boundary defined here.
- Reintroducing a general-purpose developer shell service under another name.

## Further Notes

The first experiment dataset should stay small and synthetic. Start with
skill-specific regression cases and manually review enough runs to calibrate
the trajectory rubric before using aggregate scores for release decisions.
Record the distinction between skill selection, skill loading, instruction
adherence, execution quality, and task success so an improvement in one does
not conceal a regression in another.

The local implementation already has a research note describing Langfuse's SDK
experiments, observation-judge visibility, external scoring, and the need to
record tool results and application actions explicitly. The project issue should
link to this spec and carry the `ready-for-agent` triage label.
