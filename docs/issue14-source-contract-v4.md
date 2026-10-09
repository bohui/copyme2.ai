# Recovery source contract v4

This source gate is separate from live-run, provider and semantic evidence.
It verifies the reviewed metadata-envelope recovery at
`e39195b5595de57791398727d8c0ebb9e88de3f7`, tree
`4d07434de5dfc173caf0ab93b93ed8395db77e70`, without relabelling the previous
subscription source snapshot or its failed native attempt.

The v1 derivation module/pins/receipts, v2 auditor/proof and v3 auditor/proof
remain byte-for-byte unchanged. The new proof archives all 287 original v3
runtime inputs using their original Git-blob and SHA-256 identities. Historical
v3 positive and mutation tests run against those verified original bytes, just
as v2's historical tests continue to use their original snapshot. Running
negative tests against already-drifted current files would be vacuous.

The new current gate separately checks 287 runtime/native/dataset/skill/SQL
inputs against the reviewed recovery commit/tree. The only changed prior v3
inputs are the subscription session and runner. Source additions, removals,
byte drift, symlinks, nonregular files and unreadable traversal fail closed.
Cache-like names cannot hide Python, skill or SQL inputs. The three versioned
auditors are explicitly reviewed tooling outside their own snapshots; the native
launcher additionally hashes every tracked Git blob before execution.

The existing fifty-round source-gate entry now requires the new current audit
and the preserved historical derivation. It does not rewrite historical live
eligibility. Reports retain false live authority, false provider capability and
false hard token/monetary enforcement. The recovery does not retrospectively
prove the exact first-run rejection predicate or grant a new provider/budget.

A fresh evaluation still requires the separately approved two 15-turn cases,
160 client requests, 1800-second absolute deadline, exact reviewed source,
existing route/credential, verified binary pins and fresh native resource gate.
The original failed receipt stays incomplete. No automatic retry, deployment,
production migration, judge or Langfuse activation is part of this source audit.
