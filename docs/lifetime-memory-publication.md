# Governed publication boundary (W2 adapter, not activated)

The opt-in adapter requires a server-owned transactional PostgreSQL connection.
PostgREST alone cannot keep a transaction open across an HTTP send. Deployment and
configuring persistent database access remain separately approved rollout work.
The repository optional dependency `lifetime-memory` supplies psycopg; tests use
an isolated synthetic local database, not a configured Supabase service.

The linearization boundary is completed ASGI send versus correction transaction
commit. Lock the project, authoritative profile, then lease; validate the immutable
per-body fence; await the actual send; close/rollback. Queue insertion, producer
completion and a prior RPC check are not publication. Dequeued text, final results,
saved receipts containing personal context and nonstream JSON need this same guard.
No old queued body may inherit a newer fence. Bytes already delivered or buffered
in the network cannot be recalled, and this implementation does not claim otherwise.

Send duration is at most two seconds by default, at most five by configuration,
and shorter than the remaining lease by 100 ms. Lock acquisition is separately
bounded. Disconnect, timeout and cancellation close the connection and release
locks. Never wait for producer work or another RPC while holding the send guard.

Lock graph:
- publication/capture: project -> profile -> lease; read identity after locks
- existing interview acceptance: project -> profile
- existing phase/plan publication: project -> lease (and its existing profile reads)
- direct preference write: profile -> identity revision, never project
- policy invalidation: project -> identity -> disposable continuity
No identity mutator may subsequently acquire profile. A fresh empty profile row is
created under project before the fence is captured, so absence cannot bypass locking.

The additive epoch trigger clears the disposable execution pointer and removes typed
continuity projections when policy changes. It does not erase canonical sources,
receipts, or historical backups. Prior user-wide unprovenanced generated memory must
not be fed to governed execution. Pending integration must guard all relevant routes,
worker/in-process publication, checkpoint/extraction/composer/artifact jobs and
conservatively disable direct personal-context WebRTC until equivalently revocable.

The cold-open helper attempts one compatible resume, then at most one canonical
cold start for a typed missing/corrupt/incompatible state error. Authentication and
provider errors propagate explicitly. Returned thread IDs are only candidates;
installation must occur in the same valid fenced transaction as the reply commit.
