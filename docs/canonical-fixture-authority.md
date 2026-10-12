# Canonical native fixture SQL authority

The provider-free five-case fixture applies the current mixed-capable schema.
Its synthetic owners are initially unmapped, so the shared worker must verify
that state using the normal `LegacyPublication` psycopg transaction and
`lock_lifetime_legacy_worker_admission()` SQL function. A legacy-only assertion
is not valid for this schema. No production guard, classifier, rollout state or
provider behavior is replaced by this fixture repair.

## Narrow opt-in transport

The ordinary Apple PostgreSQL fixture still has TCP disabled. The canonical
launcher requires --fixture-publication-tcp (recorded in the plan and receipt);
without it execution is blocked before allocation. Its Apple smoke and full test
also require MEMOIR_TEST_PUBLICATION_TCP=1. Only those explicit opt-ins request
publication access:

- One UUID-named disposable stock `postgres:18.3` container, one CPU and 1 GiB
- One dynamically selected host port, published explicitly on `127.0.0.1`
- No host mounts, persistent credentials, custom network, firewall change,
  shared service restart or wildcard listener
- A stock-image shell waits without starting PostgreSQL. Inspection of that
  exact UUID must confirm one matching host-loopback publication and one private
  guest IPv4. Only then is the validated address passed to the stock PostgreSQL
  entrypoint as its explicit listen address
- Unexpected inspection output, a broad/mismatched binding, multiple interfaces,
  unsupported tooling or port collision stops the run. There is no broader bind,
  alternate service or configured-DSN fallback
- The launcher scrubs inherited authority and credentials first, then uses only
  the newly created fixture DSN. It never sets `MEMOIR_LEGACY_ONLY_DEPLOYMENT`
- Before making that DSN available to a worker, a read-only psycopg connection
  through the selected endpoint must match the system identifier read through
  the fixture's original SQL transport. This check has a three-second total
  timeout and records only success, never details from a mismatched database
- Deadline/cancellation closes the exact UUID. Receipts preserve the selected
  endpoint before allocation and separately observe its closure after verified
  UUID removal. An uncertain/reused endpoint never authorizes stopping another
  process

An explicit guest-interface listener is reachable from the host and potentially
other containers on the same Apple network, even though host publication is
loopback-only. Execution therefore requires the approved temporary native network
and resource window; source review and passing stub tests are not execution
permission. Only synthetic fixture data is present.

Apple documents the explicit host-IP form and forwarding target in its
[networking guide](https://github.com/apple/container/blob/main/docs/networking.md#forward-traffic-from-localhost-to-your-container).
Its [parser](https://github.com/apple/container/blob/main/Sources/Services/ContainerAPIService/Client/Parser.swift)
defaults an omitted host address to a broad binding, which this fixture never
uses. The installed Mac release must be checked rather than inferred from
current online documentation.

## Mac prerequisites and ordered verification

Before allocating anything:

1. Obtain the explicit temporary guest-network/native verification approval and
   exclusive heavy-test window. Memory pressure must be normal. Do not change OS
   network permissions, firewall settings or a shared Container service.
2. Use the clean, independently reviewed task revision and an existing verified
   Python environment containing the test dependencies plus the `lifetime-memory`
   extra (`psycopg[binary]`). Record `git rev-parse HEAD`, interpreter path,
   `container --version` and `container run --help`.
3. Confirm that installed help supports `--publish` with an explicit host IP.
   If it does not, stop. The fixture independently verifies the exact mapping
   before permitting PostgreSQL to listen.
4. The full run also requires the existing Temporal SDK/local dev-server support.
   No live provider, model account, API key, judge, photo, geocoding or Langfuse
   service is required or authorized by these commands.

Substitute the verified existing interpreter path and a fresh evidence directory.
First run the small smoke only:

```sh
PYTHON=/absolute/path/to/existing/python
EVIDENCE=/tmp/memoir-authority-UNIQUE_RUN_ID
MEMOIR_TEST_POSTGRES_BACKEND=apple-container MEMOIR_TEST_PUBLICATION_TCP=1 "$PYTHON" scripts/run_isolated_check.py \
  --name canonical-authority-smoke --output-dir "$EVIDENCE" --timeout 240 -- \
  "$PYTHON" -m pytest -q tests/test_canonical_fixture_authority.py \
  --junitxml="$EVIDENCE/smoke.junit.xml"
```

This smoke has a 180-second database budget and no Temporal server. All five tests
must pass with zero skips: one real synthetic worker turn; mapped-owner rejection;
missing-authority rejection; actual provider pipe write/drain blocking concurrent
adoption; and cancellation releasing that same transaction. Subsequent admission
must fail after adoption. Teardown requires exact UUID disappearance and closure
of the selected host endpoint. Provider request/token spend is zero.

Only after that smoke passes on the same reviewed revision, run the existing
full native launcher test in the same authorized resource window:

```sh
MEMOIR_TEST_POSTGRES_BACKEND=apple-container MEMOIR_TEST_PUBLICATION_TCP=1 "$PYTHON" scripts/run_isolated_check.py \
  --name canonical-five-case-native --output-dir "$EVIDENCE" --timeout 1620 -- \
  "$PYTHON" -m pytest -q tests/test_canonical_native_launcher.py \
  --basetemp="$EVIDENCE/pytest-native" --junitxml="$EVIDENCE/native.junit.xml"
```

The original full test retains all five owners/projects, all 250 original turns
and 50 checkpoints. Its command caps fixture worker contacts at 2,000 and runtime
at 1,500 seconds; the enclosing subprocess has a 1,560-second timeout. It uses one
PostgreSQL container and one loopback Temporal dev process, with task-local SQLite
state and no Temporal UI. Receipts must report zero actual provider requests and
tokens, `mock_only`, completed cases, and verified native cleanup including the
publication endpoint. This is shared-worker fixture compatibility evidence, not
live model quality or lifetime-memory rollout/activation approval.
