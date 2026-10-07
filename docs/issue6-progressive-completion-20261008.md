# Progressive memoir completion — 8 October 2026

Branch: `codex/progressive-memoir-events`, based on main
`e6c06cafd5ad56f34b31edb8dd5e85dd7e96bc56`.
Requirement: [issue #6](https://github.com/bohui/copyme2.ai/issues/6) and
[the agreed shared event specification](Memoir_Shared_Event_Index_Spec.md).

Main already contains the canonical PostgreSQL MemoryEvent index, original-source
acceptance, Temporal skill lanes, coalesced catch-up, bounded parallel preparation,
revision fencing, migration/transfer support, and relationship-driven family tree.
This branch completes gaps found while exercising that implementation.

## Changes and TDD evidence

| Behavior | Observed red result | Result after the change |
| --- | --- | --- |
| Extraction repeats an unchanged saved event | Event revision and change sequence increased from 1 to 2 | Extraction coverage advances; event, section and manuscript revisions remain unchanged; no additional drafting call |
| Five completed rounds contain only acknowledgements | Composer returned `retry` despite successful empty extraction | Checkpoint finishes collecting with no prose, error or provider call; a later supported checkpoint produces the first draft |
| All event evidence is withdrawn | Empty completion still showed `updating` because its source cursor stopped before the withdrawal | Coverage includes the withdrawal; old prose stays withheld and polling can settle |
| Draft checkpoint is pending without an open workspace | Browser could not find the updating status | Compact status and saved draft remain available beside the conversation; ordinary early extraction does not activate an empty workspace |

Three additive migrations replace the affected application RPCs. Historical
migrations are unchanged. Repeated facts still undergo scope, evidence, revision
and correction validation before being treated as a no-op. Additional source
links remain changes. Empty composition commits recheck current canonical evidence,
policy, source/event versions, manuscript revision, ownership and deadline. They
cannot discard supported canonical prose.

Both skill contracts and the README now describe the current shared persistence
and checkpoint behavior. Family-tree dispatch and premium display entitlements
retain their existing application rules.

## Verification

All database tests use disposable PostgreSQL containers. Temporal tests use local
isolated dev servers. Model/provider responses, authentication metadata and browser
project metadata are controlled external boundaries; application RPCs, workers,
validation, rendering and event edits execute normally.

- 223 tests passed across shared PostgreSQL/story workflows, actual Temporal
  recovery, canonical provenance, date evidence, integrated skill contracts and
  conversation recovery.
- 180 affected API/provider, family, preview, private-draft, migration contract
  and Temporal dispatch regressions passed.
- 16 browser contracts passed: checkpoint polling/completion/retry, original
  typed/dictated input, desktop/mobile tag editing, conflicts and reload persistence.
  The tag-edit fixture uses the current activated-workspace precondition.
- 62 composer Node tests passed.
- Production Next.js webpack build passed; both locale catalogues validated
  (542 matching messages); both modified skills passed `quick_validate.py`.
- Python compilation and `git diff --check` passed.

The extended empty-to-supported checkpoint scenario was rerun after adding its
round-ten assertions and passed. Initial native PostgreSQL setup failed; the
repository's disposable Apple Container harness provided the passing database
evidence. Fixture/syntax setup failures are not behavioral TDD evidence.

Reproduce the main integration run:

```sh
MEMOIR_TEST_POSTGRES_BACKEND=apple-container python3 -m pytest -q \
  tests/test_shared_memory_events_postgres.py tests/test_memoir_lanes_temporal.py \
  tests/test_canonical_composer_provenance.py tests/test_memory_event_date_evidence.py \
  tests/test_integrated_timeline_contracts.py tests/test_conversation_recovery_api.py
```

The browser suite is `tests/test_shared_memory_browser.py` with
`MEMOIR_BROWSER_URL` pointing to an isolated source frontend and the same disposable
PostgreSQL backend. Existing story coverage remains mapped in
[the original acceptance matrix](issue6-acceptance.md).

These results establish controlled end-to-end application behavior. Live model
semantic quality, CI and production rollout are separate acceptance steps. No
production migration, deployment or shared-service restart was performed.
