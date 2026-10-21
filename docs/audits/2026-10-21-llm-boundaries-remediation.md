# LLM boundary audit remediation

This change addresses all 13 findings in the 21 October audit. The original audit
and inventory remain historical evidence of the pre-change checkout. This report
describes the resulting boundaries; it does not claim live model quality from
fixed provider tests.

| Finding | Change |
| --- | --- |
| 1. Schema policy prose | Behavioral descriptions moved to managed guidance. Schemas retain types, limits, exact source constraints and scoped identifiers. Repair requests use stable codes with managed explanations. Historical acknowledgement copies also have a managed artifact. |
| 2. Unmanaged calls | Photo discovery/caption interpretation and all three probes load registered prompt artifacts. Judges accept managed names rather than arbitrary instruction overrides. Speech selects a managed delivery prompt; environment/request instruction overrides no longer supply policy. |
| 3. Privacy language parser | Python and SQL literal grammars were removed. A bounded current-source-only model phase proposes restrictive controls. Exact spans and bounded action types are validated; a server-only transaction commits restrictions and completion together. Clients cannot certify a review or persist an unreviewed model restriction. |
| 4. Topic/pause classifier | Candidate selection no longer narrows itself using narrator-language regex. Typed model intent is checked against candidate identity, stop state, question delivery and reason consistency. |
| 5. Translation/acknowledgement classifiers | Sibling-age and invitation grammars were removed. Managed guidance and live semantic cases own meaning and attribution. Separate acknowledgement/question fields, streaming isolation and question-mark constraints remain deterministic. |
| 6. Repeated place/date interpretation | Extraction supplies normalized research windows with exact evidence. The API projects those saved windows; the browser does not parse chat to override dates or stages. Photo/news share the normalized period. Window evidence uses original-source offsets in Python and SQL. |
| 7. Caption date grammar | Structured numeric metadata is parsed as a data format. Prose uses a managed extraction contract with date roles, uncertainty and exact observed spans. Host checks reconcile normalized ranges and retain source fetching, URL, rights and bounds enforcement. Date roles exposed to the browser are protocol values. |
| 8. Prose rewriting | Timeline output variants compose managed components. Governed continuity and place instructions are separate artifacts. Runtime no longer replaces or slices an English instruction sentence. |
| 9. Generation provenance | Model boundaries record source names, numeric published versions when available, content hashes, compiled static-instruction hash, schema hash and assembly variant. Protocol aliases are labelled contract versions. Native requests forward correlation hashes; Langfuse generations link verified local prompt snapshots where supported. Private narration is excluded from the static manifest. |
| 10. Misleading quality scores | Deterministic scoring exposes completion and explicit literal-contract gates. It does not emit semantic final-response quality. Old semantic substring expectations are retained as dataset data rather than acceptance gates. A live judge is separate and advisory. |
| 11. Retired synthetic seam | The default synthetic command now explicitly replays scorer fixtures, with fixed final-state snapshots. It does not claim to execute the application. Current canonical worker/in-process and SQL replays cover application admission and persistence. Obsolete positive runtime fixtures were updated or replaced. |
| 12. Test/eval separation | Ordinary tests use explicit fixed proposals and deny external sockets/DNS. The standalone photo suite uses the same network boundary. Language cases live in a separate synthetic semantic dataset and an explicit live command. Browser E2E is opt-in before optional fixture imports. |
| 13. Dead stage parser | The unused explicit-stage parser and its phrase-fixture tests were deleted. Source-based extraction owns stage interpretation. |

## PR review regressions

The review of commit `ae790d8` found four introduced defects. The follow-up
changes address each at its calling boundary:

| Review finding | Fix and regression evidence |
| --- | --- |
| Pending review bypassed generation pause | Both retry and newly accepted source paths use one guarded review call. A paused HTTP request leaves the source pending, sends no model request and writes no policy receipt. |
| Recent normalized photo ranges expanded to whole years | Browser validation checks exact ISO endpoints, order, calendar validity and the current window. A fixed October 21 clock retains the June 1 photo through the authenticated photo API and client replay; future and out-of-window endpoints remain rejected. |
| Review ignored runtime provider binding | The runtime forwards its effective gateway and key, including proxy path prefixes. Tests cover pending and new sources with an absent or conflicting environment endpoint/key. Explicit empty bindings cannot fall back to process credentials. |
| Installed photo skill imported the Memoir package | A bundled prompt adapter and the skill-owned prompt resources support isolated installation. Model configuration is checked before loading optional application integration. Offline installed-skill tests exercise caption and discovery requests, exact receipt provenance and rejection of a changed prompt. |

The affected host tests now check stable diagnostic codes and complete provenance
hashes. The two removed language-heuristic expectations belong to semantic
evaluation data; the dataset now has 19 cases. Their semantic correctness remains
unmeasured, including unpunctuated invitations and sibling-age attribution. No
passing fixed proposal is evidence of model understanding.

Follow-up verification:

| Check | Result |
| --- | --- |
| Required `make test-place-research` | 591 JavaScript + 429 API/database + 95 standalone photo tests passed |
| Focused provider, policy, metadata, diagnostic and combined-contract regressions | 293 passed |
| Canonical worker/in-process, HTTP runtime and atomic privacy checks | 52 passed |
| Photo skill packaging | Standard `_validate-skills` target passed |
| Semantic evaluation plan | 19 cases, zero model calls |
| Syntax and whitespace | Python compilation and `git diff --check` passed |

A broader run exposed 46 failures in `tests/test_codex_agent.py` involving removed
legacy runtime methods and missing canonical publication context. The same 46
test IDs fail against an isolated copy of base `d9dfaea` (3 pass on both). These
pre-existing failures remain; the full suite is not reported green. Two further
stale two-lane fixtures from the broader run were repaired and pass in the
focused check above.

## Privacy behavior and tradeoff

Acceptance durably records the source before review. Until review completes,
older private context cannot be admitted for generation or publication. The
review request contains only the pending original source and is fenced through
actual request-body transmission. Incomplete interpretation, provider failure,
invalid evidence or a stale fence leaves the durable pending marker in place.
The model can add exclusions or pauses, never sharing, consent or publication
permissions. Explicit user controls remain authoritative for relaxing policy.

This introduces one model call before ordinary generation. Public prose captions
also require model interpretation; unavailable interpretation cannot certify a
capture date. Live latency, cost and interpretation accuracy have not been
measured by offline replays.

## Prompt publication

Changed/new Markdown intentionally has no invented publication receipt. The
repository requires review and merge to `main` before Langfuse publication.
Offline feature-branch tests load registered source snapshots explicitly; the
production loader continues to reject missing or stale receipts.

After merging, pull `main`, run `make prompt-sync`, review/commit the genuine
receipt updates and run `make prompt-check` before deployment. No prompt was
published from this feature branch, and no production migration was applied.
Schema changes remain in the single fresh-install baseline as required.

## Verification

The required `make test-place-research` target exercises browser logic, the
API/database/client replay, and the standalone photo suite using fixed providers.
Additional checks cover canonical worker and in-process execution, early
acknowledgement, cold replay, source edits, typed policy proposals, atomic SQL
controls, prompt composition/provenance, source-window offsets, speech policy,
scorer behavior and default-suite collection. Exact final counts are recorded in
the PR description after the final runs.

`python3 scripts/evaluate_llm_boundaries.py` is a zero-call plan. The explicit
`--execute` command uses production contract instructions/schemas and an
independent managed judge, recording frozen provenance for both. These are
semantic contract evaluations, not full application live E2E. No live model
quality evaluation was run for this PR.


Final observed checks:

| Check | Result |
| --- | --- |
| `make test-place-research` | 590 JavaScript + 428 API/database + 95 standalone photo tests passed |
| Canonical worker/in-process, runtime, governed places, atomic policy and baseline | 75 passed |
| Focused boundary/trace/scorer group | 152 passed |
| Evaluation adapter and prompt publisher groups | 75 passed |
| Collector repair, historical context and model boundary group | 107 passed |
| 10,000-source checkpoint and story-game group | 20 passed |
| Wider SQL/progressive group | 109 passed; its one remaining capacity case passed in the separate group above |
| Default-suite collection | 7,284 collected; two browser E2E modules skipped without their opt-in URL |
| Syntax and diff checks | Python compilation and `git diff --check` passed |

The entire collected suite was not executed. Browser live E2E and live semantic
model quality were not run. No deterministic pass is reported as evidence that a
model understands a particular phrase.
