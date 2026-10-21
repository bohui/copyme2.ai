# Memoir audit: model prompts, deterministic tests, and language interpretation

What this repo does: Memoir turns a narrator’s conversation, photographs, and recordings into source-linked memories, places, and a memoir. The API and background workers propose content with models and use PostgreSQL to control ownership, revisions, privacy, and publication. This audit assumes concurrent conversations and background jobs, with the current development deployment and its fresh-install database baseline.

Audit date: **21 October 2026, Australia/Sydney**. The checkout started at `f1d6d6f` and advanced independently to `df76b11` (`sync langfuse`) during the audit. This report distinguishes the initial failures from the final state. No application code, prompt content, receipts, or database schema was changed by this audit.

## Direct answers

**Are deterministic tests and LLM evaluation mixed? Partly, in responsibility and claims.** The inspected ordinary tests generally use fixed proposals, fake providers, and mocked HTTP. A test of a mocked judge is a legitimate deterministic test of the judge adapter. The larger problem is that production code makes judgments about natural-language meaning with regex, tests preserve those judgments through collections of example phrases, and some deterministic evaluation scores are presented with names that imply model quality. I did not find evidence that the inspected default test paths routinely run live LLM judges.

**Should `QUESTION_DESCRIPTION` and `TRANSLATION_GROUNDING` be Langfuse-managed? Yes.** They are instructions sent to the model inside the structured response schema. Their location in Pydantic `Field(description=...)` does not make them merely internal documentation. Changing them changes the effective prompt without changing a Langfuse artifact version. The same problem exists beyond those two constants.

**Should interpretation move from expanding regex lists to models? Yes, where the job is understanding language.** Use the existing collector/extraction calls to propose intent, attribution, relationships, uncertainty, and source-bound date meaning. Keep deterministic code for schemas, exact source spans, ownership, revisions, limits, arithmetic on normalized values, idempotency, and transactions. A model proposal must not grant access, payment entitlements, publication rights, or broader consent.

## Scope and evidence

| Item | Observed scope |
| --- | --- |
| Python source inventory | 113 files under `apps/api`, 99 under `scripts`, 6 under `skills` |
| Python test inventory | 407 files including support modules; 3,400 named test-function definitions, before parametrization |
| Registered prompt artifacts | 81: 70 in `PROMPT_PATHS`, plus 11 skill-judge artifacts added by the publisher registry |
| Final local receipt checks | 81/81 content hashes match at `df76b11` |
| Python `re.*` call sites | 202 in API code, 144 in scripts, 63 in skill Python; this counts calls, not distinct patterns or defects |
| API files containing `re.*` calls | 32 |
| Executed selected tests | Eight test modules; results and commands below |
| Other inspected surfaces | Web/mobile/shared-client model boundaries, browser place/date interpretation, SQL privacy/date rules, prompt publication, evaluation runners, and direct provider probes |

The [machine-readable inventory](/Users/bohuihan/memoir/docs/audits/2026-10-21-llm-boundaries-inventory.json) contains every registered prompt’s path, numeric receipt version, recorded and actual hash, field-description locations, and regex counts by file. Counts are a search map, not a claim that every regex is inappropriate.

This was a repository-wide audit of the requested boundaries, with deeper tracing through the relevant execution paths. It was not a complete security, payments, or performance audit of every feature.

## What already works and should stay

- The [prompt loader](/Users/bohuihan/memoir/apps/api/prompt_artifact.py:16) rejects missing receipts and text/hash drift. The [publisher](/Users/bohuihan/memoir/scripts/publish_langfuse_prompts.py:64) publishes committed `main` content and reuses unchanged content. Keep that workflow.
- Most collector, extraction, profile, summary, composer, organiser, historical-search, game, speech-default, and judge templates already load versioned artifacts. This is an incomplete migration, not a missing prompt-management system.
- The [composition builder](/Users/bohuihan/memoir/apps/api/prompt_composition.py:32) resolves named shared artifacts and rejects malformed/nested references. Runtime and some experiments reuse it.
- [Source validation](/Users/bohuihan/memoir/apps/api/interview_questions.py:8) checks actual quotes and offsets. [Extraction validation](/Users/bohuihan/memoir/apps/api/memory_events.py:210) checks scoped identities, revisions, and source versions. Those are appropriate deterministic responsibilities.
- The [mocked judge test](/Users/bohuihan/memoir/tests/test_trajectory_evaluation.py:269) verifies request/response handling without evaluating a real model. Keep deterministic tests of this kind, regardless of whether their filenames contain “evaluation”.
- The [Issue 6 evaluator](/Users/bohuihan/memoir/scripts/issue6_semantic_evaluation.py:68) explicitly leaves factual entailment for human review. That distinction is useful and should be applied consistently.

## Must fix

### 1. Model instructions remain embedded in response-schema code — P1

Evidence: [interview plan descriptions](/Users/bohuihan/memoir/apps/api/interview_plan.py:53), [strategy descriptions](/Users/bohuihan/memoir/apps/api/interview_strategy.py:123), [question-evidence instructions](/Users/bohuihan/memoir/apps/api/interview_questions.py:55), [continuity descriptions](/Users/bohuihan/memoir/apps/api/lifetime_memory_continuity.py:36), and [prepared-question descriptions](/Users/bohuihan/memoir/apps/api/two_lane_memory.py:23).

- **What this is:** Behavioral policy is supplied through `QUESTION_DESCRIPTION`, `ACKNOWLEDGEMENT_DESCRIPTION`, `TRANSLATION_GROUNDING`, the long `TurnWorkPlan.mode` description, and additional schema descriptions. The collector sends that schema as `output_schema` through [the model boundary](/Users/bohuihan/memoir/apps/api/lifetime_memory_engine.py:389).
- **Problem:** Editing those Python strings changes interviewing, translation, privacy classification, and evidence instructions without publishing a new Langfuse prompt. Existing registry/hash tests enumerate known Markdown files and therefore do not detect this gap.
- **Fix:** Move behavioral prose into the appropriate existing managed interviewer/timeline artifacts; keep types, limits, required fields, and scoped enums in code. Remove behavioral descriptions from generated schemas, or explicitly version any retained model-facing descriptions with the prompt.
- **If we skip it:** A run’s published prompt version will describe only part of its actual instructions, and prompt reviews or experiments can miss the real behavior change.

`TRANSLATION_GROUNDING_ERROR` is normally an error message, but this error is also admitted into `repair_reason` and inserted into another model request. That model-facing repair guidance also needs versioned ownership; use stable error codes plus managed repair explanations rather than policy prose in Python exceptions.

### 2. Entire model-facing instruction paths bypass managed artifacts — P1

Evidence: [photo discovery](/Users/bohuihan/memoir/skills/memoir-place-photo-research/scripts/photo_research.py:1003), [judge rubric](/Users/bohuihan/memoir/apps/api/trajectory_evaluation.py:70), [judge override](/Users/bohuihan/memoir/apps/api/trajectory_evaluation.py:1363), and [speech overrides](/Users/bohuihan/memoir/apps/api/speech.py:27).

- **What this is:** Photo discovery constructs its entire search instruction in Python; judge policy also comes from `JUDGE_RUBRIC` and an arbitrary `instructions` override. Speech accepts raw delivery instructions from an API request or environment variable ahead of its managed defaults.
- **Problem:** The photo path is an actual optional application provider, called by [`_llm_web_search`](/Users/bohuihan/memoir/apps/api/place_photos.py:1096), not just an example script. These requests can change independently of every published template and receipt.
- **Fix:** Add managed photo-discovery and probe templates; move judge rubric text into managed judge artifacts; choose speech policy through managed names/versions. Treat any deliberately supported user-supplied transcription context or delivery request as request data with a clearly defined role, rather than silently treating it as versioned application policy.
- **If we skip it:** “All LLM prompts are managed by Langfuse” remains false even after moving the two named constants.

Additional unversioned probe instructions are at [connectivity probe](/Users/bohuihan/memoir/scripts/memoir_provider_connectivity_probe.py:65), [web-search probe](/Users/bohuihan/memoir/scripts/memoir_provider_web_search_probe.py:103), and [worker smoke probe](/Users/bohuihan/memoir/scripts/memoir_codex_worker_smoke_probe.py:39). Mock-only dummy strings in deterministic tests are not deployed prompts and do not need publication.

### 3. Regex is the final authority for whether privacy requests can be persisted — P1

Evidence: [schema filtering](/Users/bohuihan/memoir/apps/api/lifetime_memory_continuity.py:108), [literal parser](/Users/bohuihan/memoir/apps/api/lifetime_memory_continuity.py:154), [proposal rejection](/Users/bohuihan/memoir/apps/api/lifetime_memory_continuity.py:351), and the matching [SQL persistence restriction](/Users/bohuihan/memoir/supabase/migrations/202610180001_initial_schema.sql:7847).

- **What this is:** Only listed English/Chinese forms can become excluded topics, paused topics, or commitments. For privacy requests, this restriction exists in both Python and SQL.
- **Problem:** “I would rather keep the kitchen out of our conversations.” produces no literal policy rows; its schema excludes privacy kinds, and a correctly quoted model proposal is rejected. Adding “My mother said hello.” to “Do not discuss the kitchen.” removes an otherwise recognized exclusion because reported speech is detected across the entire message.
- **Fix:** Let a versioned model contract propose scoped control intent from current narrator evidence; retain exact spans, source role/version, bounded actions, and atomic policy writes. Make uncertain interpretation hold the affected action for clarification, and preserve explicit user controls as the direct authority for permissions or relaxing restrictions.
- **If we skip it:** The system can acknowledge a privacy preference conversationally while being unable to save that preference through the current policy path.

This needs a coordinated Python/SQL change. Changing the prompt alone cannot fix it. Under this repository’s rules, edit the existing [fresh-install baseline](/Users/bohuihan/memoir/supabase/migrations/202610180001_initial_schema.sql), rather than adding a migration file.

### 4. Topic and pause regex can constrain a model to the wrong interpretation — P1

Evidence: [`current_constraints`](/Users/bohuihan/memoir/apps/api/interview_strategy.py:176), [schema narrowing](/Users/bohuihan/memoir/apps/api/interview_strategy.py:116), [result rejection](/Users/bohuihan/memoir/apps/api/interview_strategy.py:212), and [pending-confirmation suppression](/Users/bohuihan/memoir/apps/api/two_lane_memory.py:96).

- **What this is:** A language classifier detects pauses, corrections, pacing, and topic changes before generation, then changes candidate availability and allowed reasons.
- **Problem:** “Please do not change the subject.” is classified as `user_redirect`. That false match can remove prepared candidates and reject a model’s otherwise valid interpretation; “I would like to stop asking questions for now.” has no recognized constraint.
- **Fix:** Use a structured intent proposal in the existing turn model output; validate consistency between the proposed intent, selected candidate, stop flag, and delivery action. Keep literal UI actions such as a Stop button deterministic and immediate.
- **If we skip it:** Every added negation, paraphrase, or reported-speech exception grows another brittle grammar and more fixtures without solving the general problem.

The second reproduction is a missed heuristic, not proof that the model will always ignore the stop request. The first is stronger: the host actively imposes the wrong constraint.

### 5. Translation and acknowledgement checks attempt semantic judgments through surface forms — P1

Evidence: [sibling-age regex](/Users/bohuihan/memoir/apps/api/interview_plan.py:59), [acknowledgement classifier](/Users/bohuihan/memoir/apps/api/interview_plan.py:201), [stream withholding](/Users/bohuihan/memoir/apps/api/lifetime_memory_engine.py:363), and [the associated unit cases](/Users/bohuihan/memoir/tests/test_interview_plan.py:49).

- **What this is:** The host tries to prove translation faithfulness and detect questions or invitations by matching English/Chinese vocabulary and punctuation.
- **Problem:** “My sister was born before I was.” rejects the age-correct term `姐姐`, while mentioning an older brother elsewhere allows an unsupported `妹妹` for a sister. “Tell me more about your father.” is accepted by the acknowledgement detector even though the instructions prohibit an invitation there.
- **Fix:** Put translation/acknowledgement policy in managed prompts and evaluate it semantically against the full authorized context. Keep the separate acknowledgement/question fields and deterministic rendering, but remove the claim that these regex establish factual faithfulness or conversational meaning.
- **If we skip it:** Valid replies can trigger repairs or withheld output, while invalid replies still pass; the examples added to unit tests give a misleading sense of completeness.

Reuse the current call where possible. An additional LLM validator on every streamed fragment would add cost and latency and would not create certainty.

### 6. Places and dates are reinterpreted in both the API and browser — P1

Evidence: [whole-message place veto](/Users/bohuihan/memoir/apps/api/place_journey.py:202), [place uncertainty grammar](/Users/bohuihan/memoir/apps/api/place_journey.py:263), [research period parser](/Users/bohuihan/memoir/apps/api/place_research.py:59), and [browser narration reconstruction](/Users/bohuihan/memoir/apps/web/client/memoir/places.mjs:86).

- **What this is:** After model extraction, Python filters places and reconstructs date meaning; the browser separately parses raw chat to override place period and life stage.
- **Problem:** “I lived in Sydney. I am not sure which town my uncle lived in.” discards the clear Sydney proposal. The API loses the 1980 research period in “I lived in Sydney in 1980 and did not own a car,” while the browser assigns period `1980` even to “I did not live in Sydney in 1980.”
- **Fix:** Extract per-place assertions, negation, uncertainty, temporal scope, and original evidence in the existing managed extraction call. Persist one normalized representation and have browser/photo/news code consume it without reparsing narration.
- **If we skip it:** The same saved conversation can produce contradictory workspace dates, missing research, or an incorrect visual search period depending on which layer interprets it.

## Should fix

### 7. Photo metadata parsing has grown into another language interpreter — P2

Evidence: [capture/uncertainty vocabulary](/Users/bohuihan/memoir/skills/memoir-place-photo-research/scripts/photo_research.py:1092), [clause-role state machine](/Users/bohuihan/memoir/skills/memoir-place-photo-research/scripts/photo_research.py:1105), [date reconciliation](/Users/bohuihan/memoir/skills/memoir-place-photo-research/scripts/photo_research.py:1206), and [the API’s other source parser](/Users/bohuihan/memoir/apps/api/place_photo_browser.py:157).

- **What this is:** Code distinguishes capture dates from publication/upload dates and tries to interpret qualifiers in source captions.
- **Problem:** “Chengde street photographed in 1983.” is accepted, but “Chengde street before the rain, photographed in 1983.” is rejected because `before` is treated as date uncertainty. That word refers to weather, not uncertainty about 1983.
- **Fix:** Parse explicit structured provider fields deterministically; use a managed model extraction contract for ambiguous prose captions, returning date role, uncertainty, and exact source evidence. Keep source fetching, URL checks, observed receipts, date bounds, and rights enforcement in code.
- **If we skip it:** New caption wording continues to require another special-case parser change, and legitimate source images disappear from results.

### 8. Runtime code rewrites published prompt prose — P2

Evidence: [timeline string replacement](/Users/bohuihan/memoir/apps/api/two_lane_memory.py:54) and [collector slicing at an English sentence](/Users/bohuihan/memoir/apps/api/lifetime_memory_runtime.py:302).

- **What this is:** One path replaces an exact sentence in a published template with new Python-owned instructions. Another cuts a composed prompt at the literal phrase `Return place_journeys`.
- **Problem:** Rewording or wrapping the source sentence can silently defeat the replacement, and renaming the slice marker raises `ValueError`. The effective instruction variant is partly specified outside the managed artifact.
- **Fix:** Make standalone and combined output instructions explicit managed components, and split continuity/place instructions into named artifacts. Compose by component identity and data variables rather than searching or rewriting human prose.
- **If we skip it:** An apparently editorial prompt update can break runtime assembly or leave contradictory output instructions.

### 9. A recorded contract alias does not identify the full prompt used by a generation — P2

Evidence: [`lifetime-v1` metadata](/Users/bohuihan/memoir/apps/api/lifetime_memory_runtime.py:289), [native metadata allowlist](/Users/bohuihan/memoir/apps/api/codex_agent.py:168), [composition receipts](/Users/bohuihan/memoir/apps/api/prompt_composition.py:41), and [direct-call tracing](/Users/bohuihan/memoir/apps/api/llm_tracing.py:107).

- **What this is:** Runtime persists protocol/contract aliases such as `lifetime-v1`, while the useful component-version and compiled-hash helper is mainly used by export/evaluation tooling. Some direct call traces contain endpoint/model metadata without the managed prompt identity.
- **Problem:** Two generations with different published guidance or schema descriptions can share the same recorded alias, without a per-call manifest explaining the difference. A repository commit can help reconstruction, but it is not the same as explicit Langfuse prompt linkage.
- **Fix:** Record managed names, exact versions/hashes, assembly variant, compiled static-instruction hash, and schema hash at each model boundary. Keep request-specific testimony separate; distinguish `contract_version` from prompt publication versions and link generations to the managed prompt where supported.
- **If we skip it:** Quality comparisons, repairs, and incident review can attribute a behavior change to the wrong prompt version.

This is a provenance requirement, not a request to upload private narration or require a remote Langfuse fetch on every request. The existing checked-in, verified prompt snapshots remain suitable runtime inputs.

### 10. A deterministic score claims more than it measures — P2

Evidence: [phrase checks](/Users/bohuihan/memoir/apps/api/trajectory_evaluation.py:1253), [default category scores](/Users/bohuihan/memoir/apps/api/trajectory_evaluation.py:1316), and [the checked-in phrase requirement](/Users/bohuihan/memoir/tests/evaluation/cases.json:52).

- **What this is:** `final_response_quality` averages completion and literal response-contract checks, defaulting to a passing value when no additional check applies.
- **Problem:** A completed response saying “Bananas are purple and memories are made of cheese.” receives `final_response_quality=1.0` with no response requirements. “It happened approximately 1976.” fails a requirement for the literal text “around 1976,” despite preserving the same uncertainty.
- **Fix:** Name these scores `completion_contract` and `literal_response_contract`, and mark unmeasured semantic quality as unavailable. Use managed LLM/human evaluation for factuality, uncertainty preservation, usefulness, and tone; keep literal checks only where exact text is an actual protocol requirement.
- **If we skip it:** Reports and dashboards can display full quality scores without quality having been assessed, and penalize valid paraphrases.

### 11. The default synthetic trajectory evaluator calls a retired runtime interface — P2

Evidence: [default callback](/Users/bohuihan/memoir/apps/api/evaluation_cases.py:243), [the current runtime requirement](/Users/bohuihan/memoir/apps/api/codex_runtime.py:263), [default CLI callback selection](/Users/bohuihan/memoir/scripts/run_langfuse_evaluation.py:63), and [outdated tests](/Users/bohuihan/memoir/tests/test_trajectory_evaluation.py:786).

- **What this is:** The synthetic evaluation callback and three selected tests invoke `CodexRuntime.turn` without the now-required canonical publication context.
- **Problem:** Calling the default synthetic callback fails before the fake worker with `ValueError: A canonical publication context is required`. After the receipt sync, three selected tests still fail for missing canonical contracts/context.
- **Fix:** Bind the deterministic replay to the current canonical orchestration/publication seam with a fixed model transport, and update its tests and documentation. Retire the old runner if another maintained replay already covers the same contract; do not weaken production admission to keep old fixtures alive.
- **If we skip it:** The documented offline evaluation path cannot supply the application evidence it advertises, even though its lower-level scorer tests pass.

### 12. Prompt and language fixtures blur the intended test boundary — P2

Evidence: [prompt keyword checks](/Users/bohuihan/memoir/tests/test_interview_strategy.py:22), [four copies of guidance checked by wording](/Users/bohuihan/memoir/tests/test_interview_plan.py:105), [negation phrase enumeration](/Users/bohuihan/memoir/tests/test_interview_strategy.py:157), and [default test selection](/Users/bohuihan/memoir/pytest.ini:1).

- **What this is:** Ordinary tests assert that particular words occur in prompts and preserve growing lists of linguistic exceptions. There is no explicit model-evaluation marker or global outbound-provider denial in the inspected top-level pytest configuration.
- **Problem:** Finding the word `untrusted` in a prompt does not show that a model follows its trust rule, and the current negation examples pass while “Please do not change the subject.” still fails semantically. The suite relies on each fixture to prevent provider access rather than enforcing the boundary centrally.
- **Fix:** Keep deterministic checks for artifact identity, substitutions, schema shape, request construction, replay behavior, and host invariants. Move language-quality expectations into a versioned evaluation dataset; make ordinary tests reject external provider dispatch and require a separate explicit live-evaluation entry point.
- **If we skip it:** More passing fixture examples can coexist with unchanged semantic failure modes, and future tests can accidentally inherit live-provider behavior.

I did not observe an accidental live call during this audit. Missing central enforcement is a prevention gap, not evidence that today’s selected tests secretly evaluated a model. Existing tests of deterministic evaluation infrastructure should remain ordinary tests.

### 13. An unused legacy stage parser is still maintained through tests — P2

Evidence: [legacy stage heuristics](/Users/bohuihan/memoir/apps/api/profile_intake.py:24), [`apply_explicit_story_stage`](/Users/bohuihan/memoir/apps/api/profile_intake.py:301), and [tests asserting its overrides](/Users/bohuihan/memoir/tests/test_profile_intake.py:57).

- **What this is:** The legacy profile-intake module contains a substantial Chinese/English subject, correction, and age grammar for overriding `midlife` classifications.
- **Problem:** A whole-tree name search found the stage-override entry point only in its definition and tests; the current [background profile path](/Users/bohuihan/memoir/apps/api/background_profile.py:63) uses a different contract. These tests preserve a semantic implementation that does not demonstrate current product behavior.
- **Fix:** Delete the unused stage-override entry point, its private parsing helpers, and tests that only serve it, after checking any supported external import contract. Keep shared constants and independently used validation/compatibility functions.
- **If we skip it:** Developers keep expanding a retired interpretation path and may mistake its passing tests for coverage of the active profile workflow.

## Verified examples

The following were executed locally against the real functions. They were synthetic inputs; no model or external provider was called.

| Input or action | Observed result | Meaning |
| --- | --- | --- |
| Privacy: `I would rather keep the kitchen out of our conversations.` | No literal rows; schema permits only `person` and `unresolved_reference`; an exact-span `excluded_topic` proposal is rejected | Model interpretation cannot repair the host’s vocabulary limit |
| Privacy: `Do not discuss the kitchen.` | One excluded-topic row | Baseline recognized form |
| Same request plus `My mother said hello.` | No rows | Unrelated reported speech suppresses the whole request |
| Intent: `Please do not change the subject.` | `{"override":"user_redirect"}` | Negation is inverted |
| Intent: `I would like to stop asking questions for now.` | `{}` | Phrase is not recognized by the pre-generation heuristic |
| Source: `My sister was born before I was.`; output uses `姐姐` | Rejected | Supported age comparison is missed |
| Source: `My older brother and my sister walked to school with me.`; output uses `妹妹` | Allowed by translation guard | One sibling’s age qualifier licenses another sibling incorrectly |
| Acknowledgement: `Tell me more about your father.` | Not rejected by question detector | An invitation passes the surface classifier |
| Place: clear Sydney residence plus uncertainty about an uncle’s town | Sydney proposal removed | Uncertainty scope spreads across independent assertions |
| API research: Sydney in 1980 plus `did not own a car` | Empty research period | Unrelated negation suppresses a definite date |
| Browser merge: `I did not live in Sydney in 1980.` | Place period becomes `1980` | Negated residence is interpreted positively |
| Caption: `Chengde street before the rain, photographed in 1983.` | No capture date | Non-temporal `before` is misclassified |
| Completed nonsensical response, without extra response requirements | `final_response_quality=1.0` | Quality was not measured |
| `approximately 1976` against a requirement for `around 1976` | Literal contract fails; quality becomes `0.5` | Text equality is used for a semantic expectation |
| Default `evaluation_cases.run_case` | Missing canonical publication context error | Synthetic runner uses an obsolete seam |

## Model-call and prompt-ownership inventory

This table covers the application model boundaries and the main evaluation/probe families located by repository search. The JSON inventory enumerates the managed artifacts individually.

| Model-call family | Assembly / dispatch | Managed source coverage | Remaining issue |
| --- | --- | --- | --- |
| Interactive collector and repair | `lifetime_memory_runtime` → `lifetime_memory_engine` → `CodexConnection.turn` | Collector, language, privacy, continuity, strategy, turn, and repair artifacts | Schema prose, repair explanations, prose slicing, incomplete call provenance |
| Timeline extraction and derived hints | `two_lane_memory.extraction_contract` / `lane_contract` → `run_bounded_lane` | Timeline instructions, grounding, place extraction, derived hints, optional strategy/attribution | Inline descriptions and exact-prose replacement |
| Profile extraction | `background_profile.profile_contract` → bounded lane | Memory-context skill instructions | Keep current source/target/quote validation; no need for legacy stage grammar |
| Summary generation | `lifetime_memory_summary.summary_contract` → bounded lane | Memory-context summary artifact | Record complete per-call pin metadata |
| Composer prepare/draft/review | `memoir_preview.composer_instructions` → bounded lane | Composer phase, editorial, narrative, batch, and bounded-context artifacts | Record complete per-call pin metadata; preserve source validation |
| Collection outline leaf/merge | `lifetime_memory_job_engine.job_contract` → `run_bounded_job` | Locale and phase-specific outline artifacts/components | Record complete per-call pin metadata |
| Historical public search | `historical_news_provider.discover` → Responses API | Managed discovery artifact with query substitution | Preserve public-query bounds; semantic filtering/source interpretation also uses keyword rules |
| Photo native web search | Skill helper `llm_search` → Responses API | **No managed source for the actual search template** | Complete inline prompt and unversioned temporal wording |
| Story game proposal | `story_game_runtime.propose_game` → Responses API | Managed game skill and proposal artifacts | Complete prompt trace linkage; retain edition/consent/publication fences |
| Speech synthesis | `speech_character` → speech provider | Managed locale/default delivery artifacts | Request/env overrides bypass version ownership |
| Speech transcription | `OpenAISpeechService.transcribe` | No fixed application instruction in this adapter; accepts optional request context | Define user context separately from application policy; do not publish private input as a template |
| Trajectory semantic judge | `OpenAICompatibleJudge` → chat completion | Managed system/rubric templates | Python rubric text and raw instruction override remain |
| Five-case and ten-skill judges | Semantic-judge runner / skill-evaluation adapters | Managed five-case, shared judge policy, and per-skill rubric artifacts | Keep quality separate from contract/execution evidence; retain explicit calibration status |
| Generic prompt experiment | `evaluate_langfuse_prompt.experiment_task` | Exact remote template version plus local shared-component pins | Useful prompt experiment; it explicitly does not reproduce full application schema/validation |
| Connectivity/search/worker probes | Three provider probe scripts | Inline strings | Publish fixed probe instructions under the evaluation namespace |
| Web/mobile/shared clients | No direct model-provider calls found in the searched source | API boundaries handle model requests | Browser still performs semantic reconstruction of place/date information |

## Recommended boundary

| Responsibility | Deterministic application/test code | Versioned model prompt and evaluation |
| --- | --- | --- |
| Request and result shape | Types, required properties, limits, enum membership | Explain each semantic task |
| Evidence | Verify exact quote, offsets, authorized source/version, scoped target | Decide what a passage means, who it refers to, and which assertion it supports |
| Intent | Apply validated state transitions and explicit UI controls | Interpret pause, redirect, correction, distress, and quoted speech |
| Dates and places | Calendar validity, arithmetic, coordinate/range bounds, identity lookup | Interpret uncertain/negated prose and assign a date to the right person/place/event |
| Privacy and consent | Authenticate; enforce policy; make atomic writes; block invalid/stale publication | Propose narrowly scoped restrictive controls; ask for clarification on ambiguous meaning |
| Permissions and money | Always authoritative deterministic checks | No authority to grant entitlements or expand consent |
| Output presentation | Render allowed fields; escape HTML; enforce limits | Produce faithful, useful prose and translation |
| Quality | Validate scorer transport and score schema using fixed fixtures | Assess factual entailment, usefulness, tone, translation, and uncertainty against a managed rubric |

For example, a model can propose a topic exclusion with a source quote and span. The host checks that it belongs to the authenticated current narration, that its action is permitted, and that its source/policy revision is current. A quote being real does not itself prove the interpretation; that semantic uncertainty must remain visible in the contract and in evaluations. Tightening a restriction and granting broader permission should have different authority requirements.

Do not create a separate LLM call for every removed regex. Add the required structured semantic fields to the current collector/extraction contracts, or reuse existing fields such as `selection_reason`. Introduce another call only where a separate workflow needs it, such as interpreting an inspected external caption.

## Fix order and completion criteria

1. **Establish an honest baseline.** Repair or retire the stale synthetic evaluation seam; label deterministic scores accurately. Record the clean receipt state and ensure deployment/startup checks refuse unsynchronized prompt artifacts without changing remote versions from feature branches.
2. **Finish prompt ownership.** Move schema policy, photo discovery, judge policy/overrides, model-facing repair explanations, and probe templates into the existing registry. Replace instruction-text speech overrides with managed selection where they represent application policy.
3. **Make assembly explicit and traceable.** Replace prose replacement/slicing with named managed components. Attach prompt pins, compiled static hash, schema hash, and assembly variant to model call evidence; keep contract versions separate.
4. **Remove semantic host grammars in coordinated slices.** Start with privacy/control intent, then place/date context, then translation/acknowledgement and source-caption interpretation. Change Python, SQL, API contracts, and browser consumers together where they share the responsibility.
5. **Restructure tests and evaluations.** Ordinary tests replay fixed structured proposals and check host behavior; semantic cases become evaluation data with managed judges and explicit live execution. Delete legacy-only interpretation paths and tests after usage checks.

Completion should mean:

- Every application-authored instruction in a real model request maps to an exact managed artifact version, including descriptions and repair/judge snippets if retained.
- Dynamic values such as source IDs, current candidate IDs, and narrator context remain data, with deterministic trust-boundary validation.
- Ordinary tests run without provider credentials and fail immediately if they attempt an external model request. Local database/browser integration remains allowed with controlled dependencies.
- A fixture replay can demonstrate ownership, privacy transitions, retries, source invalidation, exact evidence, and transactional behavior without claiming it measured model understanding.
- Live model acceptance is an explicit end-to-end evaluation run with frozen cases, prompt/schema/model provenance, separate contract and semantic results, calibrated judging, and visible unavailable/untested statuses.
- The concrete paraphrase, negation, multi-person, and mixed-clause examples above are retained as semantic regression cases. Exact expected response wording is used only for actual protocol requirements.
- Place/photo/news or localization implementation changes run [`make test-place-research`](/Users/bohuihan/memoir/Makefile:207), including its API-to-client replay. Database changes stay in the initial baseline until production deployment is announced.
- Prompt changes follow the [versioned workflow](/Users/bohuihan/memoir/README.md:382): Git review and merge to `main`, legitimate publication/sync, then receipt review and verification. Never fabricate a published version.

## Verification and the concurrent receipt fix

The first selected run at `f1d6d6f` observed **313 passed, 8 failed** in 2.79 seconds. Five failures came from mismatching receipts for `collector-plan` v2, `guidance` v2, and `strategy/selection` v4; the other three exercised retired runtime contracts. The checkout was clean before the audit, so those failures were present in the audited state.

While the audit was in progress, the shared checkout moved to `df76b11` (`sync langfuse`). The three receipt versions became v3, v3, and v5 respectively, and all 81 local hashes now match. This audit did not perform that sync. The initial receipt failures are **resolved observations**, not outstanding findings about the final checkout.

The same eight-module selection was rerun after that change: **318 passed, 3 failed** in 4.93 seconds. All three failures are in `test_trajectory_evaluation.py` and concern the missing canonical execution/publication contracts described in finding 11. The accompanying inventory records their exact test IDs. The command was:

```sh
LANGFUSE_TRACING_ENABLED=false python3 -m pytest -q --tb=short \
  tests/test_prompt_artifact.py tests/test_prompt_composition.py \
  tests/test_interview_plan.py tests/test_interview_strategy.py \
  tests/test_issue6_semantic_evaluation.py tests/test_llm_place_photos.py \
  tests/test_place_journey.py tests/test_trajectory_evaluation.py
```

Additional verification used direct Python calls to the real validators/scorers and Node calls to `mergePlaces` with the synthetic inputs listed above. No live model evaluation, remote publication, service restart, or database mutation was performed.

## Langfuse implementation guidance

The current official documentation supports versioning structured-output configuration together with a prompt and linking a generation to its prompt version. That makes schema prose part of prompt governance a feasible design choice, not a limitation imposed by Langfuse. The smaller change here is to move behavioral prose into the existing managed Markdown and keep structural schemas in code; versioned prompt config is an alternative if rich model-facing schema descriptions remain necessary. [Official Langfuse prompt-config documentation](https://github.com/langfuse/langfuse-docs/blob/main/content/docs/prompt-management/features/config.mdx).

This audit does not require replacing the existing pinned local artifact workflow with network retrieval on each request. It requires complete ownership of instructions and complete call provenance.

**Verdict:** Keep the deterministic trust boundaries and the current prompt-management foundation. Finish prompt ownership, repair evaluation reporting/replay, and replace semantic regex interpretation with evidence-bound model proposals in small coordinated changes.

**Lean:** Deleting unused profile-stage interpretation and replacing semantic grammars should remove code without adding a framework or dependency. A safe net line-count estimate needs the implementation diff; no invented savings number is claimed.

**Not checked:** The entire test suite, full live end-to-end conversations, remote Langfuse prompt contents or hosted evaluator state, provider visual/translation quality, deployed containers, and a complete security/payment/concurrency audit. SQL restrictions were inspected but were not executed against a database during this audit.
