# Issue 14: inactive provider-budget protocol slice

This is a controlled-protocol prerequisite, not completion of [issue 14](https://github.com/bohui/copyme2.ai/issues/14).
The protocol slice has no live mode, environment-variable override, new endpoint/model/account
selection, credential lookup or judge activation. A subsequent additive
[deny-only admission slice](issue14-deny-only-admission.md) adds opted-in app hooks
and a new blocked entry point; it does not install this transport on a live route.

Original reviewed source baseline: `050a664ceadeaeacedd9ac4c38448db494fcf1a4`, tree
`69484aadec3da6c8c0fd688d360bc58bd9b2d1ce`.
Reconciled with main `3010bb4c90f6a8b5dc51af482704193a6f7a04b2`, tree
`40103f5432b315d64c77b21f9975a0a0db57340a`, after PR 35 merged. The four
issue 6 evaluator/dataset/test/report files and the frontend button change are
preserved byte-for-byte from main. The provider-budget diff remains four new files.
Subsequent reconciliation preserves main `c72f9953b012a57202e17e1cfe50da59ee49fba8`
(tree `61abc083d7c17c377aab7e59da46d5d12c335be6`), including its four disjoint
frontend/guest-transfer/test changes, without modifying those upstream files.

## Added contract

- `scripts/issue14_provider_budget.py`: one process-owned, run-wide, write-ahead
  reservation ledger. All clients/roles in a run must share the same instance.
- `scripts/issue14_provider_transport.py`: an owned HTTPX transport that validates
  the final HTTP request, reserves before its private socket transport is invoked,
  consumes the entire response, and durably settles before returning any bytes.
- `tests/test_issue14_provider_protocol.py`: real disposable loopback HTTP servers
  and synthetic identities. Server-side contact counts are independent of ledger
  counts. They are never presented as real-provider usage.

The constructor rejects live use with `live_provider_unverified`. The only factory
accepts the exact numeric-loopback route `http://127.0.0.1:<unprivileged-port>/codex/responses`.
It requires fixed synthetic authorization, account, and model values. There is no
injected callback, HTTP client, proxy, credential provider, retry strategy, or
alternate transport. HTTPX connection retries, redirects through the guard,
environment proxies, HTTP/2, and keepalive reuse are disabled. A redirect response
is an unresolved failure, so even a caller using `follow_redirects=True` cannot
follow it. Timeout is cleanup only, never evidence of a spending cap.

## Controlled protocol, not real tokenization or pricing

`synthetic-responses-byte-v1` defines one input token per byte of the complete
final UTF-8 JSON body. This includes instructions, full message history, function
definitions, function-call arguments/results, reasoning configuration, and all
JSON framing. The transport constructs a private outgoing request from the pinned
target, validated header snapshot and exact inspected bytes. It never forwards the
caller-owned request or extensions; asynchronous body callbacks cannot redirect it,
change its method/identity/role, append context or strip a cap afterward.

Only the explicitly recognized text/function payload grammar is accepted. Hidden
server context (`previous_response_id`), photos, audio, remote tools, unknown
fields, wrong models, missing/changed output caps, duplicate JSON keys and nonfinite
numbers are rejected before contact. No character-to-token heuristic is claimed
for any real model.

The fixture server independently enforces `max_output_tokens`, including reasoning.
The final response must identify the same synthetic model/account and cap. The
fixture rates are 2 XTS micros/input token and 5 XTS micros/output token. XTS is a
testing unit here, not a provider price or billing currency approval.

For a final body of B bytes and output cap O, one reservation is:

- 1 request
- B input tokens
- O total output tokens
- O reasoning tokens (all output could be reasoning)
- 2B + 5O XTS micros

Reasoning is a subset of output and is billed once. The request, input, output,
reasoning and currency totals are checked atomically before contact. Simultaneous
requests reserve the full worst case; settled reservations can release only
verified unused amounts. All limits are explicit immutable integer fixtures.
No floating-point money arithmetic is used.

## Durability and uncertainty

The ledger exclusively creates `<run UUID>.jsonl` with mode 0600, using an anchored
directory descriptor and no-follow flags. It fsyncs the creation record and parent
directory before admitting any send. Each reservation is fsynced before socket
dispatch. A successful settlement is fsynced before counters are reduced or any
response is exposed. Short writes are completed; zero writes, failed writes and
failed fsyncs fence the instance.

Each request UUID is unique within a run; each response UUID can settle once.
Tickets cannot be forged or reused through the public API. An invalid or missing
usage field, noninteger/negative/over-bound count, underreported exact byte-input
count, inconsistent total, unsupported
billing field, duplicate completion, late error, incomplete frame, disconnect,
timeout, cancellation, or uncertain journal result retains the full reservation
and stops subsequent dispatch. A failed completion is never returned as success.
Already-dispatched concurrent requests remain reserved until independently settled;
stopping a run does not prove that a provider cancelled in-flight computation.

There is deliberately no resume, journal replay/refund, or budget-reset API. Any
existing run filename, including an empty or partial journal left by a crash,
blocks a new instance. A process-kill test does this after an actual loopback
contact. Forked children cannot use the parent's ledger. A different run ID or
registry directory is a different run and cannot be used to continue an old
approval. The future coordinator must own that registry/admission policy.

Journals contain safe IDs, source revision, protocol/rate version, role, byte
length, reservations, validated usage, and fixed failure reasons. They do not
persist authorization, request/response bodies, testimony, instructions, function
arguments, raw exceptions, or private reasoning. Receipts always retain
`live_ready=false`, `actual_provider_requests=null`, and
`real_provider_token_or_cost_limits_verified=false`.

## Existing routes and held integration work

The existing provider accounting paths remain unchanged. The two application paths
noted below additionally have optional deny-only hooks, documented separately:

| Path | Finding / future gate |
| --- | --- |
| `scripts/evaluation_budget.py:BudgetedProvider.call` | Callback-only reservation. Forwarding an output limit is not proof of provider enforcement. |
| `scripts/canary_send_guard.py:CanarySendGuard` | Historical guard is request/SSE accounting; its receipt explicitly reports `token_limits_enforced=false`. Its historical limits are unchanged. |
| `scripts/canary_gateway_binding.py:GuardedHTTPSession.post` | Actual installed-gateway HTTPX seam after final headers/payload. A future reviewed integration must place the shared budget here or below it and prove no other socket paths bypass it. |
| `apps/api/codex_runtime.py` | Optional admission refusal is separate from accounting. Worker HTTP requests are not provider sends. Composer preparation/draft/review, classification and tool continuations still need native correlation and complete accounting coverage. |
| `apps/api/codex_agent.py` | Optional admission refusal is separate from accounting. Native agent/SDK traffic is outside this transport's interception; no claim of complete tool-loop accounting. |
| `apps/api/trajectory_evaluation.py:OpenAICompatibleJudge.__call__` | Direct `AsyncClient.post(.../chat/completions)` at baseline lines 1400–1401 bypasses the shared guard. It must not run under this slice. |
| `scripts/run_memoir_five_case_semantic_judge.py:judge_one` | Independent `range(retries + 1)` at baseline line 282; CLI defaults to one retry. Every eventual attempt must separately reserve at the actual-send seam. |
| `scripts/fifty_round_dispatch_budget.py`, `scripts/fifty_round_campaign_adapter.py` | Synthetic bookkeeping/worker adapter remains separate; it is not promoted to provider accounting. |

The new transport denies the `judge` and `photo` roles. This does not disable or
intercept existing application/judge programs; they remain outside the slice and
must stay inactive. Existing guards/bindings, semantic datasets/evaluators, and
existing launchers are untouched. Only the separately documented, explicitly
opted-in deny-only app hooks and new blocked launcher have been added.

## Remaining release gates

1. Verify the existing authorized provider's exact endpoint/account/wire model,
   tokenizer and server-side framing/context rules using approved configuration
   and primary evidence, without credential disclosure or paid discovery calls.
2. Prove provider-enforced output/reasoning limits on that actual route. An output
   field forwarded through a subscription gateway is insufficient if stripped or
   ignored. Fail closed if incompatible; do not switch routes/accounts/models.
3. Verify pinned billing rates, cache/reasoning/tool charges or an existing hard
   gateway monetary cap; derive numerical worst-case request/input/output/
   per-request-output/currency bounds and obtain the specific live approval.
4. Review and integrate the shared actual-send ledger across every collector,
   workspace/classification, composer, tool loop, explicit retry and judge path;
   deny all bypasses, redirects, fallback accounts, websocket and alternate APIs.
   Bound photo work separately. Preserve a durable run admission fence.
5. Establish an authorized judge endpoint/model, rubric/version, explicitly named
   human calibration reviewer/date and accepted examples. Synthetic judgments do
   not satisfy calibration or semantic release criteria.
6. Run approved prior/current/no-skill/model-provider comparisons on fixed cases
   and publish safe usage/cost receipts and outcomes. Obtain independent exact-head
   cloud review and all applicable acceptance gates before merge.

## Verification

Run the self-contained socket suite from the repository root:

```sh
python -m pytest -q tests/test_issue14_provider_protocol.py
```

It uses only synthetic data and local disposable sockets; it does not invoke a
real provider, judge, Langfuse upload, subscription, deployment or migration.
The initial test toolchain was Python 3.12, HTTPX 0.28.1, pytest 8.4.2. Final
verification also uses Python 3.12, HTTPX 0.28.1 and repository-compatible pytest
9.1.1 from an available isolated review environment.

At the source baseline, `test_audit_source_pins_match_this_reviewed_derivation` in
`tests/test_fifty_round_budget_contract.py` fails independently: the pinned
`apps/api/canonical_composer.py` digest is `569b08c45a7aeb9c84b9bd7f32627a174f577a39256d9158d7d239b1a44ca17f`,
while the exact baseline blob hashes to `be4e1afc91e223a17a47de81ab6cd09de5af825b48547268a80754a8d3b545d2`.
That held baseline pin is not silently updated in this change.
The later deny-only hook delta also changes the three application files named in
the existing derivation pins. Those pins must continue to report source drift;
they cannot be refreshed to imply provider capability or live authorization.
The subsequent [versioned source-integrity gate](issue14-versioned-source-contract.md)
preserves those exact historical pins and verifies them against immutable original
Git objects. A separate current-source audit checks the reviewed inactive payload;
the existing test requires both, while the old campaign remains blocked on drift.
