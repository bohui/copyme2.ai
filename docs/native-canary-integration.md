# Native ten-round canary integration

This task integration combines the independently reviewed host/app/input checkpoint
`c9cc0710625027c4d6578ffbdb94b8bd3c7ba99d` with gateway actor/guard checkpoint
`5f7b069742b17d9b70146dd87e130dceb25818dc`. The original branch references are
preserved. It also includes main merge `6e907c64a093c0aaf76cbb9dc6380e23c16205df`,
which contains PR18/#15 telemetry replay source `9d337087cc865fa801b81da7e4c12d35b0ac277c`.
The manifest verifies that merge's ancestry in the supplied source revision and
records source integration separately from durable telemetry evidence. Old or
unverifiable revisions retain an integration blocker. This is not exact merged-main
native acceptance; actual Langfuse/database/browser readback remains unrun.

## One native entrypoint

Run from the exact independently reviewed integration checkout with its existing
Python environment. The output root must be outside the checkout. Substitute the
literal reviewed combined commit and independently verified executable paths/hash.
No command accepts a key argument.

Local admission check, with no prompt, actor, database, Temporal or model start:

```
python -m scripts.native_canary_launcher --check \
  --reviewed-head REVIEWED_COMMIT --output-root /tmp/memoir-canary-evidence
```

Controlled native application test, only in the parent's exclusive native resource
window; this starts one UUID PostgreSQL fixture and one Temporal dev process:

```
python -m scripts.native_canary_launcher --test-native \
  --reviewed-head REVIEWED_COMMIT --output-root /tmp/memoir-canary-evidence
```

This uses the real canonical storage/runtime/worker path with controlled external
provider replies. It neither reads a key nor consumes real model requests. It does
not establish real Codex retry behavior, installed actor imports or model quality.

Guarded live application run, only after combined review, native/resource gates
and the approved user handoff for an existing gateway consumer key:

```
python -m scripts.native_canary_launcher --execute \
  --reviewed-head REVIEWED_COMMIT --output-root /tmp/memoir-canary-evidence \
  --docker /VERIFIED/absolute/path/docker \
  --codex /VERIFIED/absolute/path/codex \
  --codex-sha256 VERIFIED_CODEX_SHA256
```

The default key prompt is hidden and requires a private terminal. Echo fallback
and piped input are refused. The optional `--input-mode environment` consumes only
a separately supplied `MEMOIR_CANARY_GATEWAY_API_KEY`; do not place its value in a
shell command, chat, source file, `.env`, log or receipt. Normal provider variables
are not reused. The key must already belong to the installed gateway and allow
the requested model and selected account. The runtime rejects an incompatible key
rather than broadening scope. No new key or auth-setting change is performed.

The pinned runtime interpreter `/app/.venv/bin/python` has not been verified on
the native host by this cloud task. The live launcher checks the interpreter and
all installed source hashes before prompting. A mismatch stops; it does not choose
a different runtime or export credentials to work around the block.

## Resource and lifecycle boundaries

- Every mode requires the literal clean reviewed Git head
- A macOS pressure reading must be exactly normal level 1; level 2, level 4,
  missing output or unknown state blocks execution
- A nonblocking `/tmp/memoir-native-heavy.lock` excludes other instances of this
  launcher; it is advisory and does not replace the parent's resource window
- Pressure is checked again after hidden input, immediately before actor startup,
  before PostgreSQL and Temporal, and before each live Codex worker dispatch
- Only three reviewed task Python files are copied to a fresh exclusive
  `/tmp/memoir-canary-UUID/scripts` inside the existing gateway runtime
- The task creates no container port mapping, mount, persistent credential,
  account assignment, shared service restart or model fallback
- PostgreSQL uses the existing stock `postgres:18.3` UUID Apple Container fixture,
  one CPU/1 GiB, TCP disabled and no shared mount/published port
- Temporal uses a task-local SQLite file and the canary's unique queue; only
  MemoirSkillLane is registered, with one activity attempt and one activity slot
- The application preserves full original synthetic testimony and canonical RLS,
  SQL, extraction and composition. Auth/entitlement metadata uses the established
  synthetic PostgREST fixture facade and is disclosed as such
- The earlier four-request reservation is never opened or reset. Each new actor
  gets an exclusive fresh journal under the conditional 80-new-request ceiling,
  a 60-second request deadline and a 900-second run deadline

Owned local subprocess groups are reaped on failure/cancellation. The native
receipt records the exact PostgreSQL UUID before allocation and independently
checks its disappearance. Actor cleanup retains the closed dispatch fence, and
uncertain cancellation/persistence stays uncertain in its journal. The host also
checks the recorded actor PID inside the runtime. Only a PID whose command line
matches this run's immutable actor script and `--stdio` may be sent SIGTERM and,
if needed, SIGKILL. An unrelated or reused PID is never signalled. Forced cleanup
keeps the run incomplete; it does not manufacture accounting durability. Task
journals/workspaces remain for reconciliation and cannot be reused as a fresh run.

## Offline proof and remaining native gates

The controlled integration fixture exercises the actual actor `serve_frames`
protocol and CanarySendGuard through the real owned host bridge. It covers source
pins, challenge/identity handshake, request/observation correlations, a smaller
controlled shared budget, terminal HTTP/SSE failure, no replay and normal stop.
Controlled leases remain ineligible for live Codex even though they exercise the
same framing implementation. Authenticated unsupported routes stop host admission.

The manifest pins the expanded installed/task source map and both checkpoint
lineages. It cannot claim another source map, account, observation/root/job,
checkpoint, evaluator or merged-main identity. The native runner retains failed
application trajectories, source/event/checkpoint readback and bounded cleanup
receipts under its fresh output directory.

A controlled-native pass requires a successful JUnit result for the exact
application test; missing, empty, skipped or failed results are incomplete. Any
owned cleanup returning a failed verification also keeps the live run incomplete,
even if the application itself completed.

Still required on the actual native host: interpreter/import compatibility,
existing consumer/account policy, firewall admission, actual Codex configuration
behavior, genuine gateway request/usage-row reconciliation, database/persistence
and process-exit evidence, plus exact-ID Langfuse/database/browser readback. The
launcher reports those durable gates as pending. No separate paid, judge, photo,
geocoding or browser actor is started. Ten rounds and two drafts cannot close the
full 250-round or all-seven-skills acceptance.
