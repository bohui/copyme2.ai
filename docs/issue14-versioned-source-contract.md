# Issue 14: a versioned source-integrity gate

This repairs the source check without changing historical budget derivations,
receipts, gateway controls or live eligibility. It is a source-integrity check
for the inactive PR36 implementation, not a new campaign budget or proof of
provider capability.

## Two different questions

1. **Was the historical v1 derivation accurately pinned?** Yes. All 13 original
   hashes match the exact blobs at revision
   `3a9a339813ed06fb06ba18815bf32b880072314e`, tree
   `640f47d4ea8d1e8cb52f3198dfb93719cec1457e`.
2. **Does the current executable source payload match its separately reviewed
   inactive version?** The new audit checks the immutable PR36 snapshot
   `1026a1b97731f098962d045d24fefa581797ca67`, tree
   `60445c90ce5a16968719cb530e932560e45b35c3`.

The previous test compared historical hashes against every current checkout.
It already failed on main's composer change, then correctly detected changes in
the three issue14 app-hook files. Changing those old hashes would misidentify
which implementation the historical derivation described.

The migrated existing test now requires **both** historical integrity and the
separate current-source check. It is not skipped, xfailed, deleted, or made to
check history alone. Changing a monitored current file still fails that same
existing test node.

## Immutable offline proof

`tests/fixtures/issue14_source_contract_v2.json` is a data-only proof bundle:

- Exact Git commit objects bind each explicitly permitted revision to its tree.
- Exact Git tree objects prove path membership down to each relevant blob.
- The 13 historical source blobs are included as bounded compressed data, so
  shallow checkouts do not need old objects, network access or Git credentials.
- Every historical blob must match both its Git blob identity and the unchanged
  v1 SHA-256 pin. The v1 contract module itself must retain its published PR29
  blob `fd809659e5b3eb31e9593d5340f904a534efbda8`.
- Current source bytes must match both their immutable Git membership and their
  SHA-256 digest. Merely replacing an expected digest cannot certify new code.

Provenance: [historical derivation](https://github.com/bohui/copyme2.ai/commit/3a9a339813ed06fb06ba18815bf32b880072314e),
[original merged contract](https://github.com/bohui/copyme2.ai/commit/2369a24e0a6ea3aebc181868df303aec2fbcc1d2),
[independently reviewed inactive source](https://github.com/bohui/copyme2.ai/commit/1026a1b97731f098962d045d24fefa581797ca67).

## Current source scope

The 110-file current inventory is derived from the immutable reviewed Git tree,
not a caller-supplied shortened path list. It covers all Python source under
`apps/api/` and `scripts/`, plus `apps/__init__.py`, `pyproject.toml`, `compose.yml`
and the tracked `.env.example`. It never reads an actual `.env` or authentication
file. Missing, added, changed or linked monitored source fails closed.

The newly added `scripts/issue14_source_contract.py` is the one explicit
audit-tool exception to that older Python inventory. Its own implementation,
tests, proof fixture and documentation require independent review in this new
change; the earlier snapshot cannot cryptographically attest to later tooling.
No wildcard exemption or self-reported source identity is accepted. This does
not assert that every frontend file, installed dependency, runtime configuration
or external/native provider binary is covered.

The verifier uses the standard library, bounded decompression and anchored
no-follow file reads. It does not import application modules, execute source,
launch subprocesses, fetch Git objects, dispatch network requests, or mutate the
checkout. Corrupt or relabelled proof objects and unsupported proof schemas fail.

## What remains unchanged and blocked

`scripts/fifty_round_budget_contract.py` and its v1 schema, revision, tree,
13 pins, numerical proposal, routing statements and authorization flags remain
byte-for-byte unchanged. Existing campaign planners, launchers, gateways,
judges, fixtures and historical receipts are not rewritten.

The old campaign planner still reports `budget_call_graph_source_drift` for:

- `apps/api/canonical_composer.py` (pre-existing main change)
- `apps/api/codex_runtime.py`
- `apps/api/codex_worker_service.py`
- `apps/api/codex_agent.py`

The v2 source-audit result explicitly retains this historical mismatch. It always
reports `live_execution_authorized=false`, `provider_capability_verified=false`
and `hard_token_or_monetary_limit_enforced=false`. Passing the new source gate
does not upgrade an old receipt or allow a current live campaign. Actual route,
account, model, tokenizer/output/reasoning semantics, prices, numerical approval,
native interception and judge calibration remain separate unmet requirements.

## Validation and future changes

```sh
python -m pytest -q tests/test_fifty_round_budget_contract.py tests/test_issue14_source_contract.py
```

Negative tests cover current code/dependency mutations, shortened inventories,
missing/extra files, symlinks, invented roots/hashes, corrupt or missing Git
objects, relabelled versions, authorization fields and malformed compressed data.
They also verify read-only repeatability and that the legacy planner stays blocked.

A later relevant source change needs a new explicit reviewed snapshot/version
and proof bundle, with tests and independent review. Preserve the historical v1
identity and any prior proof bundles/receipts. Never regenerate pins automatically
from an arbitrary working tree or treat a new source audit as live authorization.
