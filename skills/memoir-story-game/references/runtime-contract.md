# Scene selection and separate game builder

Memoir owns two planning calls on `MEMORY_SPARK_MEMOIR_COMPOSER_MODEL`:

1. Chapters plus the canonical timeline produce a full scene pool, with recommendations.
2. After the owner confirms scene IDs, the selected subset produces the final creative brief.

`apps/api/story_game_runtime.py` runs these calls using the shared skill and
`proposal.md` or `brief.md`. The independently installed `higgsfield-websites`
skill then runs on Astra through `apps/api/higgsfield_game.py`. Its content stays
outside Memoir's prompt sources and Langfuse catalog. See
[the host setup guide](../../../docs/story-game-scene-selection.md) for updates.

## Pool and human confirmation

The host reads completed composer prose and the full canonical timeline under
current Shape, formal-edition, adaptation-consent and source/policy fences.
One to 128 distinct options must cover every supplied event. Each has an exact,
unambiguous chapter quotation, an exact title/person substring, supported event
IDs, a recommendation flag and a short reason. Life stages come from those events;
an option cannot combine stages. Every represented stage needs a recommendation.
Input over the bounded capacity fails explicitly rather than silently dropping events.

The durable job moves from `pending` through `running` to `selection_required`.
It has no worker lease while waiting for the owner and no build is dispatched.
The owner receives options grouped by life stage, editable count and checkboxes,
and a notice that more scenes increase generation cost and time. Recommendations
are initial checkbox values, never approval. Confirmation sends the exact pool
digest and option IDs. PostgreSQL verifies ownership, current source authority,
unique nonempty IDs and the digest, then saves the confirmation. It orders choices
by the original pool and records the owner, time and selection digest. Repeating
the same selection is idempotent; changing a confirmed set is rejected. A selected
subset need not cover every event: full coverage applies to the pool.

## Brief and delegated build

The build claim requires that saved confirmation. The composer sees only selected
scene text and returns a creative brief plus their complete ordered indices.
The host validates and saves it; retries reuse the saved brief. The final request
contains the brief, selected scenes, locale, UI labels and Memoir export contract.
Unselected passages and private chapter/event/source identities do not reach Astra.

The private worker loads a snapshot of the separate skill's Markdown files. Astra
can read its game references and validate the webpage through bounded tools.
It must read the entrypoint, game flow, design system and stylization reference,
and validate the complete HTML. The final model output references the saved
artifact digest, avoiding a second copy of the entire document. Only this tool
loop uses `gpt-6-astra`; planning calls use the composer setting. A receipt records
all response IDs, the managed prompt manifest and the installed skill digest.

This adapter targets the existing offline Memoir player: the generated artifact
contains static HTML/CSS and generic scenery; Memoir supplies movement, NPC memory
interactions, connected scenes and the complete text version. Upstream Cloudflare
scaffolding, generated media, shell commands, account requirements and public
Higgsfield deployment do not apply to this export target. The original upstream
skill remains unmodified and can still be used separately with its normal CLI.

## Authority, retries and playback

Pool claims last 180 seconds with a 150-second deadline. Brief plus game building
has a 900-second lease and 840-second deadline, including a bounded 780-second,
12-round Astra loop. Each phase allows three explicit attempts. Every provider
body send, final save and protected delivery rechecks source, consent, composer
snapshot and job authority. No authority locks are held while a provider generates.
Revocation withholds old content and clears saved planning projections.

The final save must exactly match the confirmed scene subset and its digest.
Success saves the game for immediate private play and links the project URL;
there is no extra person-permission or publishing approval screen. Existing host
sharing controls can later grant public or invited-friend access.

The document runs in an opaque-origin `sandbox="allow-scripts"` frame. A nonce
permits only Memoir's trusted movement script. Validation rejects model scripts,
handlers, extra biographical text, external assets, links, frames and CSS URLs.
The frame has no network, parent-page access or storage privileges. Closing,
navigation, project/phase changes and source revocation remove it.
