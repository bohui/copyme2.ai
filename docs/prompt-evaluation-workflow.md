# Changing prompts and their evaluations

`apps/api/prompt_catalog.py` and `scripts/prompt_registry.py` own the managed
prompt inventory. `config/langfuse-evaluation-bindings.json` owns target,
component, dataset and evaluator relationships. `config/prompt-coverage.json`
adds actual consumers, scenarios, controlled regression selectors and reviewed
content hashes. [The generated table](prompt-coverage.md) joins those sources;
[the audit](prompt-audit.md) records the remaining quality gaps.

Coverage is many-to-many: reuse one dataset, evaluator and evaluation run across
multiple prompts when its cases exercise their scenarios. Link every participating
prompt through the target's `evaluated_prompts` and retain the actual prompt
manifest for each case/run, including conditional branches. Review affected shared
cases and graders when a prompt changes; reuse them when they remain suitable.

When adding or changing a prompt, including a shared component:

1. Trace the real assembler and its conditions. Record dynamic loaders, optional
   skill reads, locale/phase choices and prompts carried in input as well as
   instructions. Update all affected target dependency sets.
2. Review representative dataset inputs and expected outputs for the changed
   behavior, including normal, failure, adversarial and bilingual cases where
   applicable. Update the case sources and use a new dataset version when frozen
   gold changes. Preserve prior experiment and item lineage.
3. Review the rubric, code validator and judge calibration. Reference-free online
   judges cannot replace expected-output correctness. Speech, images and playable
   games need their actual modality/outcome checks. Record human calibration
   separately from synthetic wiring tests.
4. Update each affected coverage entry's consumer/scenario/regression metadata
   and `review`: current prompt SHA-256, dataset-binding digest, evaluator digest
   and specific reasons for changing or reusing the cases and grader. The digest
   helpers are in `scripts/audit_prompt_coverage.py`. Updating hashes is a review
   receipt, not evidence of model quality.
5. Run the listed regressions. Commit prompt Markdown before publishing with
   `make prompt-sync`; update hosted grader templates when their prompt changes.
   Refresh the dated metadata evidence with `make prompt-coverage-snapshot`, then
   regenerate with `make prompt-coverage`. Review and commit real receipt and
   inventory updates and run `make prompt-check`, as specified in the README. The check fails
   for a missing prompt entry, removed consumer, stale review or missing component.
6. For a model-quality claim, execute the actual runtime assembler against the
   selected dataset and retain its complete prompt manifest, exact versions,
   fixture/version IDs, grader version, scores, failures and missing coverage.
   Confirm conditional prompts were actually exercised. Keep a held-out set and
   human review for high-impact interpretation and calibration.

For retirement, prove there is no supported caller, including dynamic stage and
skill loaders. Save the source, receipt and every published version before
removing it from the catalog and current dependency sets. Verify the exact
Langfuse project and archive before deleting the named remote prompt. Keep
historical datasets, experiment records, prior receipts and upstream dependencies.
Preserve each version's raw configuration, labels (including `latest`) and tags;
use the raw prompt API with an encoded name, since the high-level prompt wrapper
does not expose all recovery metadata.
Remote deletion is performed by `scripts/retire_prompt_artifacts.py` only from
clean `main` matching live `origin/main`, after checking all remote versions
against the committed archive. The existing post-pull publisher runs that cleanup
after merge. Its CLI defaults to a read-only plan; `--execute` has the same main
guard. This keeps current main's prompt checks working during PR review.

```sh
make prompt-coverage-snapshot # Read-only APIs and explicit local metadata DB snapshot.
make prompt-coverage          # Regenerate the table; no model calls.
make prompt-check             # Review hashes, bindings and exact published versions.
```

Repository `AGENTS.md` points here so future Codex sessions retain this workflow.
This uses Codex's documented [project instructions](https://developers.openai.com/codex/guides/agents-md/).
The evaluation distinctions follow [OpenAI evaluation best practices](https://developers.openai.com/api/docs/guides/evaluation-best-practices)
and [Langfuse evaluator calibration](https://langfuse.com/guides/llm-as-a-judge-calibration-skill).
