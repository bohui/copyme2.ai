# Sources and baseline

## Project-specific baseline

This skill is based on the user's CopyMe2 memoir workflow and the documents supplied in this conversation:

- `Memory_Spark_Full_Specification_v1.0.md`: source/evidence revisions, progressive invalidation, manuscript blocks, photographs, language separation, approvals and edition handoff.
- `Mira_Memoir_Journalist_System_Prompt_v1.0.md`: patient oral-history tone, factual attribution, uncertainty, hints versus testimony, narrator control and non-coercive completion.
- Latest user requirements: chronological chapters with meaningful titles; pictures from authorised uploads/chat/memory skills; progressive enrichment; **7,000 words maximum per chapter**; a free-round-completion preview trigger; and a separate storytelling-completion formal-composition trigger.

The explicit 7,000-word ceiling in this skill supersedes earlier illustrative chapter-length suggestions for this workflow. It does not edit the original specification or change an existing customer's purchased plan.

All heuristic thresholds, soft length ranges, schemas and tool capability names in this bundle are proposed implementation decisions, not vendor guarantees or experimentally validated psychological thresholds.

## Official technical references

Checked 30 September 2026. These references support format/API choices only; the custom workflow and code are authored for this request.

[S1] OpenAI, skills documentation. Skill directory structure, `.agents/skills` discovery, explicit invocation and optional `agents/openai.yaml` invocation metadata.

`https://developers.openai.com/codex/skills`

At retrieval this redirected to:

`https://learn.chatgpt.com/docs/build-skills`

[S2] Agent Skills specification. `SKILL.md` frontmatter, required name/description, scripts/references and progressive disclosure.

`https://agentskills.io/specification`

[S3] MDN, `Intl.Segmenter`. Locale-aware word segmentation, `isWordLike`, and why splitting on spaces fails for Chinese and other languages.

`https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Intl/Segmenter`

No price, commercial media licence or model-performance claim is made by this bundle.
