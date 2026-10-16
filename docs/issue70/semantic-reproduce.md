# Reproducing the semantic-checkpoint extension

Use source `2c06eaad48301a397fb3d802bd74283a491b3e43` (or the final evidence-only
head with identical application, migration and test bytes). The prior
strategy-reproduce.md describes dependency setup and browser limitations. All DB
fixtures create disposable native PostgreSQL clusters. No real provider,
production database, account credentials or paid campaign is used.

The sanitized runner is shared with the earlier evidence. Set the equivalent
local dependency paths; these are the exact implementation-environment paths:

```bash
export ISSUE70_TEST_PATH=/workspace/copyme2.ai/.venv/bin:/workspace/.tools/postgresql/usr/lib/postgresql/17/bin:/workspace/.tools/temporal:$PATH
export ISSUE70_TEST_PYTHONPATH=/tmp/issue70-testdeps
export ISSUE70_TEST_LD_LIBRARY_PATH=/workspace/.tools/postgresql/usr/lib/x86_64-linux-gnu
export MEMOIR_TEST_TEMPORAL_CLI=/workspace/.tools/temporal/temporal
python docs/issue70/strategy-reproduce.py python -m pytest -q tests/test_lifetime_semantic_checkpoint.py tests/test_issue70_review_repairs.py
```

This focused command includes the 19 semantic cases and five earlier completeness
repairs. The earlier immutable 370-case command is recorded verbatim in semantic-verification.json;
it adds the strategy, canonical context/runtime/engine/service/transport/checkpoint/
commit, atomic policy, PostgREST and quota regressions. Full frozen aggregate:

```bash
python docs/issue70/strategy-reproduce.py python -m pytest -q -n2 --dist=loadfile --timeout=60 --timeout-method=signal --tb=short --junitxml=/tmp/issue70-semantic-final-aggregate.xml
```

The isolated existing capacity protocol uses the same 60-second test timeout:

```bash
python docs/issue70/strategy-reproduce.py python -m pytest -q tests/test_lifetime_composer_capacity.py::test_pg_composer_10000_dispositions_have_bounded_complete_root --timeout=60 --timeout-method=signal --tb=short --junitxml=/tmp/issue70-semantic-frozen-capacity.xml
```

JavaScript:

```bash
python docs/issue70/strategy-reproduce.py node --test tests/js/*.test.mjs skills/memoir-composer/tests/*.test.mjs tests/historical-news/*.test.mjs
```

semantic-raw-evidence.tar.gz contains every local semantic development red/green
log and JUnit file plus the current-source targeted/capacity/aggregate results.
The manifest identifies which runs are frozen and which are development evidence.
The first red suite and fixture/transport mistakes are retained but are not
claimed as meaningful TDD. The stronger seven-case red suite and frontier,
pinning, window-bound and current-policy counterexamples are the semantic TDD
proofs. Exact aggregate case IDs and comparator records are in
semantic-case-ledger.json.gz. No failures/errors/skips are reclassified as passes;
counts from overlapping runs must not be added.

The unchanged EN/ZH frontend source-browser evidence remains in strategy-*.
It uses synthetic API/auth fixtures and is not a current real-provider/browser
quality test. No live semantic retention, quality/latency/usage/cost/audio or
provider-wide capacity campaign was authorized or executed. Those remain release
gates even if the local targeted suite passes.
