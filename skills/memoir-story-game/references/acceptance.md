# Acceptance milestones

Read the [game generation specification](specification.md) before planning a game
or changing this skill. It defines the personal-homepage goal. M0–M4 below retain
the current runtime's acceptance evidence; M5 covers the expanded introduction.

Advance only with recorded evidence. The private runtime now has disposable
PostgreSQL and actual browser integration checks. Live-provider generation and
the five-case campaign require their separate retained receipts; source changes
alone do not satisfy them.

| Milestone | Exit evidence | Status in this package |
| --- | --- | --- |
| M0 — completion and privacy | Host-authenticated completion bound to run, manuscript digest/revision, all chapters and validation; separate adaptation consent; blocked Shape-only, preview-only and composition-only cases; threat/permission review. | Formal completion, exact-edition consent, individual permissions and candidate approval exercised on disposable PostgreSQL. |
| M1 — small playable loop | Actual fixed renderer with two connected scenes, two grounded NPCs, controllable author, keyboard and touch movement/interaction, collision and safe spawn, smooth transition; reduced motion, keyboard focus/escape, text-only equivalent, no trapped focus; teardown on route/phase exit and remount. | Actual DOM/CSS renderer: two scenes/NPCs, keyboard/touch, text version, focus/close and reload recovery passed in English desktop and Chinese phone layouts. |
| M2 — source/privacy validation | Evidence and chosen manuscript coverage for every factual line; negative tests for unsupported text, stale sources, minors/sensitive claims, revocation, URLs/code and server-data leakage; independent editorial and author review. | Actual stored-original matching, unsupported-quote/identity rejection, owner checks, exact-candidate approval and revocation tests passed. Human permission authenticity remains an author assertion. |
| M3 — Shape/jobs/races | UI and server Shape gates; idempotent replay; two-worker lease race, correction/consent/source/manuscript change during generation and before commit/delivery; atomic stale-write rejection; private cache and access-loss behavior. | Real game job, token, consent/source invalidation and private HTTP-send race tests passed on disposable PostgreSQL; browser revocation removes play. Live provider/campaign evidence pending. |
| M4 — regression/licenses/performance | Existing affected suites plus real browser accessibility and lifecycle tests; license ledger and retained notices; recorded device/browser/build and performance measurements with budget comparison. | Affected runtime/browser regression checks are retained under var/story-game-checks; no real-device performance budget claim. |
| M5 — personal introduction across scenes | Author review confirms that NPC encounters introduce the intended experiences, interests and values; distinct scenes contribute to that introduction; repeated travel preserves controls and interaction state; the complete experience passes privacy review; reused resources have recorded origins and licenses. Rerun affected M0–M4 checks as the runtime expands. | Target specification. The two-scene prototype does not establish completion of this milestone. |

Run the isolated checks from the repository root with the existing test extra's
`jsonschema` dependency (no install is performed by this package):

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s skills/memoir-story-game/tests -v
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_memoir_story_game.py
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_formal_memoir_routes.py tests/test_formal_memoir_worker.py
PYTHONDONTWRITEBYTECODE=1 python3 skills/memoir-story-game/scripts/validate.py \
  --request skills/memoir-story-game/tests/fixtures/request.json \
  --candidate skills/memoir-story-game/tests/fixtures/candidate.json \
  --current-request skills/memoir-story-game/tests/fixtures/request.json
```

Suppress Python bytecode so local test caches do not enter the harness's recursive
skill manifest. The validator returns sanitized status codes only and never writes a playable
artifact. Omitting fresh current authority blocks delivery. Fixtures contain only
invented people, statements and IDs; they do not authorize real use.

`tests/test_formal_memoir_postgres.py` uses the repository's task-owned disposable
PostgreSQL fixture. It exercises actual RPCs and synthetic evidence; it does not
connect to configured Supabase. Current task-owned checks use `MEMOIR_TEST_POSTGRES_BACKEND=native` with a
verified fresh allocation and cleanup receipt. Do not substitute an existing database when a disposable backend
is unavailable. See [formal-workflow.md](formal-workflow.md) for scope and limits.

## Additional runtime/performance checks

Test forward/backward scene travel repeatedly, holding touch across transitions,
focus loss, resize, keyboard-only dialog opening/closing, tab order, screen-reader
text equivalence, OS and in-app reduced motion, replay/restart, empty/denied content,
renderer initialization twice under React development behavior, and unmount while
assets are loading. Verify zero residual canvases, animation frames, listeners,
timers or pointer capture after cleanup. Use per-instance event listener removal.

Initial **proposed** measured budgets for M4: at 60 Hz target p95 frame time at or
below 16.7 ms during movement; p95 interaction response below 100 ms; no increasing
heap/listener/canvas count after 20 mount/unmount cycles. Record representative
desktop and touch devices, browser versions, cold/warm state, asset sizes and at
least three runs. Establish baseline loading/memory sizes before assigning their
budgets. A missed budget gets a profile and one justified change with remeasurement;
do not optimize blindly or sacrifice grounding, accessibility or cleanup.

## Open-source reuse, verified 2026-10-13

- [Phaser 4.2.1 package](https://raw.githubusercontent.com/phaserjs/phaser/v4.2.1/package.json)
  identifies version 4.2.1 and MIT. Retain its
  [license notice](https://raw.githubusercontent.com/phaserjs/phaser/v4.2.1/LICENSE.md)
  when distributing engine code. This is a recommended pinned starting point,
  not a dependency installed by this package.
- The [official Next template](https://github.com/phaserjs/template-nextjs) provides
  a client bridge and scene lifecycle; its
  [PhaserGame source](https://raw.githubusercontent.com/phaserjs/template-nextjs/main/src/PhaserGame.tsx)
  demonstrates game destruction at unmount. Adapt the pattern to the repository's
  actual Next version; retain the [MIT notice](https://raw.githubusercontent.com/phaserjs/template-nextjs/main/LICENSE)
  for copied code. Do not copy its `log.js` telemetry, reserved Phaser logos,
  characters or artwork. Pin and record the exact template revision before copying.
- [Kenney Tiny Town](https://kenney.nl/assets/tiny-town) declares CC0. It is an
  optional generic art reference, not proof of side-scrolling suitability and not
  personal historical imagery. Choose suitable assets later, verify their per-pack
  license and record path, hash, origin, license and any notices in a local registry.

No third-party runtime code, artwork or assets are bundled. A future ledger must
cover all copied code and assets, even where attribution is optional. Keep remote
provenance URLs server-side in that ledger; the play package carries local keys.
No paid engine, remote asset service, telemetry or generation service is assumed.
