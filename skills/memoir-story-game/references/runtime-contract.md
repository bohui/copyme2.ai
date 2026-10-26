# Scene selection and resumable NovelToGame builds

The default builder is NovelToGame with GPT-6.1 Sol max. Planning uses the same
model and effort. `MEMOIR_GAME_BUILDER=higgsfield` selects the independently
installed Astra backup; failure never silently starts a second provider.

## Selection and authority

`story_game_runtime.py` proposes a grounded pool covering the complete approved
composer/timeline snapshot. The UI groups options by source life stage and checks
recommendations by default. Owners can change the count and individual options.
More scenes increase time and cost. Recommendations are not confirmation.
The exact saved pool digest and nonempty scene IDs must be confirmed by the owner
before the build claim. The original pool order determines the selected sequence.
A selected subset need not cover the complete timeline. PostgreSQL validates the
source quotations, selected IDs, consent, edition and current source authority.

The confirmed subset produces a saved creative brief. Retries reuse that brief.
Only selected quotations and their timeline metadata enter the builder; other
passages and private source references remain outside the build requests/player.
Repeated options from one chapter become separate supported memory stops.

## NovelToGame stages

The private worker runs `apps/api/novel_game.py`: analyze, concept, design,
whitebox, art and production. Each loads its unmodified upstream skill/references
from the reviewed `deps/novel-to-game` revision, plus Memoir's managed adapter,
journey policy and stage prompt. Art/build also consume the asset policy.
The host verifies upstream bytes against `deps/novel-to-game.lock.json` without
requiring Git inside deployed containers. Dependency upgrades refresh this lock.

Successful stage outputs and real model receipts are stored in a service-only
PostgreSQL checkpoint table, keyed by game, stage and exact request hash.
A retry with unchanged input reuses them. Every checkpoint read/write and provider
body send rechecks the job/source/consent fence. No generation holds an authority
lock while waiting for a model. Partial/failed builds never become playable.

Design returns a validated continuous `JOURNEY_PLAN.json`. The fixed runtime
allows both-direction keyboard/touch walking, smooth reversible scene transitions,
unlimited proximity reading before/after completion, unique-memory progress,
source text, reduced motion, ending and restart. Models supply data and styling;
they cannot supply executable HTML/JavaScript. The application art pass binds
source-supported locations to the original shared illustrated place library.
The standalone adapter can additionally prepare new scene illustrations through
its explicit image-generation workflow. Shared avatars, UI and music are reused.
A missing age uses an explicitly unspecified stage and imagined generic avatar.

The host plays the whitebox before art, then runs complete desktop and touch
production replays. Final receipts require six upstream checks: launch, render,
input, coreLoop, outcome and restart. These observations establish technical
playability, not subjective fun or physical-device coverage.

## Saving and playback

Pool claims last 300 seconds with a 280-second deadline. Build claims last
3600 seconds with a 3480-second deadline; individual model stages are bounded.
The final save requires the original selection digest and verified model/build
receipt, and checks every displayed passage against that selection.
The game is immediately available privately through Memoir's existing project
URL. Public and invited-friend sharing remain host controls, without another
publication approval screen in this skill.

The NovelToGame artifact is validated journey/source/CSS data. The browser loads
the host-owned runtime and public generic artwork, then creates an opaque-origin
`sandbox="allow-scripts"` frame. Only the trusted runtime receives a script nonce.
The frame permits image/audio requests solely to the application's hashed stock
asset path; it cannot connect, submit forms, navigate the parent, or use storage.
Closing, project/phase changes and source revocation remove the frame.
The legacy Higgsfield adapter retains its strict static-markup validator and
trusted player. Its upstream instructions remain separate and updatable.

All Memoir model-consumed prompts live in the managed Langfuse catalog. Review
and merge Markdown to main before publishing actual numeric versions and receipts.
