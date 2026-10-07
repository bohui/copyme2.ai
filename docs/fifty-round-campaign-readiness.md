# Single fifty-input campaign: offline preparation

This is one selected checked-in case, with all 50 original inputs and ten expected
private-draft checkpoints at 5, 10, …, 50. It is not an automatic five-case,
250-round workload. The user's fifty-round goal remains open: this slice creates
plans and checks claimed receipt shape, and does not implement execution.

## Explicit boundaries

`scripts/single_fifty_campaign.py --execute` always returns blocked before
loading a budget module, prompting, allocating output, or contacting a service.
The planner imports no application/authentication modules, reads no runtime
credentials or `.env`, and leaves the existing ten-turn/two-draft launcher,
80-request cap, 900-second wall limit and 60-second send limit unchanged.

The budget is a separate unapproved proposal. Logical worker dispatches and
actual upstream sends are separate counters. Missing actual usage stays unknown;
it must not be replaced by worker calls, guarded entries or planned rounds.
Neither a proposed cap nor a complete-shaped receipt authorizes a run or proves
provider/token/cost accounting, model quality or completion.

## Plan a specific scope

Run from the intended source checkout, with evidence outside the checkout:

```sh
python -m scripts.single_fifty_campaign --plan-only \
  --case-id harbour-copper-notebook --family-mode enabled \
  --output-root /tmp/memoir-single-fifty-plans
```

The case and Family mode are mandatory. The source dataset determines the
language; the example selects English/Australia. `chengdu-tea-ledger` selects
Chinese/China. Every plan records exactly one fresh synthetic owner/project,
50 unique round roots, original-input hashes, ten distinct checkpoint IDs,
current Git commit/tree/dirty status, source and skill hashes, and the separate
budget proposal. Reusing an output run UUID cannot replace earlier evidence.

The supplied source revision is observed locally, not provided as a claim on the
command line. Planning can report a dirty tree, but cannot certify it. Source
review and a final exact-main freeze remain required before execution.

## Entitlement and coverage

The proposed fifty-input backend campaign uses an explicitly isolated synthetic
entitlement fixture. It creates no real subscription or billing change. The
normal free-account allowance remains 20 rounds and must be tested separately.
Fifty successful fixture inputs would not prove that a normal free account may
bypass that gate.

The canonical driver exercises UserStorage, runtime/private workers and, when
separately admitted on the Mac, actual PostgreSQL/Temporal. Its synthetic auth
facade does not prove browser login, project recovery, ownership enforcement,
mobile behavior, the free gate, or a user's real account history. Those checks
are separate required coverage. The known recovery/security repair must pass
before the campaign runs against any native application state.

## Preserve actual role routing

This campaign must preserve the exact latest-main role configuration. The old
canary's all-role `gpt-5.6-luna`/low override is a separate experiment and cannot
stand in for current application routing. The plan records no model overrides.
Installed interview/background aliases, resolved reasoning policy, consumer
permissions and account binding remain unverified until explicitly inspected
through an authorized native preflight. Repository defaults are not proof of
installed configuration or quota.

## Receipt-shape assessment

`assess_campaign_receipt(plan, receipt)` is a pure offline checker for the future
campaign adapter's normalized receipt. It checks the exact run/source/case scope,
ordered original-source readback, source IDs and versions, settled extraction,
50 unique completed rounds, ten saved checkpoints and reported cleanup flags.
Failure, cancellation, duplicate/missing/foreign evidence, stale extraction,
unsaved checkpoints or unknown actual requests leave the receipt incomplete.
Partial completed-round/checkpoint counts are retained. Guarded entries remain
separate from actual request counts.

Even a complete-shaped receipt returns `live_ready=false`,
`acceptance_status=not_established` and `model_quality=not_graded`. Authentic
request/observation/job/checkpoint joins, actual native ownership/cleanup,
provider usage and durable Langfuse/database/browser readback still require
independent evidence; this checker does not manufacture that evidence.

## Explicit next work

1. Review and approve a precise new campaign envelope, including actual sends,
   per-stage worker/preparation quotas, time, model/account bindings and any
   enforceable token/cost limits. Historical ten-turn permission does not apply
2. Complete the security/legacy-recovery fix and freeze the exact reviewed main
3. Add a separate isolated execution profile and generalized round/checkpoint
   linkage. Keep legacy canary behavior and limits unchanged
4. Run controlled native checks in the exclusive Mac resource window, including
   cap exhaustion, cancellation and exact owned-resource cleanup
5. Only after explicit live admission, run the one selected fifty-input campaign
   with fail-closed accounting; stop and preserve incomplete receipts at any cap
6. Grade and verify durable evidence separately. Keep issues #12/#14 open until
   their actual acceptance scope passes
