# Memoir scene selection and Higgsfield

The game action first prepares the full pool from composer chapters and timeline.
The owner chooses scenes by life stage and confirms their count before a game
build starts. More scenes cost more and take longer. Two composer-model calls
produce the pool and confirmed game brief; only the separate Higgsfield game
builder uses Astra. Saving and sharing remain in Memoir, private by default.

## Independent upstream updates

Install or update the separate upstream skill:

```sh
python3 scripts/update_higgsfield_skill.py
```

The command downloads the current `higgsfield-ai/skills` main branch, keeps the
unmodified `higgsfield-websites` directory and MIT licence under ignored
`var/external-skills/`, and records the upstream commit in `.upstream.json`.
Use `--ref <upstream-tag-or-branch>` to select a release. This does not edit Memoir
prompts or create Langfuse versions. Compose mounts the external-skills parent
read-only into the game worker; the next build reads the updated files. Active
builds retain their original instruction snapshot and content digest. A missing
or incompatible installation fails the build and retains the owner's selection.

Outside Compose, set `MEMOIR_HIGGSFIELD_SKILL_PATH` to the installed directory.
The existing worker secret, model gateway and publication database configuration
are required. The adapter calls `gpt-6-astra` through the gateway; it exposes only
skill-reference reads and HTML validation tools. It never enables shell tools in
the conversation worker or installs private stories in global skill files.

Memoir's target is its existing isolated player. The external game design flow
supplies the visual approach, and the Memoir export contract supplies the HTML/CSS
interface. This is an offline export adapter, not a Higgsfield Cloudflare site.
Higgsfield CLI deployment is public, so that path is excluded. No Higgsfield login
is needed for this adapter; upstream media generation and server multiplayer are
outside its export capabilities.

## Durable API

- `POST .../story-game` prepares the pool and returns `selection_required`.
- `GET .../story-game/:gameId` returns the owner's pool and recommendations.
- `POST .../story-game/:gameId/selection` accepts `expected_pool_digest` and
  `scene_ids`, saves human confirmation, composes the brief and builds the game.
- Repeating a confirmed selection retries the same durable job and saved brief.
  Published jobs return the saved result without model calls. An altered selection
  or stale authority is rejected before dispatch.
- `/memoir/game/:projectId` and the existing host sharing controls are unchanged.

Prompt Markdown is reviewed and merged before publishing numeric Langfuse pins.
The managed artifacts are instructions, proposal, brief, Higgsfield handoff,
webpage export contract and runtime contract. Upstream skill text has its own
content digest in game-build receipts rather than a copied Langfuse prompt.
