# Issue 41: photo-linked memories and a private question pool

Implementation draft for [issue 41](https://github.com/bohui/copyme2.ai/issues/41).

## Scope

- Authoritative one-turn public photo selections and owned private uploads are frozen with accepted turns. Retry identity preserves the original snapshot; consuming a cue leaves favourites intact.
- A single structured collector response supplies the acknowledgement and private pool (up to five candidates). Only its acknowledgement and one chosen question reach chat/speech. Local and remote collectors share the schema. Photo-only input creates no narrator source or billable narrator round.
- Photo associations cite exact current narrator source/version/quote. Canonical extraction binds only a unique supported event and preserves distinct events. Public metadata and generated descriptions remain derived context, separate from testimony.
- The canonical composer receives current confirmed significance, not image pixels or publication permission. Lifecycle changes invalidate photo links, candidate plans and frozen manuscript work; stale final conversation commits are fenced too.
- Personal images use owner-authenticated private Storage access, operation-aware policies and an idempotent upload identity. Guest transfer rebinds ownership and revokes the superseded guest. See [Storage prerequisites](issue41-private-storage.md).

## Verification recorded before independent review

- TDD red/green for pool/schema isolation, exact evidence, duplicate/foreign identities, pause, unsupported year, old-testimony reuse, ambiguous repeated quotes, canonical projection, acceptance/replay and local/remote parity.
- 259 focused and adjacent Python tests passed: collector/runtime/worker, photo state, recovery, language, canonical composer and task runtime.
- 221 JavaScript tests passed; production frontend build and ICU localization validation passed.
- Real PostgreSQL standalone integration exercises the authenticated HTTP/runtime, persisted exact typed/transcribed source, photo cue consumption, distinct canonical continuation and memoir projection. Three primary cases passed. Standalone mode is deliberately not RLS proof.
- PostgreSQL migration tests cover source/turn/policy/lease fencing, immutable replay, guest transfer, private upload identities, correction/deletion/unlink invalidation and canonical evidence.

## Acceptance coverage and open gates

| Issue scenario | Deterministic coverage | Remaining acceptance |
| --- | --- | --- |
| 1. Recognised photo | Typed/transcribed HTTP + SQL, exact Chinese source and canonical link | Live reviewed collector output; browser |
| 2. Continuation with distinct move/residence | HTTP + SQL canonical identity and photo scope | Live reviewed interpretation |
| 3. Undisclosed selected photo | Deferred candidate/card, no false association | Browser and reviewed model choice |
| 4. Return to deferred photo | Private pool/bridge contract | Fixed multiround model trajectory |
| 5. Private upload | Actual image validation, Storage client contract, SQL metadata/link | Native RLS and disposable Storage HTTP |
| 6. Photo-only | No narrator source or counted round; runtime and UI fixtures | Browser and reviewed model wording |
| 7–8. Other events and stage/year breadth | Candidate identity/context/bridge and unsupported-year checks | Reviewed EN/CN multiround output |
| 9. One question/pool/pause | Schema and rendered output; voice chosen-reply test | Browser + live continuity evaluation |
| 10. Privacy isolation | Explicit SQL owner checks; native policy fixtures prepared | Native PostgreSQL/RLS and Storage HTTP |
| 11–12. Replay/ordering/account change | Runtime, SQL, JS, prepared browser fixtures | Browser + conventional concurrency checks |
| 13. Grounding/uncertainty | Metadata-only provenance, exact quotes, ambiguous/foreign evidence rejection | Reviewed model outputs |
| 14. Lifecycle/memoir | SQL invalidation/fences; canonical projection tests | Native RLS/reviewed final source |
| 15. Continuity evaluation | Controlled bilingual source/output fixtures | Separate bounded model-output evaluation approval/run |

## Blocking environment limits

This cloud runner denies socket creation. Native PostgreSQL server and Chromium therefore cannot start; escalating execution also fails before launch in the runtime mount setup. No sandbox/security settings were changed. The explicitly selected standalone PostgreSQL fallback runs real SQL/transactions but implicitly bypasses RLS even after SET ROLE; its native-only RLS tests remain skipped, and no privacy acceptance is inferred from that fallback.

Before merge: independent exact-head cloud review/fix loop, native PostgreSQL/RLS and actual private Storage HTTP checks with synthetic separate principals, shipped frontend browser tests at desktop/phone widths, reviewed English/Chinese multiround model-output evaluation, and current required-check/mergeability/deployment review. The draft does not claim any of these missing gates passed. Existing issue-14 frozen source-inventory gates were already stale on main and are not repinned or waived here.

No production migration, deployment, credential/security configuration change, public image publication or paid model call was performed by this implementation task.
