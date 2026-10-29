# Skill-owned prompt structure

## One owner per instruction

Langfuse owns versions; the repository contains exported, pinned deployment
artifacts. The name identifies the skill and task. Issue numbers, dates and
release versions belong in metadata and version history.

```text
memoir/
  skills/
    memoir-interviewer/
      reply
      policy-review
      policy-review-opening
      governed-turn
      repair-{codes,prefix,suffix,acknowledgement}
      greeting-{begin,continue}
      strategy-proposal
    memoir-author-timeline/
      instructions
      contract
      extract
      extract-with-hints
      derived-hints
      attribution
      window
      shared/grounding
    memoir-composer/
      prepare
      draft
      review
      batch/{prepare,compose}
      outline/{leaf,merge}/{en-AU,zh-CN}
      outline/shared/{prefix,suffix}
      shared/{narrative-enrichment,editorial-review}
    memoir-memory-context/{instructions,summary}
    memoir-place-journey/{instructions,extraction}
    memoir-historical-news-research/{instructions,contract,discovery}
    memoir-family-tree/instructions
    memoir-place-groups/instructions
    memoir-story-game/{instructions,proposal,brief,higgsfield,webpage,runtime-contract}
    memoir-place-photo-research/instructions
  shared/
    bounded-context/{policy,en-AU,zh-CN}
    place-conflicts
  evaluation/
    five-case-judge
    five-case-judge/guard
    trajectory-judge/{system,rubric}
    live-skills/...
  speech/{default,en-AU,zh-CN}
```

`memoir-interviewer` names the existing foreground collector's prompt ownership;
it adds no runner or scheduler. The other skill sources remain inside their
existing skill directories. Generic bounded-worker policy has one shared owner
because both timeline and composer consume it.

The interviewer catalog contains 11 prompts for the sole `reply-v2` mode,
including conditional privacy-review opening, repairs, begin/continue actions and
background strategy proposals. The 13 prompt sources and receipts used only by
the retired collector variants have been removed with their configuration and
prompt assembly paths. Language and strategy now reach the reply as context data.
The catalog maps the retained Langfuse names to their existing source files.

The [privacy/repair optimization](issue53-policy-repair-20261022.md) composes
optional acknowledgement guidance from the same privacy core and transmits only
the matching repair hint. It adds no model call; source publication and deployed
latency acceptance remain separate from namespace cleanup.

The October 22 interviewer cleanup changes record names only in the local
Langfuse project. All 46 version records retain their IDs, text, numeric versions,
timestamps, labels, tags, config and commit messages. It creates no prompt
versions. The matching receipts are exported from the renamed records; the
23 source texts and compiled instruction hashes are unchanged.

## Runtime contract

`apps/api/prompt_catalog.py` maps every managed name to one source. The runtime,
exporter and dataset evaluator share that catalog. `prompt_path` resolves local
files; runtime generation does not contact Langfuse. Each exported file has an
exact numeric version and SHA-256 receipt.

Story-game planning has two composer-model phases: `proposal` creates the full
pool with recommendations by life stage; after explicit owner selection, `brief`
composes the creative request for exactly the chosen scenes. Both reuse
`instructions`. The delegated Astra builder consumes `higgsfield` plus `webpage`
for the Memoir export target, and reads the separately installed upstream skill
at runtime. Its content digest is recorded independently; upstream updates do not
edit Memoir's Langfuse prompts. `runtime-contract` remains the host-admission
evaluation context. Selection is a required human gate; private saving, sharing
and publication remain host concerns, without another publishing-review prompt.

`apps/api/prompt_composition.py` expands curated shared references. Fourteen task
templates reuse policy from a single owning source. Budget validation and worker
execution both call the existing bounded contract builder, which composes phase,
locale, feature and current-page constraints. There is no separate partial
preflight instruction builder.

Selected-collection outline leaf/merge jobs remain distinct bounded structural
operations in the composer namespace. They reuse their existing guarded transport
and shared instruction policy; they do not extract autobiographical events.

## Removed paths

The root `memoir/composer`, `memory`, `interview`, and `research` prompt namespaces
were replaced with skill ownership and shared policy. No `lane`, `two-lane`,
`runtime`, issue number or release-date folder remains in the active catalog.

Ten guide-only Langfuse entries were removed; their useful repository documents
remain. `SKILL.md` for composer now routes readers to its actual phase templates
and shared references. Composer's old model index, full-source preview fallback,
and uncalled private-draft executor were removed as well. Current canonical
composition starts from the host-owned event index. Saved job IDs and historical
source metadata remain readable without restarting old generation.

## Publishing and evaluation

```sh
make prompt-export
make prompt-export PROMPT_NAME=memoir/skills/memoir-composer/draft
make prompt-check
make prompt-eval
```

Export selects the highest numeric version, then writes the source and receipt.
Check validates exact pinned versions and composed references. A unique short
filename is accepted; ambiguous short names require the full Langfuse name.
Commit and deploy exported artifacts to use a prompt change in the application.

Dataset names remain under `memoir/evaluation/`. Preflight records the selected
prompt, dataset snapshot, component pins and assembled digest. Explicit model
experiments use that assembled text. Application behavior and publication gates
still require the bounded runtime checks.

See [the individual inventory](Langfuse_Prompt_Usage.md) for all 69 sources,
consumers, removed entries and the version-history migration details.
