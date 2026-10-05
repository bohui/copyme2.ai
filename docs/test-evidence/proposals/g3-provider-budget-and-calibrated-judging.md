## Problem

The worker boundary exposes request counts but does not prove actual model
requests, input/reasoning/output usage or billed cost. Native-tested budget
components reserve worst-case input/output and stop before excess dispatch,
including concurrent reservations; they require a verified actual-provider
adapter. No judge endpoint/calibrated human reviewer/date is established in the
checked configuration. Mock judges and variant wiring do not establish accepted
semantic scores or comparisons.

Related: Issue #2; prerequisite for paid G1/G2 runs. Keep Issue #2 open.

## Agent scope and acceptance criteria

- Inspect only authorised existing provider configuration privately. Never
  print/copy secrets, create credentials or guess a judge endpoint/model/price.
- Implement a public actual-provider accounting adapter around every model call,
  including collector, workspace/classification, composer preparation/draft/
  review, tool loops, retries and configured judges. Bound photos separately.
  A private-worker HTTP cap must never be reported as provider/token accounting.
- Measure a conservative input-token bound before dispatch using the exact
  actual protocol, tokenizer/context/tool payload/reasoning accounting rules.
  Enforce output limits at the provider itself; confirm how reasoning tokens
  and retries are bounded and charged. Reserve totals before concurrency begins.
- Reject missing/invalid/over-bound usage and hold unresolved reservations;
  stop further dispatch on cancellation, unknown usage or provider failure.
  Prove zero upstream contact when a cap is exhausted through controlled
  external-provider protocol tests and concurrency/cancellation tests.
- Verify exact billing rates or an existing gateway hard monetary cap through
  primary provider documentation/configuration. Pin all models and prices and
  derive a numerical worst-case cost. The approval must state request, input,
  output, per-request output and currency spend caps. No paid calls to discover
  a budget, and no claim that timeouts/concurrency are spending controls.
- Configure only an authorised existing judge, or obtain the missing decision
  from the parent. Record rubric/version, explicit named human calibration
  reviewer/date and accepted examples before semantic release gates.
- Separate trajectory, skill selection/adherence, execution/state and final
  response quality; preserve step/run targets, equivalent valid-path credit,
  bounded retry versus duplicate success and asynchronous unavailable results.
- Compare prior/current/no-skill and model/provider variants on the same fixed
  case/rubric versions within the approved caps. Publish safe usage/cost
  receipts and raw outcomes; cloud review any code or rubric change.

## Proposed first approval envelope

Eight bilingual source-claim inputs plus four ephemeral follow-up cases;
no judge or photo call and no composer checkpoint is planned for that pilot.
Propose at most 80 actual provider requests, 400,000 total input tokens,
80,000 total output tokens and 1,000 output tokens per request, with a verified
gateway cap of US$2 or a verified worst-case cost below US$2. These are **not
approved or currently enforceable live limits**. Confirm the exact existing
models can honor the required protocol/caps before asking for paid execution;
if not, report the incompatibility rather than silently changing models.
The full 250-round run and any judging/photo work need a separate derived
envelope after the pilot and harness review.
