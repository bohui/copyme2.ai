# Memoir semantic-judge calibration review packet

Status: `requires-human-review`. This packet does not authorize semantic scores
as acceptance gates. The checked-in calibration manifest remains advisory-only
until a human reviewer records the reviewer identity and review timestamp in
`tests/evaluation/memoir_five_case_judge_calibration.json`.

## Review set

The examples are synthetic failure labels, not customer memoirs:

| Example | Expected failure to verify | Primary evidence |
| --- | --- | --- |
| `known-failure-unnecessary-place-photo-call` | A place/photo action was called without a resolvable place or photo request. | Ordered tool steps and the round's user request. |
| `known-failure-invented-date` | An approximate or unknown date was exported as exact. | Timeline marker, persisted state, and source wording. |
| `known-failure-unauthorised-family-write` | Family data was written while server entitlement was disabled. | Entitlement state, write step, and persisted revision. |
| `known-failure-duplicate-successful-search` | The same successful search was repeated without new evidence. | Tool arguments, item lifecycle IDs, and ordered steps. |

For each example, a reviewer should confirm that the proposed category scores
are supported by observable step IDs or final-state fields, and that the
rationale does not rely on hidden model reasoning. Reviewers should reject an
example if the expected result depends on an exact tool sequence when the case
allows an equivalent safe path.

## Sign-off procedure

1. Inspect the synthetic input, expected outcome, trajectory, and persisted
   state together.
2. Record any score or rationale correction in this packet or its linked issue.
3. Only after the examples are reviewed, set `review_status` to
   `human-reviewed`, add a real reviewer identifier, and record an ISO-8601
   `reviewed_at` value in the JSON manifest.
4. Re-run the calibration validation and the negative-suite tests. Keep the
   signed manifest in the same commit as the review receipt.

An unavailable, unconfigured, or unapproved judge must remain
`unavailable`, never pass. Deterministic failures, missing live evidence, and
judge unavailability are separate result classes; an LLM judge cannot upgrade
any of them.

## Endpoint and acceptance boundary

The configured Memoir provider may serve an optional judge for local
development, but that judge is advisory and is reported separately from the
deterministic acceptance result. A same-provider judge is not an independent
release gate: provider/model or prompt failures can be correlated with the
trajectory under review. If semantic scores ever become a gate, use a
separately operated endpoint/model and retain this human-reviewed calibration
set; until then, deterministic application-state and trace assertions remain
the acceptance source of truth.

Every future judge receipt should retain the run, case, round, provider/model,
prompt/rubric version, trajectory digest, request status, and reported usage or
cost when the endpoint supplies it. Do not export raw storyteller prose,
private instructions, or typed reasoning items/content. A judge receipt may be
`scored`, `unavailable`, `blocked`, or `not_configured`; those statuses must
not be collapsed into a numeric pass.
