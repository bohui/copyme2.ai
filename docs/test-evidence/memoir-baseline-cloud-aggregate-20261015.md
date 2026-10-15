# PR69: complete current cloud aggregate and historical comparison

Actual execution head: `b4e184c8ad2568b6c671b0f6ea22b0ae404b8afb`.
Last source/test change: `51ca7fe5629f74f6a657a7a2e611d86dabf91bf8`. The b4 child changes
only evidence. All current checks ran with these source/test files fixed;
the worktree was clean before and after the known temporary dependency link.
This delivery adds only evidence. **Complete acceptance remains false.**

## Complete Python result

The complete applicable cloud collection records **6,320 records: 5,478 passed,
572 failed, 21 errors and 249 skipped**, with **three warnings**, in
**1233.40 seconds** wall time (JUnit
1229.533 seconds). No -k, deselection, fail-fast or new
skip/xfail is used. All 593 failures/errors and all 249 skip identities/reasons
remain recorded. Classification never converts a failed assertion into a pass.

The exact command uses two file-scoped workers, the historical sixty-second
case budget, installed local PostgreSQL/Temporal tooling and an owned offline
runner:

```text
python -m pytest -q -n2 --dist=loadfile --timeout=60 --timeout-method=signal --tb=short
```

The machine has a four-CPU quota and 16 GiB limit. Application/provider/service
authority is cleared by the isolated runner; only local tooling prerequisites
are added. Databases are fresh task-owned native Unix-socket clusters, and
workers/auth/API boundaries use synthetic fixtures. No live provider or user
data is enabled. The only .env files in the worktree are example templates.

## Per-case comparison with historical b1

The b1 raw XML hash was verified against its existing ledger before comparison.
All **6,282 historical identities** are present in the current run. There are
**38 added identities, all passed**, **zero removed identities**, and **no newly
failing identities**. Every skipped identity and reason is identical between
runs. The comparison is to the earlier PR69 checkpoint, not a fresh main run;
matching IDs do not prove an assertion acceptable or preexisting on main.

| Outcome | Historical b1e54e8 | Current b4e184c |
| --- | ---: | ---: |
| Passed | 5,438 | 5,478 |
| Failed | 574 | 572 |
| Errors | 21 | 21 |
| Skipped | 249 | 249 |
| Records | 6,282 | 6,320 |

Two historical aggregate timeouts now pass within the same sixty-second budget:

- `tests/test_lifetime_draft_capacity.py::test_database_ten_thousand_sources_rounds_complete_bounded_snapshot`: **49.519 s**.
- `tests/test_lifetime_draft_coalescing.py::test_database_ten_thousand_repeated_receipts_transmit_zero_old_source_bytes`: **59.695 s**.

These are current observed outcomes, not relabelled historical passes or a
performance guarantee. No API or migration source changed since b1; subsequent
executable changes are controlled tooling, shared fixtures and lifecycle tests.
Failure classification uses current messages/trace files and test-source checks
as well as identities. One generated-row message was manually compared: both
versions fail the exact unchanged photo-policy assertion at
`tests/test_workspace_memory_actions.py:489`, observing an empty request row
instead of the prior row. UUID/digest/timestamp differences account for the
literal message change; the consequential policy remains unresolved.

| Current failure/error disposition | Records |
| --- | ---: |
| Stale fixture or retired-contract assertion | 569 |
| Identified tooling/fixture compatibility | 10 |
| Aggregate case budget | 4 |
| Exited PID-1 zombie versus required process absence | 1 |
| Unresolved functional/authority contract | 9 |

The original proposal-overlap and zombie-absence assertions remain unchanged and
failed in this complete run. Current `/proc` evidence identifies the recorded
descendant as an exited `Z` process owned by PID 1, not a live process; reaping
is not claimed. Pending-proposal inheritance versus waiting for decisions,
photo-policy revalidation/retirement and the other recorded consequential
contracts remain open. No SQL, cursor, publication/review/identity guard or
product policy is changed.

## Other current cloud checks

| Check at the same current head | Result |
| --- | --- |
| Seven separately budgeted large correctness cases, 600 s each | **7 passed**, 593.84 s wall |
| JavaScript suites | **501 passed**, zero failed/skipped |
| Mobile domain/client tests | **87 passed** |
| Mobile UI and integration Jest | **66 + 21 passed** |
| Mobile typecheck, lint, OpenAPI and native configuration introspection | Passed |
| Web webpack build and separate owned-origin standalone build | Both passed |
| Mobile all-target JS/assets export | Passed with Expo offline/telemetry-disabled prerequisites |
| Controlled standalone Chromium/fixture selection | **36 passed, four failed** |
| AT-001 through AT-055 | **55 passed** |
| Localization | **647 messages**, both locales passed |
| Normative route audit | **63 required / 125 application**, passed |
| All three changed first-party JS/MJS files lint | Passed; no rule disabled |
| All tracked Python syntax | **548 files parsed**, zero syntax errors |

The four sixty-second aggregate timeouts stay failed even though all seven
larger-budget cases pass separately. Supplemental specification/browser fixture
checks overlap the full collection; their counts are not added to the Python
aggregate. Four actual Chromium stage journeys pass under controlled readiness/
auth data; this is not PR68 readiness SQL, real image or full UI acceptance.
The four recovery fixture failures still reject the canonical identity resolver
before the original UI/ownership assertions; all are preserved with full traces
and are also present in the Python aggregate.

The first mobile-export attempt failed with exit 7 when Expo telemetry tried to
initialize an unavailable `/home/agent/.expo` path. Its complete failed log and
receipt remain recorded. The separate rerun sets `EXPO_OFFLINE=1` and
`EXPO_NO_TELEMETRY=1` and passes without changing source, HOME or access policy.
The export bundles JS/assets for configured targets; it is not a native
binary/device test.

The standalone browser run uses only two task-owned loopback origins. Public
asset hosts are disabled, unexpected backend calls receive synthetic 503
responses rather than catchall success, and the frontend is reaped/backend
closed afterwards. Runner receipts reconcile only their registered roots and
sessions; they are not a global PID-absence proof for every raw native fixture.
No global process sweep or protected-resource action occurs.

## Skips and unrun checks

All 249 original skips remain: **214 frontend/locale/historical-browser gates**,
**12 live-provider gates**, **10 complete-round gates**, **four artifact gates**,
**six missing Mocker checks**, **two missing Supabase CLI splitter checks** and
**one PostgreSQL TCP opt-in**. The ledger lists each exact identity and reason.
The selected standalone checks do not turn these aggregate skips into passes.

Live provider/judge and semantic/production-latency acceptance, real Auth,
full opt-in UI/artifact/complete-round and 250-round acceptance, native
device/binary or production execution remain unrun. No merge, deployment,
production migration, access/security-policy or operator action is performed.
PR68 polling/attribution/migration ownership remains separate.

## Parent-verified external results, not this agent's execution

The following was supplied as parent-verified evidence. Raw per-case artifacts
were not supplied in this implementation task, and these counts are not merged
with the own cloud aggregate:

- Cloud task `01a1404f-c3cb-760e-aa04-bd89f35b50d0` reviewed exact source
  `51ca7fe`: **98 affected passes and two retained failures**. It separately
  reports **17 ownership probes**, **three exact race reproductions** and
  **one real-clock budget check** passed. Subscope overlap is unspecified and
  counts are not summed.
- Native Mac task `01a140fb-2615-7041-aea3-ea54644fb016` verified exact `b4e184c`:
  **23 passed, 17 explicit Linux-only skips, zero failures**. Real Apple
  `ps`/`os.getsid` and generic timeout cleanup passed; **75 recorded task PIDs**
  and **15 temporary roots** were absent and protected resources preserved.
  Environment: **macOS 26.3.1(a), Python 3.12.11, pytest 8.4.2**. The installed
  pytest is below the repository's declared **>=9.1.1,<10** range, so this is
  not dependency-conformant full acceptance. **Mac PostgreSQL supervisor and
  emergency cleanup remain unverified.** No Mac execution is claimed by this
  implementation agent.

Source review and generic Mac checks have therefore advanced beyond the earlier
unrun status, but neither establishes acceptance of the remaining aggregate
failures or omitted platform/product/live-service gates. Independent review of
this newly completed aggregate evidence remains outstanding.

## Durable evidence

The [readable ledger](memoir-baseline-cloud-aggregate-20261015.json) indexes all
current failures/errors and skips, current commands/receipts, per-case identity
comparison, classifications, warnings, environment, explicit unrun gates and
separately attributed parent verifications. Very long synthetic binary/oversized
parametrizations are referenced by record index and full-ID hash in that index.
Their full identities and traces are retained unchanged in the archives:

- [Current exact JUnit XML, gzip](memoir-baseline-cloud-aggregate-20261015.junit.xml.gz):
  **6,320 records**, source/head identified as current.
- [Historical b1 exact JUnit XML, gzip](memoir-baseline-historical-b1e54e8-20261015.junit.xml.gz):
  **6,282 records**, explicitly historical; decoded hash matches its old ledger.

Both archives are lossless and deterministic; the manifest records compressed
and decoded hashes. Decode with Python's `gzip.open` and parse with
`xml.etree.ElementTree` to recover every original node ID, duration, attribute
and failure/error/skip entry. No assertion or outcome is omitted to keep the
readable index compact. Raw current XML/log and helper hashes are also recorded.
Historical reports and their counts remain unchanged.

## Transferable original supplementary files

The later [raw-evidence transfer guide](memoir-baseline-cloud-raw-artifacts-20261015.md),
[accessible-path manifest](memoir-baseline-cloud-raw-artifacts-20261015.json) and
[unchanged-file bundle](memoir-baseline-cloud-raw-artifacts-20261015.tar.gz)
make all 42 files in this ledger's original raw-hash map available through the
repository, including supplementary logs/XML/helper files unavailable to the
independent review task. Originals and packaged members match their existing
hashes byte-for-byte. No test was rerun, original reconstructed or original
ledger/hash changed. Content review found only synthetic negative-test
credential-shaped literals and no real secrets or private user data. The
reviewer's earlier 22-of-42 verification remains historical; independent
verification of the new package is pending parent-routed re-review.
