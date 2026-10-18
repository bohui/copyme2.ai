---
name: memoir-composer
description: Compose a vivid, source-grounded memoir from canonical events and original evidence at authorised private checkpoints, after free rounds, after storytelling confirmation, or when dependencies change. Enforce 7000 words per chapter.
metadata:
  version: "1.1.0"
  product: "CopyMe2 Memoir"
  companion: "Mira"
---

# Memoir composer

Compose from the host's canonical events and authorised original evidence. The
host owns admission, cadence, snapshots, consent, publication and payment. Its
current composer prepares evidence, drafts prose and reviews that exact draft.

## Model instructions

Each phase has one source, versioned under
`memoir/skills/memoir-composer/` in Langfuse. The application exports those
versions into this bundle and assembles them through its bounded request
contract. Read the relevant phase and shared references when using this bundle
outside the application; this guide is not a second system prompt.

| Phase | Source | When to read |
| --- | --- | --- |
| Prepare | [prompts/prepare.md](prompts/prepare.md) | Prepare one canonical event and its exact original references. |
| Draft | [prompts/draft.md](prompts/draft.md) | Write or revise the manuscript selected by the host plan. |
| Review | [prompts/review.md](prompts/review.md) | Check the exact candidate against its original evidence. |
| Batch preparation | [prompts/batch/prepare.md](prompts/batch/prepare.md) | The host supplies a bounded completed-round batch. |
| Batch composition | [prompts/batch/compose.md](prompts/batch/compose.md) | Revise the existing manuscript with that batch. |

The draft and review templates reference `narrative_enrichment`, defined once in
[references/narrative-enrichment.md](references/narrative-enrichment.md).
Review also references `editorial_review`, defined once in
[references/editorial-review.prompt.md](references/editorial-review.prompt.md).
The application resolves these references before model dispatch. A reference
or an earlier draft supplies guidance or context; original testimony supplies
personal facts.

## Integration and completion

1. Before integrating, read [the runtime contract](references/runtime-contract.md).
   Require the host's immutable request, canonical event IDs, source versions and
   current permissions. Composer consumes that event index; extraction belongs
   to the timeline skill.
2. Use [workflow routing](references/workflows.md) for the host-authorised trigger
   and [editorial and length rules](references/editorial-and-length.md) when
   checking the supported 7,000-word chapter ceiling. The ceiling is not a target.
3. Run `node scripts/memoir.mjs plan --request request.json --out plan.json`.
   Follow the plan's readiness and output kind. Use the phase instructions above
   with the supplied evidence and saved prior manuscript.
4. Validate and render with the existing [local utilities](scripts/memoir.mjs).
   Their deterministic checks complement evidence-to-prose review; retain
   findings and exact-base proposals for protected text. Completion is a saved,
   source-linked, reviewable private result with truthful coverage.

For source/media integration, read [sources and rights](references/sources.md).
Publication, access changes, charges and printing remain separate host actions.
