# Five-case/fifty-input source contract v6

V6 adds a separately bound source snapshot for the explicit
`subscription_fifty` profile. Its commit and tree identities are fixed in
`scripts/issue14_subscription_source_contract_v6.py` and repeated in
`tests/fixtures/issue14_subscription_source_v6.json`. The canonical remote
binding records source integrity only. Independent review and explicit run
admission remain prerequisites; this offline audit does not publish or approve
execution.

The canonical runtime source snapshot is commit
`99cd9533e92508433a475da4718233ee0ce074ff`, tree
`d1ceb2f676d1c7abb7b297dbd43f4b752090ef0d`. V6 monitors 299 source files.
Its proof adds 20 Git objects and has SHA-256
`e299e5a7d8790218fd20318a0ee53d51026b221287c9d90692d253a015ce511c`.

The inventory covers all Python runtime modules under `apps/api` and `scripts`,
all files under `skills` and `supabase`, the root journalist prompt, the existing native
Postgres fixture sources, both the original progressive dataset and the
original five-case input/expected datasets. This includes the fifty-profile
selection, readback, offline coverage, isolated public-photo and browser modules, along
with the revised session, transport, runner and native launcher.

Frontend TypeScript/JavaScript and package manifests are outside this versioned
backend inventory. Native admission separately requires the launcher's full
tracked-Git-blob verification, including frontend source and rejection of hidden
index flags. The owned browser producer must use a hash-verified private copy
of that verified frontend; a V6 pass alone cannot stand in for those checks.

The original five-case input SHA-256 is
`e7f705bc4a96537b01cb5cde7d412972bdd929de49d339bc6b1a95bc9cb43927`.
The separate offline expected-data SHA-256 is
`9391515876dc2f346291e9ecca653e3710a1497d6a03961291cebb8f01d1c242`.
V6 independently pins both original files in addition to authenticating their
Git membership. Monitoring expected data does not make it a narrator input or
authorize placing it in any runtime prompt.

V1 derivations, v2/v3/v4/v5 auditor modules and proofs, and earlier 5/10/15
evidence remain byte-for-byte unchanged. V5 keeps source revision
`3d0e157f0835a72c3fb3aa9ec6766f8c2aaaa67b` and tree
`fda1225d8cde3c00d81d4168e7d7a1a68c4d4b4a`. V6 archives the exact V5
source blobs and exposes them through `historical_v5_files`. The original V5
positive assertions and negative mutations run against that verified archive,
so they neither silently fail on unrelated current drift nor relabel the new
profile as old evidence. Earlier archive helpers and publisher regressions
continue checking their original identities.

V5 is frozen to the final canonical files merged in PR44. Its auditor SHA-256
is `294db5d8aef39d9595a42fe52b2746734059e5124c73f13f66660448ea1826db`
and its proof SHA-256 is
`94070f30ef19b7de626eac54ba1052656d16bf588a0151ddcd90cf5f5d29f78a`.
Its source tree and source-file bytes are unchanged by that canonical binding.

The new proof reuses the unchanged bounded Git-object parser and immutable
parent objects. It adds only the objects needed for the new snapshot and the
V5 archive. Source inventory additions/deletions, byte mutations, forged or
missing object evidence, duplicate JSON keys, unreadable paths, symlinks,
nonregular files and oversize inputs fail closed. The explicitly named auditor
modules remain reviewed tooling outside their own runtime inventories, avoiding
a self-referential snapshot.

A passing V6 audit proves source integrity only. It supplies no live execution,
provider capability, subscription entitlement, publication, semantic acceptance,
hard token/monetary limit, or production authority. The old progressive profile
retains its own limits; the new profile must independently satisfy its explicit
campaign, per-case, native-process and cleanup gates.
