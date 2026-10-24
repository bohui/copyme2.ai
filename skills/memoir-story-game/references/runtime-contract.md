# Two-step game runtime

The skill has two model operations:

1. Composer chapters plus the canonical timeline produce a source-linked scene plan.
2. Astra turns the validated scenes into an HTML/CSS webpage. The host validates the page and injects its trusted movement, interaction and text-version runtime.

`apps/api/story_game_runtime.py` implements both operations. Each receives the shared skill instructions and its phase prompt (`proposal.md` or `webpage.md`). Model responses follow `schemas/scenes.schema.json` and `schemas/webpage.schema.json`. The page builder uses `MEMORY_SPARK_STORY_GAME_BUILD_MODEL`, defaulting to the verified `gpt-6-astra` binding; scene planning uses the composer model setting.

## Input and completion

The authenticated host reads the current composer snapshot and its canonical event dependencies. The `chapters` input contains the composer's saved prose sections, titles and source references; `timeline` contains the corresponding canonical event records, including supported stages, dates and uncertainty. Composer prose replaces the old extractive-only game input. One to 128 scenes cover the supplied timeline. A person can recur, and a memory marker can have `person=null`.

Validation requires exact chapter quotations, matching title/person substrings, valid chapter/event references and complete event coverage. The webpage must contain the required control slots, permitted static HTML/CSS and supplied UI text. Model-written scripts, event handlers, external resources, frames, forms and additional personal claims are rejected. Successful completion returns the scenes and validated webpage. A build failure leaves the job retryable; a partial plan is not delivered as a game.

## Host integration

The existing authenticated game action owns admission and persistence. It keeps the current Shape/source/policy checks, formal source-completion fence and edition-bound adaptation consent outside the skill. The UI's create action prepares those host records when needed. It requires a completed, current composer snapshot; it does not ask the user to build a second memoir manually.

A job binds the composer snapshot/digest/revision, source/event/policy/preferences, current Shape reply, formal edition and consent revision. Claims have a 360-second lease and three attempts. Each model-body send, final save and delivery rechecks the host authority. The two-call generation deadline is 330 seconds. Source or consent changes withhold stale results.

After a successful build, the host stores the private game and returns `published`. There is no game-review screen, per-person approval form or publish action in the creation flow. No human approval receipt is manufactured. The browser opens the saved game immediately and can reopen it without another model call.

## Playback

The generated document runs in a frame with `sandbox="allow-scripts"` and an opaque origin. The host adds a nonce-protected script and a restrictive content-security policy. Astra supplies static markup and styles; only the trusted host script runs. The page has no network access, parent-page access or storage privileges. Keyboard/touch movement, connected scenes, memoir interactions and a complete text version use the existing runtime. Escape, closure, project/phase changes and revocation remove the frame.

Saving, access control and display belong to the host UI. Public hosting, external recipients and public links are not authorized by private workspace generation.

The older request/candidate fixture validator is a development artifact, not the two-step runtime's admission service or model contract.
