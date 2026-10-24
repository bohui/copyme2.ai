# Two-step acceptance checks

A complete skill result has a grounded scene plan and a validated playable webpage. The host automatically saves and presents that result privately.

Verify the two model requests in order: composer chapters/timeline to scenes, then scenes to Astra. Check scene IDs and evidence, full event coverage, repeated people, person-free memory markers, and more than two scenes. A failed plan or webpage must not leave a playable partial result.

Verify page structure and source-safe UI text. Reject generated scripts, event handlers, external URLs, CSS imports, frames, forms and missing controls. Verify that the page-builder request does not contain provenance or job authority.

Exercise keyboard and touch movement, scene travel in both directions, interactions, text equivalence, focus, Escape and cleanup in the actual generated-page frame. Verify an opaque frame origin, host-only script execution and no external requests. The UI must go from Create to Play without review or publish buttons. Reopening a saved game must make no model call.

Retain database checks for owned-project reads, current composer snapshots, leases, retries, source/consent invalidation, provider-body send races and private delivery. Use only the repository's fresh disposable PostgreSQL fixture.

Run the focused suites:

```sh
python3 -B -m pytest -q tests/test_story_game_runtime.py tests/test_memoir_story_game.py
MEMOIR_TEST_POSTGRES_BACKEND=native python3 -B -m pytest -q tests/test_story_game_runtime_postgres.py
```

`tests/test_story_game_browser.py` additionally exercises the full application when `MEMOIR_BROWSER_URL` points at a task-owned source frontend. Ordinary tests control model responses; they do not certify Astra's visual quality. Model prompts remain unpublished until reviewed/merged main is synchronized through the repository's prompt workflow.
