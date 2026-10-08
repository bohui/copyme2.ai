# Source contract v3: preserve history, audit the new runtime separately

The historical fifty-round proposal is not a hash lock that can be silently
updated to describe later code. Its original 13 pinned sources and receipts
remain unchanged. The v2 auditor and its proof also remain byte-for-byte unchanged.

The v3 proof is anchored to the independently reviewed subscription executor
integrated with PR43 at
`bbf35488e37d7a83f9542a8b09ba2b7a81e2ca05`, tree
`f2a5418d5fd8916cc98231030f7558b275cc774c`. It proves 287 current inputs:
application/scripts Python, all skills and SQL/configuration under Supabase, the
native fixture modules, the exact synthetic dataset and existing source configs.
The PR43 integration preserves every upstream blob and adds the reviewed place
identity runtime and skill changes to this current snapshot. No previous v1/v2
evidence is relabelled. Cache-like names cannot hide Python, skill or SQL inputs.
Git commit/tree membership and both Git-blob/SHA-256 file hashes are checked.
Extra runtime inputs, missing/unreadable files, symlinks and nonregular files fail.
The two explicitly reviewed auditor modules are tooling outside their own source
snapshots; the native launcher separately verifies every tracked Git blob.

All 110 original v2 source bodies are additionally archived with verified Git and
SHA-256 identities. This lets the unchanged v2 auditor and its original mutation
tests run against the exact historical snapshot. Running its negative tests on an
already-drifted checkout would be vacuous; simply repinning v2 would misrepresent
the historical evidence. The v3 current-source gate is separate and strict.

The old fifty-round source-gate test now requires v1 historical integrity, v2
historical integrity and a passing v3 current snapshot. Its live-authority and
provider-capability assertions remain false. No historical planner, gateway,
receipt, numerical derivation or strict token-budget eligibility is rewritten.

This is source integrity only. It is not provider capability, budget/spending
approval, native execution evidence, semantic acceptance or permission to merge.
Execution still requires the separately approved scope, exact-head source check,
fresh memory-pressure/resource lease, private existing configuration and owned
native teardown evidence. The original strict Issue 14 ACs remain open.
