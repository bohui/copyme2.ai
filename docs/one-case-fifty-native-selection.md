# One selected original fifty-round case

The native subscription launcher accepts an explicit `--case-id` for exactly
one original case in the `subscription_fifty` profile. Omitting it preserves
the ordered five-case campaign and its existing limits. The offline
`single_fifty_campaign.py` planning facade remains separate and blocked from
execution.

For the approved harbour scope, the additional plan-only arguments are:

```text
--evaluation-profile subscription_fifty
--case-id harbour-copper-notebook
--max-client-requests 569
--max-elapsed-seconds 7200
--max-case-client-requests 569
--max-case-elapsed-seconds 7200
--collector-timeout-seconds 180
```

The launcher still requires an explicit run UUID, exact source revision,
run directory, and existing reviewed Codex/Temporal executable SHA pins.
Planning alone neither loads credentials nor creates native resources.
Execution still requires the existing explicit subscription execution flag,
committed clean fetched main, source proof, native readiness gates, and the
evaluation owner's unused live authorization. This change grants no live
authorization and records no live result.

The saved plan, owned session, immutable request-ledger selection, runner,
and final receipts must agree on the same case. The original case mapper
retains its owner/project identities, all 50 original narrator inputs, locale,
and ten checkpoints at rounds 5 through 50. Native resource facades and
worker scope contain only that case. The existing round gate rejects round
51; the ledger rejects a second case before another send.

Empty, unknown, duplicate, multiple, or malformed selections fail before
native allocation. A saved plan is rebuilt exactly before execution; editing
its selection, case list, case data, dataset, deadlines, or caps cannot resume
it. Existing exclusive journals reject reopening a used run UUID, including
with a different selection. Browser/photo work and the one-collector
observation mode are excluded from this selected full campaign.

Request and elapsed limits remain mandatory and enforced. Selected execution
cannot exceed 569 new client sends or 7200 seconds, globally or per case;
the collector deadline is explicitly 180 seconds. Other role deadlines,
model routing, concurrency, retries, product entitlement limits, and default
five-case bounds retain their existing behavior. These are client-to-gateway
counts; actual provider usage and upstream cancellation remain unverified.

Partial failure retains completed rounds, failed-round evidence, cleanup,
and request accounting. A structural fixture completion continues to report
`live_ready: false`, `e2e_passed: false`, and semantic human review required.
The one-case receipt does not establish five-case coverage or model quality.
