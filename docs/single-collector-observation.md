# One collector observation

This mode observes one fresh collector invocation for the original first harbour
input. It is an operational diagnostic, with no campaign, round, conversation
commit or semantic acceptance claim. The parent owns independent review, merge
and live admission. Coding and review use synthetic responses only.

Before any real observation, merge the reviewed mode into main. Run the native
launcher from a clean task-owned checkout on the `main` branch at the freshly
fetched `origin/main` revision. The launcher verifies all tracked Git blobs and
the additive V6 source binding before credentials or native execution. The same
main preflight applies to the existing campaign modes. Leave the user's public
checkout and running services untouched.

The scope is fixed: one collector dispatch, one original input, four additional
client requests, 300 seconds including native setup, an unchanged 180-second
collector timer, and one separate cleanup window of at most 60 seconds. Global
and active-case request/time gates use the existing SubscriptionRun enforcement.
Every started send remains charged; completed/unresolved counts are never reset
or refunded. Receipts retain 35 prior charges and 2 prior unresolved requests,
with cumulative totals equal to those baselines plus this observation's counts.
The maximum cumulative charge is 39. No hard upstream token/spend ceiling or
upstream cancellation guarantee is established.

The mode reuses the existing native PostgreSQL/Temporal isolation, resource
lease, artifact readiness probe, guarded subscription route, retry settings,
bilingual profiles, model `gpt-5.6-luna-pooled` and reasoning effort `max`.
It calls the production runtime's original-source acceptance and collector
preparation. The owned worker gate allows only the first collector dispatch for
the first case/round. Its terminal sentinel stops the runtime before subsequent
conversation commit or workspace work. The production collector schema, skills
and its existing bounded validation correction remain unchanged within that one
dispatch; any internal continuation still consumes the four-request gate and
original absolute deadline. Additional app-server starts remain visible in
bounded progress diagnostics. The mode adds no retry or second runtime turn.

Other roles, later rounds/cases, browser builds, photo research and the campaign
runner are excluded. A fifth send is rejected before wire contact. Headers,
body arrival, recognized SSE terminal frames without EOF, cleanup, journal
durability, actual timeout cause and sealed worker progress retain their existing
diagnostic meanings. A recognized terminal frame is never accepted as HTTP EOF
or semantic success. Source text and collector output are absent from the public
observation receipt.

Hold this observation while the user's evaluation is running. The parent must
verify that run's owner/configuration and resource availability before any later
observation, under the same exclusive native lease. An unavailable lease or
failed resource preflight does not authorize interrupting the user's run.

The receipt's `status: observation` means the bounded diagnostic attempt ended;
read its `observation.outcome`, accounting and cleanup fields. Outcomes include
`collector_completed`, `worker_timeout`, `limit_guard`, `collector_failed` and
`setup_failed`. Cancellation or incomplete cleanup yields `status: incomplete`.
Cleanup failures retain uncertainty and never authorize a replay. Independently
verify owned process/container absence and lease release before treating cleanup
as established. The parent's already approved observation is one attempt only.

The CLI keeps its existing exclusive native lease while supervising one owned
Python process. That child rechecks main, the saved plan, V6 and its parent's
held lease before native allocation. Its private stdin carries the credential;
the command line and receipt contain no credential. Cancellation is sealed as
an incomplete outcome before cleanup. A terminal receipt records accounting and
worker diagnostics before session/native teardown can block.

The supervisor never joins a cancellation-suppressing setup thread in its own
process. It sends one cooperative stop at cancellation or the execution limit.
The same single cleanup deadline applies after repeated cancellations. Five
seconds of that 60-second window are reserved to kill and reap the owned Python
process group if cooperative teardown hangs. It reads the final receipt only
after that writer exits. A forced stop is incomplete and does not prove native
container removal, independently spawned native process absence, or upstream
cancellation. Those remaining resources require the parent's owned cleanup
verification before any later run; a hard stop grants no replay authority.
Sealed ledger counters remain authoritative. An HTTP completion journal event
precedes the ledger's final deadline check and cannot prove that completion was
admitted. Recovery without a sealed receipt retains those events as diagnostics,
keeps every reservation unresolved and reports accounting bounds.

After merge, use the parent's verified main revision, fresh run UUID/output
directory, existing reviewed executable pins and existing subscription credential
source. Do not print the credential or environment. The native invocation is:

```sh
python scripts/run_issue14_subscription_evaluation.py \
  --single-collector-observation --evaluation-profile subscription_fifty \
  --run-id "$OBSERVATION_RUN_ID" --source-revision "$REVIEWED_MAIN_HEAD" \
  --run-dir "$OBSERVATION_RUN_DIR" \
  --codex-binary "$REVIEWED_CODEX_BINARY" --codex-sha256 "$REVIEWED_CODEX_SHA256" \
  --temporal-binary "$REVIEWED_TEMPORAL_BINARY" --temporal-sha256 "$REVIEWED_TEMPORAL_SHA256" \
  --max-client-requests 4 --max-case-client-requests 4 \
  --max-elapsed-seconds 300 --max-case-elapsed-seconds 300 \
  --collector-timeout-seconds 180 --execute-existing-subscription
```

Omit `--execute-existing-subscription` to inspect the pure plan. It performs no
credential discovery, service allocation or model call. A failed preflight or
observation does not authorize another attempt or the fifty-round campaign.
