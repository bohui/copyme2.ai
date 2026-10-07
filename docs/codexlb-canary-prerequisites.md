# Guarded Memoir canary: offline prerequisites, execution blocked

This branch contains a reservation/send guard, controlled worker configuration,
correlation fields, and a ten-round manifest. It does **not** install an upstream
guard in codex-lb, load runtime credentials, start a live canary, save real-model
drafts, or publish new Langfuse data. Both the existing canonical live gate and
the new canary CLI reject live execution. Source review of these prerequisites
must not be interpreted as clearance of an installed provider adapter.

The base is main `291622826cdfb776e946dcd92b65d2fdaf4923ad`, tree
`1b5ab8687053bd18e8dbf44609430a60a2917918`. Original MemoryEvents, source-claim
validation, metadata stripping, event vetoes, and null-claim rejection are untouched.
PR18 `701032f608a7d4c35b3ad098cf3ff1ec7c705563` remains a separate unmerged revision.

## Implemented boundaries

`CanarySendGuard` reserves a fresh UUID/source/account/model journal exclusively
before a supplied wire adapter is entered. Its shared ceiling is at most 80 entries,
one concurrent generation, 900 seconds per run and 60 seconds per generation,
including response consumption. HTTP generation and each WebSocket `response.create`
use the same counter. Account/model mismatch, protocol failure, ambiguous completion,
invalid/missing usage, duplicate completion, known returned-model mismatch, timeout,
or cancellation stops further sends. Existing reservation paths cannot be reopened.
Owned iterators close on cancellation and consumer disconnect; uncertain upstream
generation cancellation remains unverified. Journals retain IDs and reported usage,
with no story text, output body, reasoning, credential or external exception text.

Its receipt intentionally says `boundary_verified=false` and
`guarded_send_entries`, rather than claiming actual gateway request counts. The
native binding still must extract account identity from the actual authenticated
dispatch context, fix the endpoint, prevent hidden wire/client retries, apply
known-secret redaction before crossing the runtime boundary, and prove that every
HTTP/WS generation/replay passes through this instance. Supplying a fingerprint
as a Python argument is not independent account-binding proof.

`CanaryWorker` runs only with `evidence_mode=controlled_provider`, a fresh task home
and explicit disposable loopback endpoint. Its command must select a checked-in
controlled app-server fixture; a `controlled_provider` label cannot select a real
Codex binary. All worker roles use requested
`gpt-5.6-luna`, low reasoning, a synthetic fixture key, and the ordinary worker/
app-server protocol. CLI overrides disable request/stream retries, automatic Codex
memory generation/use, WebSocket transport for this worker, and web search. The
outer worker deadline is 300 seconds; collector/workspace limits remain at most
240 seconds. Production defaults remain intact. Optional worker constructor
arguments avoid loading an inherited real key and pin effort in task tests.

Trace, observation, job and checkpoint IDs now survive the existing correlation
and Responses client-metadata seams. This does not populate absent background
correlation or establish durable Langfuse publication by itself. The native test
used a controlled external app-server process, not the installed Codex binary or
a real model; Codex CLI `0.155.1` was inspected with a fresh home only.

The retry/memory configuration keys are documented in the
[official Codex configuration reference](https://developers.openai.com/codex/config-reference/).
Their actual installed-client behavior needs a controlled native HTTP/stream test
before activation; the protocol fixture observes passed options and correlation.

## Canary manifest and still-missing integration

The English harbour owner has family enabled for all five canary rounds. The
Chinese Chengdu owner has family disabled for those five rounds, preserving its
original pre-round-16 boundary. Each gets a fresh synthetic owner/project and its
first five unchanged inputs, with one private checkpoint at round 5. The manifest
declares ten expected root IDs and two checkpoint IDs; every evidence field starts
as `not_run`, and neither owner/project nor draft has actually been created.

The proposed allocation is 79 logical calls under a single 80-actual-request cap:
20 collector/workspace, 10 extraction, 2 locale, 10 place recovery, 15 family
recovery, 10 event preparation and 12 draft/review. Family includes 5 initial focus
passes plus up to 10 semantic repair passes. Composer includes 4 initial calls plus
up to 8 repair calls. Those 18 repairs and all hidden app-server sends consume the
same actual cap. There is no completion guarantee. Judge/photo/geocoding/paid
routes and transport/activity redelivery/failover are excluded from the proposal.
The user subsequently approved this envelope conditionally on exact implementation
review. That approval allows request/time-only subscription handling despite unknown
token ceilings; it does not install the guard or authorize shared-service changes,
judges, photo/geocoding, paid routes or the full 250-round run. The prior four-request
reservation remains consumed. No new live reservation is created by this branch.

The live runner is not implemented. Before it can be added, the isolated Temporal
registration must enforce one activity attempt, one model activity at a time,
and no legacy private-draft worker registration. Preparation concurrency must be
one in task configuration. Current main otherwise retains three Temporal attempts,
preparation concurrency three and a 600-second inner draft timeout; this branch
does not claim to have changed those deployed paths. Original family/composer
semantic repair logic also remains intact. It must debit the native upstream guard.

A real run needs accepted replies, canonical background extraction, the two saved
private drafts, ordinary gateway request/usage rows, workflow/source/checkpoint
joins, exact-ID Langfuse API/database verification and authenticated browser
observations. Trace-field forwarding alone is insufficient. PR18 integration
authority and supported browser access remain unresolved. Subscription token
ceilings remain unenforced and must be reported honestly under the approved
request/time-only envelope. This ten-round canary cannot establish all-seven-skills or 250-round
acceptance.

## Gateway placement blocker and exact effects requiring a decision

Read-only inspection of the installed `/app/app` source in
`llm-provider-codex-lb-1` established these send paths:

- `modules/proxy/_service/streaming/mixin.py` invokes `core_stream_responses`.
- `core/clients/proxy.py` sends through both aiohttp HTTP and `CodexClient` routing;
  it also submits WebSocket generations via `send_json`/`send_str`.
- `modules/proxy/_service/streaming/retry.py` handles retries and account selection.
- `modules/proxy/service.py` includes refresh and failover behavior and constructs
  shared repository/session, encryption, bridge and routing dependencies.
- `modules/api_keys` supports assigned-account scope, which is persistent key
  configuration rather than an established per-run external dispatch guard.

A host proxy or worker-request counter cannot intercept retries/replays *inside*
that existing gateway process. An ordinary HTTP request to its unchanged daemon
therefore cannot establish the proposed ceiling or pinned account.

The preferred next scope decision is a **temporary task-only gateway actor in
the existing runtime**, using reviewed installed dispatch code, a pinned existing
consumer/account authorization context and process-local hooks around every actual
send. This would require explicitly authorized runtime-only reading of the existing
encryption key, selected encrypted account row and existing consumer authorization;
no credential may be exported or created. If ordinary gateway accounting writes
are retained, it also needs authority to append only this run's genuine request/
usage rows to the gateway store. A task-owned process/endpoint and exact cleanup
would be added; unsupported dispatchers must fail closed. Such an actor has not
been implemented or started here. Its consumer authentication, repository scope,
low-level SDK/WS hook coverage and credential boundary need independent review.

The alternative is to modify/instrument/restart the shared gateway daemon and
change its account/retry routing. That affects other consumers and conflicts with
the current no-shared-change scope. No such change is made or requested implicitly.
The parent must resolve gateway placement and the exact effects above before
runtime activation work; approval of 80 calls alone is not adapter readiness.

## Validation and TDD evidence

The observed red/green slices were: missing guard module (1 failure → 1 pass),
request/binding/privacy validation (5 failures → 6 passes), fragmented/invalid SSE
(8 failures → 14 passes), deadlines/cancellation/reservation/exception privacy
(3 failures → 17 passes), consumer disconnect (1 failure → 18 passes), controlled
worker routing/correlation (2 failures → 2 passes), controlled-label command gate
(1 failure → 3 worker passes), and honest manifest/live CLI
gate (2 failures → 2 passes). Final counts and exact commands are retained in the
separate evidence packet. Controlled callbacks and subprocesses are fixture evidence;
they are not real model quality or actual installed gateway accounting evidence.

No live provider call, runtime credential read, consumer/key change, shared setting,
service restart, PR merge, deployment, migration, or model judge/photo request was
performed for this branch. Existing consumed pilot reservations and completed
evidence remain intact.

## Cloud HTTP facade binding (not activated)

`scripts/canary_gateway_binding.py` adds a process-local adapter for the exact
installed `ProxyService → core_stream_responses → stream_responses` path. It
retains account selection, existing consumer authorization, installed payload/
header construction and ordinary gateway request/usage recording. It does not
replace the real application with another direct-pilot driver. The only supported
transport for this task is HTTP to the existing subscription Responses endpoint.

`InstalledGatewayBinding(guard=guard, core=app.core.clients.proxy,
service=app.modules.proxy.service)` exposes an `install()` context manager.
Installation first checks the three audited source hashes (core proxy, service
facade and streaming mixin) and refuses altered/unavailable files. It replaces
only exports inside the task's already isolated process and restores them on
exit. It must never run inside the shared daemon. It disables the facade's
compact, control, thread-goal, transcription, file-upload and WebSocket exports.
The task ingress must itself expose only the existing authenticated Responses
path, with no other consumer traffic, background tasks or unguarded egress path.
Those native actor/ingress conditions are not established by this source package.

The wrapper verifies the actual selected gateway row ID against the reservation's
SHA-256 account binding, rejects repeated gateway request IDs and opaque
`CodexClient` routes, and serializes whole installed-core streams. It never
silently converts an opaque route into direct egress. Safe correlation fields
from `client_metadata` accompany the fixed run/gateway-request IDs in the journal.

The supplied `GuardedHTTPSession` implements the small HTTP-session protocol used
by the audited direct core path. The final `post()` checks the exact actual
account header and bearer value against the same in-runtime authorized call,
the fixed endpoint, requested model and text-only payload. It refuses built-in
remote tools, image/audio/file payloads and non-default service tiers. Every
allowed HTTP request is reserved before the private HTTPX transport runs.
HTTPX connection retries, redirects, environment proxies and persistent
keepalive are disabled. Failures stop the shared guard; a 307 is never followed.
No credential is loaded by this module, exported, written to its journal or
included in a receipt. Known bearer values are redacted from returned SSE JSON
and response headers before returning to the installed core.

This task transport deliberately buffers at most 8 MiB of SSE and validates the
full completion/usage before exposing any bytes to the installed core, whose
SSE iterator stops at the first terminal event. That avoids falsely leaving a
settled upstream call pending when the normal core parser stops early. The
trade-off is no incremental user-visible streaming until a call completes.
The same 60-second per-send and 900-second run ceilings remain; a slow/incomplete
stream may end the canary rather than finish the ten rounds.

### Offline evidence and remaining native seam

Controlled protocol tests use a genuine disposable loopback HTTP server and
synthetic credentials. They count actual server contacts, including zero-contact
exhaustion/mismatch cases, 307/500/invalid-completion one-contact terminal stops,
competing reservations, credential redaction and unsupported dispatcher rejection.
Facade tests cover account changes, replay, source mismatch and patch/restore.
They do not establish installed runtime compatibility, native authorization,
ordinary request-row persistence, real model quality or durable trace evidence.

The native executor must check `core/clients/http.py::lease_http_session` compatibility,
installed HTTPX availability, and whether the selected existing account uses the
audited direct route. If it instead uses an opaque route, stop and report that
specific incompatibility; do not change routing/security settings. In a separate
task runtime, exercise the existing gateway facade against a controlled endpoint
before activating the conditional real-app canary. Run the application/Codex
path with the #12 isolated launcher and #15 telemetry changes after their reviews.

The fresh canary has its own at-most-80-request reservation. The previous four-call
pilot was a separate consumed approval; its reservation and artifacts remain
immutable and cannot be reused. No new live reservation has been created here.
The execute CLI remains blocked and `boundary_verified` stays false pending the
native checks and independent exact-source review. No token ceiling, monetary
cap, billing assertion or full Issue #14 acceptance is claimed.

### Review fixes: terminal errors and native settlement

Contradictory completion status, non-null completion error/incomplete details,
standalone error envelopes, and SSE `event: error` or failure names are terminal,
including when they appear after an apparent completion. The controlled HTTP
regressions prove one contact followed by a permanent stop, not two successes.

A guard stop is converted at the installed facade boundary to one content-free
`response.failed` event with `canary_guard_stopped`. Raising a generic exception
before the first block made the exact installed `_stream_once` record success;
that path is no longer used. The original installed SSE terminal-error path
records an error and `record_success=false`. The binding now also pins the
streaming helper source hash and rejects installation if this sentinel is in
its account-recovery/transient sets or is classified as retryable/penalizing.
No classifier is replaced. Source-extracted settlement tests exercise the exact
installed method and helper functions with synthetic dependencies, both with
and without a previous-response/account affinity. These tests are still distinct
from full native gateway execution and ordinary database readback.

## Executable task actor and authentication blocker

`scripts/canary_gateway_actor.py --stdio` is an executable, dependency-injected
runtime entrypoint. It validates every framing ID and the exact installed/task
source hashes before runtime imports; authenticates an existing gateway consumer
with the original required-auth function; resolves only account IDs against the
approved account fingerprint; and creates one fresh, exclusive reservation.
It uses `get_proxy_service_for_app` and `_proxy_repo_context` from the installed
factory. It does not invoke the shared application's lifespan, initialize/migrate
a schema, create a bootstrap token, purge bridge rows or start schedulers.

The task app exposes only POST `/v1/responses`. It preserves installed required
consumer authorization, capability checks, policy/usage enforcement and firewall/
request-ID/body-limit middleware. It narrows the existing authorized account set
in memory, rejecting an account the consumer cannot already use. It rejects a
configured paid model-source route and invokes the original subscription stream
with bridge forwarding disabled. No stored consumer/account/routing policy changes.
Framed requests use an untrusted peer; forwarded client-origin headers are refused,
so a stdio connection cannot pretend to be a trusted/localhost network peer.
A firewall denial remains a blocker.

The newline-JSON protocol is `memoir-canary-stdio/1`, bounded to 16 MiB. Initialization
returns only safe identities, actual source hashes and a challenge echo. Request
frames preserve the existing consumer Authorization in memory; replies contain
only the bounded HTTP status/content-type/body and a safe guard receipt. Source
pins cover the actor, binding and guard files as well as the inspected installed
files. EOF/stop is monitored concurrently with an active generation and cancels
it. Stop closes the guard, drains task request-log persistence with a bound, closes
only owned HTTP/database resources and restores task-local exports. Forced remote
termination or failed persistence drain cannot be reported as verified cleanup.

The host half is owned by #12's `canary_gateway_bridge.py`; it must use an owned
loopback listener and child process, never shared daemon restarts or published
container ports. These two code paths have not yet passed a full native handshake.

Verified native facts: gateway Linux/aarch64 has no Codex executable, while the Mac
has Codex. The supplied-session lease is statically compatible and installed HTTPX
is 0.28.1. No existing gateway-bound Mac consumer credential was found in the
checked configuration; the existing Memoir worker credential targets LiteLLM.
That credential must not be sent to this gateway actor to probe access. The
native check established `api_key_auth_enabled=true`, including for genuine
loopback requests. The existing LiteLLM mapping instead uses a direct ChatGPT
subscription handler, bypasses codex-lb, has no effective auth file, and includes
401 refresh/resend. It cannot establish this guarded gateway route. No further
routing alternative is proposed. An existing codex-lb consumer key that already
permits `gpt-5.6-luna` and the selected account must be entered locally through the
task's secure input before native launch. Do not create/export a gateway token,
disable auth, or overwrite the ordinary Memoir/LiteLLM configuration.

The actor route/protocol tests use fake native dependencies and no real account.
A real factory/auth/accounting roundtrip, integrated actor/bridge/launcher review,
resource-safe native test, and verified consumer path are still required. The
original live CLI remains blocked. Runtime activation has not occurred.

### Actor review corrections

The actor pins the supplied crypto/settings source and requires an existing,
nonempty encryption key only after consumer/account authorization succeeds.
A process-local read-only replacement for the original key fallback rejects a
missing/changed/different key file; it cannot create directories or keys. The
owned service returns the existing selected account without refresh, and rejects
forced refresh. An expired token can end the run after one guarded failure; no
freshness promise or refresh/resend is made. Auxiliary core archive callbacks are
suppressed only in this task process; ordinary request/usage persistence remains.

Consumer credential redaction parses JSON and SSE, including escaped Unicode,
before serializing any response frame. API auth/quota/error HTTP responses also
stop the run before another application request, even if no upstream send occurred.
Cleanup bounds cancellation/draining independently, attempts later resource stages
after a failure, and records false/uncertain outcomes. Closed dispatch/key/archive
fences remain installed for the one-shot interpreter lifetime, including late
cancelled tasks; they are not restored while asynchronous work might still run.
Native controlled validation must still establish that the installed service's
constructor dependencies cause no unrelated auxiliary writes, background starts
or egress. These code changes do not constitute that native evidence.

Incomplete cancellation of an application/ASGI operation before the first guarded
send is also sticky cleanup uncertainty. The actor marks both active-operation
and overall cleanup incomplete, preserves the closed dispatch fence, and writes
an atomic, fsynced `cleanup.json` beside its owned reservation. A completed guard
with no active wire send cannot override a still-pending application operation.
This uncertainty is retained even if that deferred task finishes later.
