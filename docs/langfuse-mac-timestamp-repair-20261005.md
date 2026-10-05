# Mac Langfuse timestamp repair

On 2026-10-05 the user approved the local Langfuse configuration fix and
restart, then explicitly approved temporary macOS open-file caps. The local
stack is healthy. A single synthetic root, child span and numeric API score
passed durable database and fresh API readback after the publisher exited.
There were **zero model, judge or photo calls**. This verifies bounded tracing
ingestion; it does not establish the five-case live acceptance gate.

The [sanitized evidence](test-evidence/langfuse-mac-repair-20261005.json) records
commands, failed startup attempts, corrections, IDs, checksums and actual
settings. A [task-only gateway patch](test-evidence/langfuse-mac-gateway-task-20261005.patch)
excludes the gateway checkout's pre-existing edits. Independent review of that
patch remains a cloud task. The gateway checkout is still on
`bacd5ed11dc4521c480e97cb7834c68712981883`; no gateway commit, deployment,
provider routing change or production migration was performed.

### Gateway patch provenance

The published patch's SHA-256 is
`03516fbaead13b76f39705debc8ec8d623e08b04a856b1b55c9cb6605f2aff58`.
Its baseline is the **pre-task dirty working files**, not clean gateway HEAD.
Both `compose.langfuse.yaml` and `tests/test_observability_versions.py` already
differed from `bacd5ed11` before this task. Their captured baseline hashes match
the initial inventory. The patch adds only the two read-only mounts, the test
class/import and the two new XML fragments; all other existing edits remain.

| Gateway file | Pre-task working SHA-256 | Current working SHA-256 |
| --- | --- | --- |
| `compose.langfuse.yaml` | `60277536232f70d7678211b6fd0e8ac15e338e9e6c94ded07d19a1e6ccfe6db3` | `5d1c286313b865d68919fd4813b684ad56e6b12013063f31c57bb16df9c5725a` |
| `tests/test_observability_versions.py` | `1cc0fb48698d253d7088d6dabc4d9724947903a902c06925390f3d26d891798f` | `137d10ea4c46f197ea628ccbb00edfab18d3a13a940370ce813b2d778ee3cb06` |

The JSON provenance also records both clean-HEAD file hashes, new-fragment
hashes and seven preserved unrelated-file states. `git apply --check --reverse`
passes against the current gateway files without modifying them. A round trip
in a disposable four-file copy restores both exact pre-task snapshots and
removes the two new fragments; applying forward reproduces all four current
files byte for byte. That copy was removed. No unrelated
gateway work is included or committed. Five blank patch-context lines were
normalized to omit their space markers; Git accepts that format, which also
passes the evidence commit's whitespace check.

## Applied configuration

ClickHouse remains **26.9.8.3**, with the existing cached image. Langfuse web
and worker remain **4.21.0** with their existing pinned image digests.
ClickHouse 26.8 changed bare JSON integer DateTime64 values from precision
ticks to seconds; the [official compatibility setting](https://clickhouse.com/docs/reference/data-types/datetime64)
restores the integer units emitted by this Langfuse version.

In `/Users/bohuihan/llm_provider`:

| File | Change |
| --- | --- |
| `config/langfuse-clickhouse-users/zz-langfuse-numeric-datetime.xml` | New `langfuse_numeric_datetime` profile inherits `default`, sets `input_format_read_datetime_number_as_raw_value=1`, and assigns only the existing `langfuse` user to that profile |
| `config/langfuse-clickhouse-server/zz-langfuse-local-startup.xml` | Sets `tables_loader_background_pool_size`, `tables_loader_foreground_pool_size`, `max_active_parts_loading_thread_pool_size` and `max_outdated_parts_loading_thread_pool_size` to `1` |
| `compose.langfuse.yaml` | Adds two read-only file mounts into ClickHouse's `users.d` and `config.d`; existing data/log mounts, ports and image references are retained |
| `tests/test_observability_versions.py` | Adds two configuration regressions to the existing CI suite |

The [table-loader settings](https://clickhouse.com/docs/reference/settings/server-settings/settings/tables-loader)
and [part-loader settings](https://clickhouse.com/docs/reference/settings/server-settings/settings/max)
bound startup concurrency on the development Mac. The profile affects the
shared Langfuse database user serving **memior, LLM Gateway and Trading**.
It changes future ingestion parsing, including normal queued work; no manual
backfill or historical-row rewrite was requested or performed.

Fresh authentication as the existing `langfuse` database user returned setting
`1` and correctly decoded both millisecond and microsecond probes. Container
startup logs confirmed both mounted fragments were merged; system profile and
server-setting queries confirmed their active values after recreation.

## Host limits and restart

The initial restart and two recovery attempts failed while loading internal
`system.metric_log` tables: errno 23, `Too many open files in system`.
Reducing startup concurrency alone did not resolve the host cap. ClickHouse
automatically detached an internal metric-log part during one failed startup;
no manual deletion or detach of database records was performed.

The user then approved these **temporary, machine-wide** values. They were
applied through macOS's secure administrator dialog, without entering an
administrator password into chat, arguments, logs or files:

```sh
sudo sysctl kern.maxfiles=262144 kern.maxfilesperproc=131072
```

Previous values were `122880` and `61440`. The latest recorded read at
**11:17:54 UTC** was:

```text
kern.num_files: 173135
kern.maxfiles: 262144
kern.maxfilesperproc: 131072
```

These kernel caps reset at reboot. No LaunchDaemon or other persistent host
configuration was installed. Current usage exceeds the old system cap;
**do not restore that lower cap under this workload**. A reboot resets the
caps and can bring startup exhaustion back unless capacity/workload is addressed.
No additional host change was requested or performed during reconciliation.
Per-process resource limits can still be lower;
[Apple's resource-limit implementation](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/kern/kern_resource.c)
enforces both the process limit and the kernel per-process cap.

The existing Apple Container/Mocker Makefile targets were used:

```sh
make langfuse-restart STARTUP_TIMEOUT=90 \
  PYTHON=/tmp/memoir-pr9-pr10-mac-20261004/.venv/bin/python

# Successful recovery after the explicitly approved host-cap increase:
make langfuse-up STARTUP_TIMEOUT=90 \
  PYTHON=/tmp/memoir-pr9-pr10-mac-20261004/.venv/bin/python
```

The successful recovery exited `0` in **34.45 seconds**. All six scoped
Langfuse containers are running. ClickHouse `/ping`, web
`/api/public/health?failIfDatabaseUnavailable=true` and worker `/api/health`
returned HTTP `200`. Provider gateway services were not restarted.

## Durable canary and preservation

Destination: existing local project **memior**, ID
`cmut9t75w00071z02n8bdv7it`, at `http://127.0.0.1:3001`.
Existing project-scoped tracing credentials were used privately in memory;
authentication checked the project before publication. The canary process
permitted network connections only to `127.0.0.1:3001`.

| Record | Exact ID |
| --- | --- |
| Trace | `f8316b85df420c4f0f17367985dbb22c` |
| Root agent observation | `edce02d9071ea188` |
| Child span | `f5de9464f6d47a01` |
| Numeric API score | `37a2aace-2cdb-4b14-a345-19149ba7df9c` |

Publication finished at **10:46:47.399 UTC**. Fresh readback at **10:50:40.926
UTC** found exactly two observations and one score, with correct project,
trace, child-parent and score-subject linkage. The score is
`mac.timestamp_canary=1`, a synthetic ingestion assertion rather than a model
quality grade. Both database and API timestamps are **2026-10-05**, including
creation timestamps; no new DateTime64-overflow query-log entry was found
after successful startup.

Langfuse SDK 4.16.0 gave the root a generated physical upstream parent context.
The V4 `isRootObservation=true` API filter returns exactly the root ID, and
ClickHouse `is_app_root` is true for the root and false for the child. The
canary oracle checks those explicit root markers alongside the physical
child-parent association.

Read-only reconciliation on 2026-10-05 repeated exact-ID API checks at
**11:16:26 UTC**, and database/settings/health checks at **11:17:54 UTC**.
The same two observations and one score passed again, all six services were
running, all three health endpoints returned `200`, and the actual ingestion
user still had compatibility setting `1`. These checks published no telemetry.

The old year-9999 score rows remain **3750**, with the same full logical-row
fingerprint before and after:

```text
groupBitXor(cityHash64(tuple(*))) = 10146712981589141912
```

This is a preservation invariant, not a database backup. Those historical
scores are not repaired, and missing historical traces are not recreated.
The canary remains under the existing retention policy (`retention_days` was
NULL); no retention policy, TTL or cleanup job was changed.

## Checks, corrections and rollback

Final gateway command:

```sh
make agent-ci PYTHON=/tmp/memoir-pr9-pr10-mac-20261004/.venv/bin/python
```

It exited `0`: **79 startup/observability tests, 56 offline-policy tests and
41 JavaScript tests**, total **176**, with lint, build and package verification
passing. Both new regressions failed before the corresponding configuration
was added and passed afterwards. Earlier CI invocations using inherited
`ENV_FILE`/data-root command-line overrides invalidated mocked fixture settings;
the normal invocation passed. A temporary addition to the Makefile's exact
test-command allowlist was removed by placing the new tests in the existing
observability suite. The Makefile matches its pre-task bytes.

Read-only HTTP probes initially hit ClickHouse's `readonly=1` restriction on
subsequent resource-setting parameters; they passed under `readonly=2`, which
still prohibits data writes. The canary helper's unused `requests` import was
removed before any telemetry publication. Worker `/health` was a `404`; the
correct `/api/health` is `200`. Initial SDK metadata readback emitted its
public-key identifier; saved evidence was sanitized and subsequent output
retains only the synthetic metadata whitelist. No secret key was printed.

To roll back the timestamp/loading configuration, remove only the two new
fragments and their two Compose mount entries, then use the existing local
Langfuse restart target. The `langfuse` user will inherit `default` again, with
numeric timestamp parsing at its prior default `0`. Remove only the new test
class/import if reverting the task patch. Preserve all prior gateway
edits. The source bug returns under that rollback; historical rows and the
canary are not part of configuration rollback.

The previous temporary host caps can be restored separately with
`sudo sysctl kern.maxfiles=122880 kern.maxfilesperproc=61440`, once the active
workload fits those limits, or by rebooting. Lowering the caps while this stack
uses more than the old system limit would reintroduce failures; do not treat
that as part of routine task cleanup.

Original Memoir and older Issue2/Issue6 worktree fingerprints still match the
pre-task baseline. Unrelated gateway edits also match. Five empty task-owned
mocked-data directories were removed; no shared data directories, unknown IPC,
other services or credentials were cleaned up.

The Memoir application source remains the tested `c1f5e296` source tree:
**1194 native passes, four live-only skips, zero failures/errors** from the
earlier completed validation. Browser verification of this Langfuse canary is
not established: no matching current Chrome tab was found, and the earlier
fresh browser context redirected to sign-in. Cloud review of the integration
and gateway patch, the calibrated canonical/judge harness, a hard live budget,
and the full five-by-fifty/browser evaluation remain outstanding.
