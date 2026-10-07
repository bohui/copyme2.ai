# Ten-round application canary

This is a narrowly bounded application run for issue #12. It is not the full
five-storyteller 250-round acceptance or an all-seven-skills quality result.
The original inputs remain unchanged: harbour English rounds 1–5 with Family
features and Chengdu Chinese rounds 1–5 without Family features.

## Executable application seam

`await scripts.canary_app_launcher.run_application_canary(plan, storages=...,
broker=..., temporal_client=..., worker=..., run_dir=...)` uses authenticated
`UserStorage`, the ordinary `CodexRuntime`, private `CodexWorker` transport,
`MemoryEventWorker`, the canonical composer, and real `MemoirSkillLane` workflows.
The native task owner supplies fresh task-owned PostgreSQL/Temporal resources
and an authenticated guarded worker. The function does not provision a database,
change shared services, obtain a key, create access or authorize live execution.

Only MemoirSkillLane and its activity are registered. Task settings enforce one
activity attempt, one activity slot, preparation concurrency one, cadence five,
and the pinned gpt-5.6-luna role model. The dispatcher awaits timeline extraction
before launching composition; an unsettled lane stops the run instead of
redelivering it. Existing production Temporal defaults remain unchanged.
All private-worker roles share a single serialization lock. A worker failure
stops queued calls. A fresh worker never migrates an inherited customer home.

The application request cap is an additional 80-worker-request stop, not an
upstream accounting guarantee. Every actual upstream send, including Codex
internal generation and semantic repair, must still consume the installed
#14 guard. Its 80-new-send/60-second-request/900-second-run budget remains the
single authority. The earlier four-request pilot reservation is not reused.
No judge, photo, geocoding, paid provider route or account failover is enabled.

## Native bootstrap boundary

The installed gateway is Linux/aarch64; the known Codex executable is on the
Mac. A same-process binding object cannot establish that cross-runtime route.
The native owner must verify an existing Mac consumer-auth path without
exporting the gateway's upstream credential or creating a key. The #14 actor
must provide a concrete authenticated ingress lease bound to the owned actor,
its exact source, one reservation and this run's identity. An arbitrary URL,
a copied JSON readiness receipt or a Boolean is insufficient.

The live CLI remains fail-closed until that lease and actor are implemented and
independently reviewed. The callable application path is ready for controlled
native regression meanwhile; the controlled provider cannot become real-model
evidence by changing a label. PR18's telemetry source remains a separate,
unmerged dependency, with its exact source revision recorded in the plan.

## Evidence and incomplete runs

The plan pins input/expected/truth/oracle/judge-artifact hashes, skill/reference
hashes, evaluator revision, and the exact source revision/tree where available.
A live application entry also requires the exact clean Git head and tree.
Every model-producing private request gets a distinct observation ID under one
of ten root IDs. Background requests additionally carry the real Temporal
workflow/run/activity join; composer requests carry the round-five checkpoint
ID. User testimony never enters Temporal arguments or history.

Partial manifests are saved before dispatch and after each meaningful result.
Failed round and worker trajectories are retained without raw exception text.
Per-round canonical readback retains source versions, stable events and their
evidence; checkpoints retain the saved draft. Binding receipts are reconciled
against roots, observations and jobs. They remain explicitly unverified against
ordinary gateway request/usage storage. Langfuse API/database and browser gates
remain open until actual exact-ID readback is supplied; planned IDs are not
publication proof. The native owner must verify PostgreSQL, Temporal, actor and
owned process cleanup; the app runner only confirms resources it actually owns.

## Tests

`tests/test_canary_app_launcher.py` covers original-input/configuration drift,
worker registration, single-attempt failure, ordered/scoped background dispatch,
failed trajectory retention, root/job links and evidence honesty.
`tests/test_canary_worker.py` checks configuration, serialization and stop behavior.

`tests/test_canary_application_native.py` is the real PostgreSQL/Temporal ten-round
regression with controlled external provider replies. Run it only after the
parent grants the native resource window, using the existing UUID Apple Container
postgres:18.3 fixture with TCP disabled and no shared mounts or published ports.
It verifies ten original round sources, two drafts and joined worker/job receipts.
It has been collected in cloud but has not been executed there. Real Codex/actor
compatibility, live model quality and durable/browser evidence require separate
native tests and the exact reviewed integration head.

## Authenticated host bridge (offline implementation)

`scripts.canary_gateway_bridge.py` owns a loopback Uvicorn socket and one local
`docker exec -i` child. The gateway-runtime actor is a separate #14 dependency.
The bridge does not mount the general gateway router or publish a container port.
It forwards only authenticated POST `/v1/responses`, pins the run/model and
preserves the existing consumer Authorization. That consumer must already be
intended for this gateway. A Memoir-to-LiteLLM credential is not interchangeable.

The current verified topology has no gateway-bound consumer credential on the
Mac. Native launch therefore remains blocked, even though the host protocol is
implemented. No key was copied, created or granted. The exact runtime Python
path in the command gate also requires native verification before launch.

NativeGatewayLease is constructed only by spawning its constrained owned actor
command and validating a fresh challenge, actor identity, run/source/account
bindings and exact source hashes. It cannot be built from an externally supplied
readiness JSON or a URL. The fixed controlled subprocess has a distinct boundary
mode and can never authorize the live worker constructor. The live worker also
pins the installed Codex executable's SHA-256 and uses the lease's own endpoint.

Frames use `memoir-canary-stdio/1`, one unique ID per operation and a 16 MiB bound.
Bad JSON, duplicate keys, mismatched IDs, EOF, timeouts or ambiguous responses are
terminal. There is no replay. Consumer authentication is neither written to
argv/files/logs nor allowed in response frames. The upstream account token is
never available on the host. Uvicorn cannot replace the parent signal handler.

Explicit stop allows the actor 12 seconds for guard cancellation and genuine
request-row persistence. The bridge then bounds local child/listener shutdown.
A forcibly killed local docker-exec process does not prove its remote actor
exited: the receipt keeps `actor_exit_verified=false` for native reconciliation.
These are owned task processes only; no shared daemon cleanup is permitted.

## Hidden existing-key input helper

The separate `scripts/canary_gateway_auth.py` helper reads no credential when
imported. The native owner invokes `authenticated_canary_worker(...)` only after
review and user handoff. It preflights the exact actor target before prompting,
then keeps the existing gateway key inside the owned lease/worker scope. It
clears the worker key, closes the lease and drops input references on exit.
Python immutable strings do not provide guaranteed memory zeroization.

Default input is `getpass` in a private local terminal. Echo fallback and piped
stdin are refused. Alternatively `input_mode='environment'` consumes and removes
only `MEMOIR_CANARY_GATEWAY_API_KEY` from that task process. It neither reads nor
overwrites normal `MEMORY_SPARK_LLM_API_KEY`, project `.env`, shell profiles or
persistent settings. No key is created, saved, broadened or printed. The key
must already authorize the existing gateway; the actor still verifies its scope
and pins the approved selected account. Never put the key in chat or argv.

A local input-shape diagnostic command is:

```
python -m scripts.canary_gateway_auth --check-input
```

This command only checks hidden input and immediately clears it. It makes zero
authentication/model calls and explicitly reports `gateway_auth_verified=false`.
It is not an activation command or a successful gateway-key validation. The
actual native handoff should enter through the reviewed
`authenticated_canary_worker` context around `run_application_canary`, so input
is held only for that owned run. Its PostgreSQL/Temporal setup and exact runtime
actor source integration remain with the native task owner; do not ask the user
to activate an incomplete topology. All helper tests use synthetic keys only.
