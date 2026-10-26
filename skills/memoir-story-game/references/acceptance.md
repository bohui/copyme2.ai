# Scene-selection acceptance checks

A complete result has a full grounded pool, an explicit owner selection, a brief for that exact subset and a validated playable webpage. The host saves and presents the result privately.

Verify the two Sol max planning requests: chapters/timeline to a full pool, then the confirmed subset to a brief. Between them, require the human-selection pause and a current pool digest. Check recommendations per life stage, scene IDs and evidence, full pool coverage, repeated people and person-free memory markers. The chosen subset may omit events. The default installed NovelToGame builder runs analysis, concept, design, whitebox, art and production with Sol max. The explicit Higgsfield backup uses Astra. A failed plan or webpage must not leave a playable partial result.

Verify page structure and source-safe UI text. Reject generated scripts, event handlers, external URLs, CSS imports, frames, forms and missing controls. Verify that the page-builder request does not contain provenance or job authority.

Exercise count changes and individual selection by life stage, with the cost notice visible before confirmation. No brief or builder call may occur before confirmation. Exercise keyboard and touch movement in both directions, reversible illustrated transitions, repeatable reading after completion, unique-memory progress, text equivalence, focus, Escape and cleanup in the generated-page frame. Verify an opaque frame origin, host-only script execution and no external requests. There is no publishing or person-permission review after the scene choice. Reopening a saved game makes no model call; retries reuse the saved brief and matching validated NovelToGame checkpoints.

Retain database checks for owned-project reads, current composer snapshots, leases, retries, source/consent invalidation, provider-body send races and private delivery. Use only the repository's fresh disposable PostgreSQL fixture.

Run the focused suites:

```sh
python3 -B -m pytest -q tests/test_story_game_runtime.py tests/test_higgsfield_game.py tests/test_memoir_story_game.py tests/test_novel_game_integration.py tests/test_novel_game_journey.py tests/test_novel_game_player.py tests/test_novel_game_live.py
MEMOIR_TEST_POSTGRES_BACKEND=native python3 -B -m pytest -q tests/test_story_game_runtime_postgres.py
```

`tests/test_story_game_browser.py` additionally exercises the full application when `MEMOIR_BROWSER_URL` points at a task-owned source frontend. Ordinary tests control model responses; they do not establish live model quality. The explicit paid command `scripts/run_novel_game_live_example.py --execute --env-file <gateway.env> --output <private-output>` uses the fictional age-eight source, actual selection UI, API, PostgreSQL and worker with live Sol max calls. Resume an interrupted run with `--resume` and the same output directory. Its composer and sign-in are controlled fixtures. Retain all stage receipts and observed desktop/touch QA. Model prompts remain unpublished until reviewed/merged main is synchronized through the repository's prompt workflow.
