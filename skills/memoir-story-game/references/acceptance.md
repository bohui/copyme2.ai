# Scene-selection acceptance checks

A complete result has a full grounded pool, an explicit owner selection, a brief for that exact subset and a validated playable webpage. The host saves and presents the result privately.

Verify the two composer-model planning requests: chapters/timeline to a full pool, then the confirmed subset to a brief. Between them, require the human-selection pause and a current pool digest. Check recommendations per life stage, scene IDs and evidence, full pool coverage, repeated people and person-free memory markers. The chosen subset may omit events. Only the separate installed Higgsfield build uses Astra. A failed plan or webpage must not leave a playable partial result.

Verify page structure and source-safe UI text. Reject generated scripts, event handlers, external URLs, CSS imports, frames, forms and missing controls. Verify that the page-builder request does not contain provenance or job authority.

Exercise count changes and individual selection by life stage, with the cost notice visible before confirmation. No brief or Astra call may occur before confirmation. Exercise keyboard and touch movement, scene travel, interactions, text equivalence, focus, Escape and cleanup in the generated-page frame. Verify an opaque frame origin, host-only script execution and no external requests. There is no publishing or person-permission review after the scene choice. Reopening a saved game makes no model call; retries reuse the saved brief.

Retain database checks for owned-project reads, current composer snapshots, leases, retries, source/consent invalidation, provider-body send races and private delivery. Use only the repository's fresh disposable PostgreSQL fixture.

Run the focused suites:

```sh
python3 -B -m pytest -q tests/test_story_game_runtime.py tests/test_higgsfield_game.py tests/test_memoir_story_game.py
MEMOIR_TEST_POSTGRES_BACKEND=native python3 -B -m pytest -q tests/test_story_game_runtime_postgres.py
```

`tests/test_story_game_browser.py` additionally exercises the full application when `MEMOIR_BROWSER_URL` points at a task-owned source frontend. Ordinary tests control model responses; they do not certify Astra's visual quality. Model prompts remain unpublished until reviewed/merged main is synchronized through the repository's prompt workflow.
