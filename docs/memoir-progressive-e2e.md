# Progressive memoir end-to-end coverage

The progressive regression target is:

```bash
make memoir-progressive-test
```

It has two layers:

- `skills/memoir-composer/tests/progressive_e2e.test.mjs` loads the checked-in
  skill manifest and 10 distinct sample lives: five `zh-CN` China profiles and
  five `en-AU` Australia profiles. Each profile contributes 31 grounded
  storyteller rounds. The test checks the private checkpoint, the 20-round
  free-preview gate, a review-only formal memoir, stable chronological chapter
  IDs, source-backed blocks, a photo slot with rights metadata, and a
  source-backed progressive update.
- `tests/browser_memoir_progressive_e2e.py` runs 31 submitted turns for both
  locales against the rendered app. It checks the place journey, place-group
  and photo requests, family and timeline surfaces, persisted 63-message
  history, and the stage-3 `composer_delivery` envelope. At stage 3 it asserts
  that delivery and chapters are visible, four structured chapter bodies render,
  and the previous location/photo overview is absent.

The browser worker response is deterministic by design. It verifies the
application/UI contract and does not claim live-model quality. Live provider
evaluation remains a separate concern; the composer layer’s quality gates are
the evidence-grounding, chronology, source lineage, uncertainty, word-count,
rights, protected-edit, and review-only checks exercised by the Node suite.
