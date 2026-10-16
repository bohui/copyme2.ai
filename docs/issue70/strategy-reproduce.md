# Reproducing the three-strategy extension

Use the source/test commit recorded in strategy-verification.json. All test data
is synthetic and the PostgreSQL fixtures own disposable clusters. Do not point
these tests at production. Install the repository Python/test dependencies plus
pytest-xdist, pytest-timeout, native PostgreSQL tools (initdb/pg_ctl/psql) and,
for the browser checks, Playwright with Chromium. The preserved original evidence
and README describe the existing repository setup; no provider is needed.

The evidence runner strips inherited application/provider credentials. In the
implementation environment the exact paths were:

```bash
export ISSUE70_TEST_PATH=/workspace/copyme2.ai/.venv/bin:/workspace/.tools/postgresql/usr/lib/postgresql/17/bin:/workspace/.tools/temporal:$PATH
export ISSUE70_TEST_PYTHONPATH=/tmp/issue70-testdeps
export ISSUE70_TEST_LD_LIBRARY_PATH=/workspace/.tools/postgresql/usr/lib/x86_64-linux-gnu
export MEMOIR_TEST_TEMPORAL_CLI=/workspace/.tools/temporal/temporal
python docs/issue70/strategy-reproduce.py
```

Replace those dependency paths with equivalent installed tools on another
machine. The actual run used the identical sanitization in the archived
implementation-environment-runner.py. Optional Temporal cases use the installed
local official CLI, rather than a network download. With no arguments the
reproduction runner executes the 107 task cases. Full frozen aggregate command:

```bash
python docs/issue70/strategy-reproduce.py python -m pytest -q -n2 --dist=loadfile --timeout=60 --timeout-method=signal --tb=short --junitxml=/tmp/issue70-strategy-aggregate.xml
```

The combined final strategy/review/policy/quota/PostgREST command and
source hashes are recorded in the manifest (161 passes). The broader development regression command is recorded in the manifest and
archive. It completed with 690 passes and seven failures, all seven also failed
in the earlier preserved aggregate. It ran while implementation was finishing;
use the frozen aggregate for immutable source provenance. Do not add counts from
overlapping runs or turn earlier failures into passes.

JavaScript:

```bash
node --test tests/js/*.test.mjs skills/memoir-composer/tests/*.test.mjs tests/historical-news/*.test.mjs
```

Browser: run the source Next app from apps/web with the installed package
versions, then run these separately (the sanitized Python runner intentionally
omits browser/service environment overrides):

```bash
MEMOIR_BROWSER_URL=http://127.0.0.1:31170 MEMOIR_BROWSER_EXECUTABLE=/usr/bin/chromium python -m pytest -q tests/test_two_lane_browser.py --junitxml=/tmp/issue70-strategy-browser.xml
```

Six source-frontend cases cover three strategy profiles × English/Chinese,
independent saved reply/workspace ordering, a garden redirect and absent mode
buttons. They use synthetic API/auth fixtures; native persistence and planner
selection are exercised by the separate runtime/PostgreSQL tests. These are not
live model, live auth, live upload, TTS or deployment checks.
