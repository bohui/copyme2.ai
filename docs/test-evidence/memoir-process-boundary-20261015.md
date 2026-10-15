# PR69: bounded process-observation investigation

Inspected head `afb20289a051f929162ba5f8facab3752aa093df`; application/test source remains identical to reviewed
`9a89c4961b2448d8243c39fccdf1a66bc0b00edb`. This delivery adds evidence only.
The full aggregate is **not rerun**: **5,517 passed / 574 failed / 21 errors /
259 skipped**, including all **five aggregate budget failures**, remain unchanged.

The original failure is XML record 4771,
`tests/test_single_collector_process.py::test_completed_process_is_reaped_before_receipt_return`
at line 98. Its duration is **0.898s**; its only saved failure details are
`incomplete` versus expected `observation`. The exact original full-log section,
parsed XML fields, outer runner receipt and prior receipt search are packaged.
The original child was launched in a separate session with stdout/stderr discarded.
Neither its child receipt nor its owned PID/birth/session identity survives in
the preserved evidence or task-owned pytest paths. Outer pytest group 1094789
does not identify that child. **The original cause and that child's cleanup remain
unestablished.** No original or unverified PID is guessed or signalled, and no lost receipt is reconstructed.

## Bounded diagnostic

New runs use the existing committed `CHILD` fixture, original **2s execution /
0.4s cleanup / 0.1s stop-grace** budgets, and the exact original `python -B -c`
launch shape. Only explicitly labelled child variants add a controlled delay.
A preliminary file-launch version is also retained separately.

| Exact-launch case | Elapsed | Result | Forced stop | Reaped |
| --- | ---: | --- | --- | --- |
| unchanged_complete | 0.823s | `observation` | False | True |
| completed_receipt_with_live_exit_tail | 0.979s | `incomplete` | True | True |
| startup_exceeds_execution_budget | 2.032s | `incomplete` | False | True |

The live-exit-tail case writes a completed receipt, then keeps that same owned
process alive for 0.7s. Recorded transitions show `observation/cleanup_complete=true`
while the process is still alive. The supervisor correctly returns `incomplete`
when its shorter cleanup deadline expires, force-stops the exact owned process,
and reaps it. Thus a sub-second `incomplete` can arise from the cleanup boundary
without reaching the 2s execution limit. The startup-delay control instead reports
`execution_limit` after approximately 2s. This diagnoses the tooling boundary;
it does **not** establish which path occurred in the lost original failure.

Across both diagnostic versions, **six new children** were reaped. All **four
nonzero signals** were verified against recorded PID birth ticks, UID, PGID and
SID immediately before dispatch; each result records group absence, reaping,
and `waitpid` finding no remaining waitable child. These statements concern the
new recorded identities only, not the lost aggregate child or unrelated processes.

## Exact remaining blocker

The missing original receipt and owned-child identity prevent retrospective
verification of cause and cleanup. A new passing focused run cannot repair that
evidence gap. Classification stays **unresolved process-observation failure**;
no timing/environment/preexisting attribution is assumed. Production supervision,
test assertions, budgets and product policies are unchanged. No expensive
aggregate was repeated merely to seek a pass.

[Manifest, process identities, transitions and limits](memoir-process-boundary-20261015.json) ·
[Lossless raw evidence and exact diagnostic helper versions](memoir-process-boundary-20261015.tar.gz).
The archive has **48 regular files**, 24,646 bytes,
SHA256 `3ac457d1a571d90e9b00ee9186bda61fa60549f75a3da8bfc41c8eb3f8d5cd8f`. Every member was read back and matched
byte-for-byte/hash. The prior 150-file archive and report are unchanged. No original
child evidence was reconstructed; extracted original log bytes and parsed XML
representations are explicitly distinguished.

Only disposable synthetic processes were used; no listeners, databases, leases,
providers, real data, access changes, product-policy choices, merge to main or
deployment occurred. Human ready-for-review status remains preserved; acceptance
is incomplete.
