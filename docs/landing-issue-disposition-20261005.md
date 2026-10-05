# Memoir landing and acceptance disposition

The user now requests landing after review, then five separate 50-round synthetic datasets on exact merged `main`. This supersedes the earlier pre-merge full-run ordering. Parent confirmation of the reviewed head and disposition remains the final merge step. Four `ready-for-agent` gap tickets were created as requested; original issues stay open. No PR was merged/retargeted and no branch setting changed.

**Keep Issues 2 and 6 open.** Neither has a literal acceptance-criteria section; the matrix maps all 35/56 User Stories and all 8/20 Testing Decisions. `PASS` means the deterministic contract passed at the exercised seam. `PARTIAL` means an implemented contract has additional unmet acceptance. Controlled-provider results do not establish live extraction, prose or judge quality. No skips/errors are counted as passes.

| Item | Current state | Landing/disposition |
| --- | --- | --- |
| PR11 | Draft integration; contains exact PR3/9/10 heads and PR8 main | Cloud review the new exact head, then parent approves landing this one candidate |
| PR3 | Open, main base; `28acda14f684aab6dd4dbbaf4fcc398e4d853b9b` | Already incorporated; after approved PR11 landing, close as incorporated with exact ancestry evidence |
| PR9 | Draft, stacked base; `84366778f50495d065e794a00f16184d16dc4216` | Already incorporated; do not separately merge the stacked branch |
| PR10 | Draft, stacked base; `90dee1f2be4f6a83fbc44e779f8d2e91106c6061` | Already incorporated; do not separately merge the stacked branch |
| Issue2 | Trajectory evaluation; managed/live acceptance incomplete | Keep open; G1/G3/G4 follow-ups carry specific gaps |
| Issue6 | Canonical/native contracts pass; live semantic acceptance incomplete | Keep open; G1/G2/G3 follow-ups carry specific gaps |
| Issue1 | Localization outside this disposition audit | Keep open; no closure inference from locale regression count |

Read-only GitHub rules API returned no applicable branch rules (`[]`); open PRs have no attached check runs or formal review decision. An empty check list is not a pass. Cloud review is external evidence and must cover the final published head. Current main remains `a4d8abf810eefa1ec36cc219710f8ac954bb52e9`.

## Evidence and its limits

The [native report](pr8-pr9-pr10-mac-validation.md) records 1,194 passes, four configured-provider skips, zero failures/errors on code `c1f5e296`. Its component counts overlap. New driver/budget checks pass separately (33 cases); they do not turn the earlier broad result into a new broad-suite result. [New receipts](test-evidence/canonical-readiness-20261005.json) retain exact command results/source hashes, including failed TDD attempts. No model, judge or photo-provider call was made.

Langfuse has fresh exact-ID API/database canary evidence after the approved local repair. Authenticated Chrome automation still reports zero windows despite the user signing in. Browser visibility is an unverified acceptance gap. Both renderer modes now pass with explicit flags and cached-asset hashes; final task ports are closed. One descendant-group probe was blocked by EPERM and is not claimed as verified.

## Tracked gaps ready for agents

- **G1 — Canonical five-case launcher and exact-main 250-round acceptance:** wire the tested UserStorage/runtime/Temporal callback into the evaluation command; five isolated owners/projects, original inputs, all checkpoints, full manifest and raw outcomes. Follow the approved budget and review/fix/retest loop on exact main.
- **G2 — Bilingual seven-skill/source-claim pilot and output acceptance:** run explicit/natural paths, positive/negative invocation cases, every life stage, four configured-provider follow-up cases, source-claim cN association/stripping and attributed/timing/null vetoes. Offline/native passes and diagnostic pilots do not close semantic quality.
- **G3 — Verified provider accounting and calibrated judge/comparisons:** implement an actual provider-boundary adapter that measures conservative input and enforces output caps across every model/tool/retry/background call; verify billing prices or gateway hard spend cap; configure only existing authorised judge settings, calibrate with named reviewer/date, and compare prior/current/no-skill/model variants on fixed cases. Worker request counts are not model usage.
- **G4 — Durable Langfuse browser/linkage/idempotence and retention:** verify exact canary records in the authenticated browser, durable duplicate-score replay, exact-main round/observation linkage and reviewed retention/minimization. Preserve historical corrupted scores and missing traces; recovery requires retained original ingestion data and a separate verified plan.

Created [G1 / #12](https://github.com/bohui/copyme2.ai/issues/12), [G2 / #13](https://github.com/bohui/copyme2.ai/issues/13), [G3 / #14](https://github.com/bohui/copyme2.ai/issues/14), and [G4 / #15](https://github.com/bohui/copyme2.ai/issues/15), each labelled `ready-for-agent`. No incomplete original is marked complete. The parent confirms disposition and the final reviewed landing head. Exact agent-ready ticket bodies accompany this matrix.

## Required ordering

1. Cloud rereview the new driver/budget code and evidence; confirm final head, deterministic checks and this disposition.
2. Land PR11 once, preserving integrated commit ancestry; record actual main SHA/tree. Close incorporated PRs explicitly; keep incomplete issues open and link the precise follow-ups.
3. Finish a reviewed isolated canonical launcher and verified actual-provider accounting/judge setup. Obtain a numerical request/token/spend approval using verified prices or a gateway hard cap before live calls.
4. On exact main, run the bounded bilingual pilot and four configured-provider follow-up cases, then five distinct 50-round datasets. Record invocation/output grades separately, browser state and durable Langfuse readback; retain unavailable/fail outcomes.
5. Fix each observed bug through the agreed public seam, cloud review the fix, land, and rerun affected cases plus justified regression checks. Close an original issue only when every required acceptance row passes.

## Requirement-by-requirement matrix

### Issue 2: 35 user stories

| # | Requirement | Status | Evidence | Remaining gap / finding |
| --- | --- | --- | --- | --- |
| 1 | As a developer, I want one local evaluation command, so that I can run a skill-enabled Memoir case without starting a second agent runtime. | PARTIAL | E06, E01 | G1: wire the canonical callback into the five-case command |
| 2 | As a developer, I want the evaluator to invoke the same API and `codex-worker` boundary used by the product, so that evaluation results predict product behavior. | PARTIAL | E06, E01 | G1: full canonical command and five isolated 50-round runs remain |
| 3 | As a developer, I want every case to use an isolated synthetic storyteller and project, so that evaluation cannot read or modify customer data. | PASS | E01, E05 | Isolated native fixtures; each reused project is refused |
| 4 | As a developer, I want a case to declare its user message, prior memories, profile, entitlement, language, enabled skills, and expected outcome, so that a run is reproducible. | PASS | E05 | Declarative synthetic context contract |
| 5 | As a developer, I want the runner to pin the application revision, skill manifest, model, provider configuration, and evaluator version, so that two experiment runs can be compared fairly. | PARTIAL | E05, E26 | G1/G3: exact merged-main model/provider/evaluator manifest and calibrated rubric need run evidence |
| 6 | As a skill author, I want to test a skill when it is explicitly enabled, so that instruction-following failures are separated from discovery failures. | PARTIAL | E06 | G2: real explicit skill loading/adherence remains live evidence |
| 7 | As a skill author, I want to test ordinary requests with the normal skill catalogue, so that inappropriate activation and missed activation are visible. | PARTIAL | E06 | G2: real natural-selection behavior remains live evidence |
| 8 | As a skill author, I want the run to record which skill version and reference materials were loaded, so that loading failures are distinguishable from adherence failures. | PARTIAL | E07, E20 | G2: actual loaded references/versions for all seven skills need live receipts |
| 9 | As a developer, I want the trajectory to show the context available immediately before each action, so that a judge does not penalize or excuse a decision using information the agent did not have. | PASS | E07 | Observable pre-action context contract |
| 10 | As a developer, I want each model action to include its selected tool, normalized arguments, and action category, so that tool choice can be checked independently of the final prose. | PASS | E09 | Normalized tool names/arguments/categories |
| 11 | As a developer, I want each tool result, error, timeout, and retry recorded in order, so that recovery and repetition can be evaluated from evidence. | PASS | E07, E10 | Protocol ordering, errors and bounded retry contract |
| 12 | As a developer, I want application-side validation, entitlement checks, marker parsing, persistence, task publication, and artifact commits recorded as trajectory steps, so that a successful reply cannot conceal an invalid state change. | PASS | E11, E01 | Application validation/state and native canonical outcome |
| 13 | As a privacy reviewer, I want private reasoning excluded from the trajectory, so that evaluation records contain observable inputs and actions without claiming access to chain-of-thought. | PASS | E08 | Private reasoning omitted |
| 14 | As a developer, I want the final visible response, stop reason, terminal status, and resulting application state captured, so that answer quality and task success can be scored separately. | PASS | E07, E01 | Terminal response/state and ordered trajectory |
| 15 | As a developer, I want deterministic checks for tool permissions, schema validity, marker grounding, entitlement gates, source ownership, retry limits, and saved-state revisions, so that objective failures do not depend on judge variability. | PASS | E11, E25, E54 | Deterministic permissions/state/source ownership |
| 16 | As a reviewer, I want a trajectory-quality score for the whole run and targeted scores for failed steps, so that a run can be triaged without treating every defect as an answer-quality problem. | PARTIAL | E15, E13 | G3: managed run/step judging is not configured or calibrated |
| 17 | As a reviewer, I want separate scores for skill selection, skill adherence, execution quality, state correctness, and final response quality, so that the team can fix the right layer. | PARTIAL | E27, E15 | G3: scoring contracts pass; semantic live scores still unavailable |
| 18 | As a reviewer, I want judges to assess tool appropriateness, evidence use, recovery, unnecessary repetition, and stopping behavior, so that trajectory quality is broader than exact-sequence matching. | PARTIAL | E13, E10 | G3: reviewed semantic judges remain unavailable |
| 19 | As a developer, I want equivalent valid paths to receive credit, so that evaluation does not require one arbitrary tool sequence when the resulting behavior is safe and grounded. | PARTIAL | E10, E11 | G3: outcome checks allow recovery; semantic credit for equivalent valid paths needs judge calibration |
| 20 | As a developer, I want the evaluator to distinguish a sensible retry after a transient error from repeating a successful action, so that recovery is measured accurately. | PASS | E10 | Transient retry versus duplicate success |
| 21 | As a developer, I want to compare a new skill revision with a previous revision and a no-skill baseline on the same cases, so that improvements and regressions are visible. | PARTIAL | E17 | G3: same-case prior/current/no-skill comparison not executed with a calibrated judge |
| 22 | As a developer, I want to compare model and provider configurations while keeping the case and rubric fixed, so that quality and latency trade-offs are attributable. | PARTIAL | E17 | G3: controlled model/provider comparison not executed |
| 23 | As a developer, I want local experiment results to remain useful when managed judging is asynchronous, so that runtime behavior does not depend on a Langfuse worker being available during the turn. | PASS | E18 | Missing/asynchronous judge separated from local deterministic evidence |
| 24 | As an operator, I want runtime timeouts, cancellation, maximum iterations, and permissions enforced before evaluation, so that a judge cannot become a loop-prevention mechanism. | PASS | E19, E11 | Runtime timeout/cancellation precede judging |
| 25 | As a privacy reviewer, I want sensitive storyteller content redacted or minimized before it is sent to Langfuse, so that evaluation retention follows the application's data policy. | PARTIAL | E12, E08 | G4: minimization passes; retention policy and signed-in UI receipt not established |
| 26 | As a developer, I want each Langfuse score write to be idempotent, so that retries do not create duplicate or conflicting evaluation results. | PARTIAL | E16 | G4: idempotent mock identifiers pass; durable duplicate-write replay not verified |
| 27 | As a reviewer, I want a trace or run identifier linked to the local case result, so that a failure can be inspected in Langfuse without searching by free text. | PARTIAL | E16, E27 | G4: fresh exact-ID canary API/DB pass; canonical run-to-browser links remain |
| 28 | As a developer, I want deterministic artifact and persisted-state checks to inspect the real output, so that a plausible final answer cannot substitute for a missing file or incorrect workspace revision. | PASS | E11, E01 | Real saved state/draft inspected through public storage |
| 29 | As a skill author, I want explicit cases for current-day versus historical place-photo searches, uncertain dates, unrelated requests, and ambiguous place cues, so that the place-photo and place-journey contracts remain grounded. | PASS | E22, E23 | Offline current/historical/uncertain/unrelated place-photo and journey contracts |
| 30 | As a Family feature developer, I want cases for paid, unpaid, pending, and revoked entitlements, so that premium skill activation and persisted Family context remain server-controlled. | PASS | E24, E52 | Server-owned paid/unpaid/pending/revoked display contracts |
| 31 | As a collection developer, I want cases for collection review, organiser handoff, source ownership, and deterministic task results, so that the background workflow is evaluated beyond the organiser's proposal. | PASS | E25 | Collection approval/source/task boundary regression suite |
| 32 | As a developer, I want a failed case to preserve enough local evidence to reproduce it without uploading unnecessary content, so that debugging remains practical and privacy-aware. | PASS | E18, E07 | Local partial-trajectory/evidence preservation |
| 33 | As a maintainer, I want repository checks to run directly on the host or in ordinary CI, so that removing the dedicated harness does not remove regression coverage. | PASS | E06, E01 | Native host regression suite; no retired harness service dependency |
| 34 | As a maintainer, I want `install_skill` to refresh every runtime that caches skill text, so that an evaluation never silently uses an older skill bundle. | PARTIAL | E20, E21 | G2: file replacement and rebuild recipe pass; actual cache refresh in both running runtimes needs receipt |
| 35 | As a reviewer, I want the accepted rubric and dataset version recorded with every run, so that score changes caused by rubric edits are not mistaken for agent improvements. | PARTIAL | E14, E26 | G3: rubric/dataset versions exist; human reviewer/date and accepted calibration absent |

### Issue 2: testing decisions

| # | Requirement | Status | Evidence | Remaining gap / finding |
| --- | --- | --- | --- | --- |
| 1 | Test externally observable behavior at the highest available seam: a complete evaluation case through the normal application/worker contract. Avoid tests that merely assert an internal event list was assembled in one implementation method. | PASS | E01, E06 | Normal runtime/private-worker public outcome; canonical fixture added |
| 2 | Unit-test trajectory normalization with protocol fixtures containing tool calls, successful results, errors, retries, interleaved events, cancellation, and terminal failures. Verify ordering, redaction, and omission of private reasoning. | PASS | E07, E08, E09 | Protocol ordering/redaction/private-reasoning regression suite |
| 3 | Contract-test deterministic evaluators with valid and invalid marker payloads, unauthorized tools, malformed arguments, wrong-project sources, repeated successful calls, bounded retries, missing artifacts, and stale revisions. | PASS | E11, E25, E54, E10 | Deterministic evaluator rejection/retry/state contracts |
| 4 | Integration-test the local runner with a fake model/provider and the real application/worker boundary. Assert that a case returns a final outcome, ordered trajectory, metadata, and state assertions without requiring a live Langfuse judge. | PASS | E01, E06 | Synthetic provider with real application/worker/state outcome |
| 5 | Test Langfuse publishing with a mock client for trace/observation linkage, redacted payloads, run-level and step-level score targets, and idempotent score identifiers. Keep network-dependent experiment tests opt-in and clearly marked. | PASS | E16, E15, E12 | Mock Langfuse linkage/score identifiers/minimization |
| 6 | Exercise skill fixtures for explicit loading and natural selection separately. Include the present-day place-photo default, explicit historical period, uncertain source date, unrelated request, place-journey grounding, and Family entitlement cases. | PARTIAL | E22, E23, E24 | G2: offline fixtures pass; real explicit/natural seven-skill paths need receipts |
| 7 | Preserve existing runtime and application regression coverage for Codex connection behavior, worker isolation, marker extraction, Family gating, collection review, organiser handoff, task ownership, and deterministic task execution. Add no test that depends on the removed `codex-harness` service. | PASS | E25, E19, E53 | Existing runtime/worker/collection regressions retained |
| 8 | Verify the operational change with Compose configuration validation, focused Makefile/skill-install tests, the Codex worker tests, and the full local repository checks before enabling Langfuse scores as release gates. | PARTIAL | E20, E01 | Native/build checks pass; Langfuse release score gates remain disabled pending G3/G4 |

### Issue 6: 56 user stories

| # | Requirement | Status | Evidence | Remaining gap / finding |
| --- | --- | --- | --- | --- |
| 1 | As a storyteller, I want every accepted message processed for life events in the background, so that my timeline grows without a separate recording step. | PARTIAL | E01, E29 | G2: canonical contract passes; all-stage live extraction quality remains |
| 2 | As a storyteller, I want conversational acknowledgements to produce no invented events, so that my timeline contains memories I actually described. | PARTIAL | E29 | G2: empty controlled extraction passes; model acknowledgements/vetoes need live pilot |
| 3 | As a storyteller, I want several events from one reply saved separately, so that different stages and years are represented accurately. | PASS | E28 | Distinct canonical identities from one reply |
| 4 | As a storyteller, I want several replies about one event linked together, so that extra details enrich the same story. | PASS | E28 | Multiple original sources enrich one stable identity |
| 5 | As a storyteller, I want new details to reach an event first discussed much earlier, so that I can revisit memories naturally. | PASS | E31 | Old-event evidence changes its passage and preserves unrelated bytes |
| 6 | As a storyteller, I want distinct events with similar descriptions kept separate, so that recurring experiences are not merged accidentally. | PASS | E32 | Similar events and long periods are not merged implicitly |
| 7 | As a storyteller, I want uncertain event matches left unresolved, so that the assistant does not attach my words to the wrong memory. | PASS | E33 | Ambiguous matches remain unresolved |
| 8 | As a storyteller, I want events assigned to supported life stages, so that I can navigate my story by period of life. | PARTIAL | E34, E35 | G2: supported-stage validators/editing pass; live all-stage assignment pending |
| 9 | As a storyteller, I want each event assigned its supported year or date range, so that capture dates do not become story dates. | PARTIAL | E35, E36, E37 | G2: timing validators pass; live date extraction pending |
| 10 | As a storyteller, I want approximate expressions such as around 1970 preserved, so that my memoir reflects my uncertainty. | PASS | E36, E35 | Approximate/original expressions retained; unsupported numeric dates refused |
| 11 | As a storyteller, I want an undated memory retained, so that missing timing does not discard an otherwise clear event. | PASS | E32, E35 | Unknown/undated evidence retained without fabricated timing |
| 12 | As a storyteller, I want a year estimate linked to its evidence, so that I can understand and correct its basis. | PASS | E36 | Age estimates retain original evidence and birth basis |
| 13 | As a storyteller, I want long life periods retained as single records with ranges, so that my work or residence history is not fragmented into invented yearly events. | PASS | E32 | Long periods retain supported ranges as records |
| 14 | As a storyteller, I want to correct a previously saved event's life stage, so that its placement matches my recollection. | PASS | E34, E45 | Explicit stage edit preserves event identity/revision |
| 15 | As a storyteller, I want to correct a previously saved event's year, so that both the timeline and writing reflect the correction. | PASS | E34, E45 | Explicit year edit invalidates affected groups |
| 16 | As a storyteller, I want my explicit tag corrections retained during later extraction, so that the assistant does not silently undo them. | PASS | E34 | Corrected tags fence later model estimates |
| 17 | As a storyteller, I want an event's identity retained when its tags change, so that its source and chapter links remain intact. | PASS | E34, E38 | Stable identity and downstream dependencies |
| 18 | As a storyteller, I want conflicting accounts to retain their attribution, so that the system does not silently choose a factual winner. | PASS | E37 | Attributed conflicting dates remain unresolved |
| 19 | As a storyteller, I want access to the original evidence behind an event, so that I can review what supports the timeline and prose. | PASS | E38, E28 | Original source references retained and readable |
| 20 | As a storyteller, I want event records to survive closing the browser and returning later, so that my work is recoverable across sessions. | PASS | E66 | Tag/coverage readback survives browser reload in controlled product fixture |
| 21 | As a storyteller, I want conversation to continue while extraction and writing run, so that background work does not interrupt storytelling. | PASS | E39 | Authenticated chat continues during bounded preparations |
| 22 | As a storyteller, I want the first supported private draft after five completed rounds, so that I can see progress early. | PASS | E01, E40 | Native default five-round checkpoint saved |
| 23 | As a storyteller, I want later five-round checkpoints to update relevant writing, so that the draft grows as I provide more memories. | PASS | E31, E61, E40 | Later checkpoints and catch-up use eligible evidence |
| 24 | As a storyteller, I want failed replies and technical retries excluded from the round count, so that milestones reflect actual conversation. | PASS | E41, E65 | Failed replies/technical retry do not add completed rounds |
| 25 | As a storyteller, I want editing an earlier message to update affected writing without counting as a new round, so that correcting a memory does not change my allowance. | PASS | E42, E41 | Source edits reconcile without increasing usage |
| 26 | As a storyteller, I want unchanged passages preserved exactly, so that new memories do not unexpectedly rewrite earlier writing. | PASS | E43, E31 | Unchanged passage bytes/revisions retained |
| 27 | As a storyteller, I want deleted or withdrawn sources removed from eligible derived content, so that earlier drafts do not continue exposing that material. | PASS | E44 | Changed/withdrawn evidence invalidates eligible derived output and fences late output |
| 28 | As a storyteller, I want an event moved between stage/year groups to update both affected groups, so that it is neither duplicated nor left behind. | PASS | E45 | Both former/current grouping invalidated without duplicate identity |
| 29 | As a storyteller, I want a checkpoint to include extraction through its stated round, so that its coverage label is accurate. | PASS | E40, E61 | Checkpoint waits for required extraction and captures stated coverage |
| 30 | As a storyteller, I want the latest validated draft available while a newer version runs, so that I can review saved progress immediately. | PASS | E46 | Latest eligible draft remains available during ordinary updates |
| 31 | As a storyteller, I want to see the round covered by my saved draft, so that I understand how current it is. | PASS | E46, E66 | Saved coverage displayed and retained on reload |
| 32 | As a storyteller, I want recoverable failures to show a clear retry state, so that quiet background processing does not conceal a stalled update. | PASS | E47, E48 | Terminal failure exposes explicit retry and stops endless polling |
| 33 | As a storyteller, I want human-edited or approved writing protected, so that automatic enrichment becomes a reviewable proposal. | PASS | E49 | Protected bytes retained; revision-bound enrichment proposal saved |
| 34 | As a storyteller, I want chapters grouped around meaningful narrative transitions, so that event indexing does not turn my memoir into disconnected fragments. | PARTIAL | E38, E68 | G2/G3: structural chapter contract passes; meaningful narrative transitions need reviewed live semantics |
| 35 | As a storyteller, I want source language and memoir output language kept distinct, so that indexing does not alter my original testimony. | PASS | E51, E50 | Original testimony language kept distinct from output locale |
| 36 | As a storyteller, I want Chinese and English memories processed through the same event contract, so that language choice does not change persistence behavior. | PARTIAL | E50, E01 | G2: Chinese voice/canonical contracts pass; bilingual full live workload pending |
| 37 | As a storyteller, I want background draft checkpoints kept separate from payment and formal-book readiness, so that routine updates do not initiate a purchase or publication. | PASS | E52, E40 | Private cadence separate from allowance/payment/publication |
| 38 | As a Family legacy storyteller, I want explicit relationship mentions to trigger family-tree updates, so that my tree grows when relevant information appears. | PASS | E53 | Relationship mentions dispatch tree updates through actual story worker |
| 39 | As a Family legacy storyteller, I want relevant corrections to an established relative processed, so that the saved tree remains accurate without repeating the relationship introduction. | PASS | E53 | Existing relative correction dispatches one tree pass |
| 40 | As a storyteller, I want ordinary messages without relationship information to leave the family tree unchanged, so that unrelated conversation does not cause unnecessary tree work. | PASS | E53 | Unrelated narration leaves tree unchanged |
| 41 | As a storyteller, I want my events isolated from other users and projects, so that private memories cannot cross ownership boundaries. | PASS | E54 | Cross-owner/project event and reference boundaries |
| 42 | As a returning guest storyteller, I want an authorised account transfer to preserve event identities and source links, so that signing in does not duplicate my story or milestones. | PASS | E55 | Authorised guest transfer preserves IDs/dependencies/retry state |
| 43 | As an editor, I want timeline and composer to use the same canonical event IDs, so that a correction has one target throughout the project. | PASS | E38 | Timeline and composer use canonical event IDs without re-extraction |
| 44 | As an editor, I want stale writes rejected with a recoverable conflict, so that concurrent extraction or editing cannot overwrite newer decisions. | PASS | E56, E34 | Expected-revision conflicts are recoverable and fence stale writes |
| 45 | As an operator, I want background intents to survive disconnects and restarts, so that saved narrator messages are eventually processed without asking the storyteller to repeat them. | PASS | E30, E62 | Durable input/outbox and native Temporal recovery |
| 46 | As an operator, I want retries to reuse completed work, so that a failed render or review does not repeat every successful partition task. | PASS | E57 | Successful partition preparation reused after failed provider task |
| 47 | As an operator, I want partition preparation to run with bounded concurrency, so that independent work can finish faster without unlimited provider requests. | PASS | E57, E39 | Bounded preparation concurrency and ongoing chat |
| 48 | As an operator, I want obsolete output rejected after a relevant correction or revocation, so that a late job cannot restore outdated or inaccessible content. | PASS | E58, E44 | Corrections/revocation invalidate and fence obsolete output |
| 49 | As a maintainer, I want existing event and manuscript references preserved during migration, so that the shared index can replace duplicate indexes without losing prior work. | PASS | E59, E60 | Legacy IDs/provenance/privacy and manuscript references preserved on replay |
| 50 | As a maintainer, I want acceptance tests driven through the story workflow, so that refactoring internal storage does not require rewriting tests for every helper function. | PASS | E01, E53, E65 | Existing UserStorage/runtime/private-worker acceptance seam |
| 51 | As a storyteller, I want later milestones to wait while an earlier background run is active, so that competing jobs cannot overwrite my event structure or draft. | PASS | E61 | One active invocation and coalesced later milestones |
| 52 | As a storyteller, I want the next background run to include all accumulated inputs, so that a slow run can catch up across ten or fifteen conversation rounds. | PASS | E61 | Catch-up resolves latest eligible accumulated inputs at claim time |
| 53 | As a storyteller, I want inputs from a failed background attempt kept pending, so that an unsuccessful run does not silently lose part of my story. | PASS | E62, E64 | Failed ranges stay pending and successful cursor does not advance |
| 54 | As a storyteller, I want my durably accepted message retained as evidence even when an assistant reply fails, so that a delivery error does not discard the memory I supplied. | PASS | E65, E30 | Accepted original survives failed assistant delivery without a completed round |
| 55 | As an operator, I want a stalled background run to reach a configured timeout, so that queued work can recover without waiting forever. | PASS | E63 | Configured deadline bounds held native provider and exposes retry |
| 56 | As an operator, I want output from a timed-out worker rejected after a replacement run starts, so that a late response cannot overwrite newer saved state. | PASS | E64, E62 | Late timed-out worker cannot overwrite replacement work |

### Issue 6: testing decisions

| # | Requirement | Status | Evidence | Remaining gap / finding |
| --- | --- | --- | --- | --- |
| 1 | The primary acceptance seam is the existing authenticated story workflow: submit narrator turns, drive the background worker to an observable state, edit/read canonical events, and read the saved private draft. Prefer this seam over isolated tests of prompts, private helpers, table layout, or function-call order. Use controlled responses only at the external model/provider boundary; exercise application validation, persistence, dispatch, revision handling, and rendering together. | PASS | E01, E53, E65 | Authenticated story runtime, worker, native storage and Temporal outcome |
| 2 | A good test asserts what the storyteller or authorised caller can observe: event identity and tags, evidence links, accurate coverage, unchanged output content/revisions, corrected output, access denial, or a recoverable processing state. Tests remain valid when internal batching, queue adapters, or module arrangement change. | PASS | E34, E46, E54 | Public identity/evidence/coverage/access observations |
| 3 | Cover one reply describing several events in different stages/years and several replies describing one event. Read timeline and draft dependencies to prove both use the same canonical event ID, including a late new detail about a much older event. | PASS | E28, E31, E38 | Multiple/old evidence and shared canonical IDs |
| 4 | Cover explicit, approximate, age-based, ranged, conflicting, and unknown dates; unknown stage; undated events; and periods spanning years. Check uncertainty and original expressions rather than expecting fabricated numeric dates. Exercise both supported conversation languages and transcribed voice using the same persistence contract. | PASS | E35, E36, E37, E32, E50 | Supported/uncertain/conflicting/unknown ranges and transcribed Chinese |
| 5 | Cover stage/year edits without source-text changes. Assert stable event ID, a changed revision, invalidation of former/current grouping, updated timeline and affected draft, and preservation of unrelated output. Delay an earlier extraction response and prove that it cannot restore a tag the user corrected later. | PASS | E34, E45 | Corrected stable IDs/group invalidation/fenced late estimates |
| 6 | Cover successful empty extraction, failed extraction, out-of-order completion, disconnect, restart, and replay. A milestone must remain pending while a required extraction gap exists, then compose against a snapshot covering the stated round once the gap settles. | PASS | E29, E62, E40 | Empty/failure/restart/replay and settled extraction coverage |
| 7 | Cover checkpoints before five rounds, at five and ten rounds, and under a non-default cadence. Duplicate inputs, failed replies, source edits, and background jobs must not increase completed-round usage. An unchanged checkpoint advances processing state without new generated output or duplicate provider work. | PASS | E41, E67, E40 | Before/at checkpoints, configured cadence, retry/usage independence |
| 8 | Hold a background run active while milestones at ten, fifteen, and twenty arrive. Assert that the lane still has one active invocation, then finish it and verify one catch-up run consumes the latest eligible range rather than three obsolete milestone packets. Include extra inputs arriving between milestones and prove that the worker resolves its snapshot at claim time. Perform this through the existing worker boundary for both skill lanes. | PASS | E61 | Both lanes held through later milestones and latest catch-up |
| 9 | Fail or time out an attempt covering six through ten after saving through five, then provide inputs through twenty. Assert that the next eligible run covers six through twenty, including the failed range, and that no claim or failed attempt advances a successful cursor. Reuse applicable successful checkpoints and verify that sources and already committed events are not duplicated. | PASS | E62, E64 | Failed 6–10 range retained through 20 and completed work reused |
| 10 | Advance a controlled clock past the configured run deadline while the original worker remains stalled. Verify that ownership is fenced, pending work becomes eligible without another user turn, and a late completion cannot save over the replacement run. Cover lease expiry after a process crash as the equivalent recovery boundary; test durable outcomes rather than sleep durations or scheduler internals. | PASS | E64, E63, E62 | Controlled deadline/lease recovery and obsolete completion fencing |
| 11 | Persist an accepted narrator input and fail assistant delivery. Read back its source/event evidence, prove it is included in later authorised catch-up processing, and verify that completed-round usage remains unchanged. Retry the same client input and assert that source identity and evidence links are reused. | PASS | E65, E30 | Accepted evidence survives delivery failure and replay |
| 12 | Cover conversation overlap that refers only to unchanged material. It must not trigger rewriting. Cover new evidence for an existing older event outside the overlap window and assert that its dependent section updates. These are regressions for the dirty-content selection gaps reproduced during the review. | PASS | E31, E43 | Unchanged overlap preserves bytes; older dirty evidence updates dependencies |
| 13 | Cover edits, source-link removal, deletion, and access withdrawal. Rebuild from surviving evidence and refuse late output that depends on removed or inaccessible sources. Verify that a permitted previous draft remains available during an ordinary update while an ineligible one is withheld. | PASS | E44, E58, E46 | Removal/revocation and eligible prior-draft visibility |
| 14 | Cover independent dirty partitions with controlled delayed responses. Demonstrate bounded concurrent preparation and continuing chat, then fail one task and prove that already successful tasks are reused on retry. Verify that concurrent runs cannot overwrite a newer manuscript revision. | PASS | E57, E39, E56 | Bounded concurrent preparation, failed-task reuse and revision safety |
| 15 | Cover exact unchanged-content preservation, coherent chapter assembly, the existing word ceiling, failed evidence review, and protected text. Unchanged sections retain content and revisions; a protected affected chapter receives a proposal rather than silent replacement. A failed candidate never becomes the ready draft. | PARTIAL | E68, E49, E43 | G2/G3: structural/ceiling/review/protection contracts pass; coherent narrative quality needs reviewed live evidence |
| 16 | Add focused real-PostgreSQL integration checks for the shared event service and migration boundary: user/project isolation, expected-revision conflicts, atomic change/outbox recording, many-to-many references, migration replay, and preservation of legacy IDs, provenance, and privacy. Extend the existing disposable PostgreSQL migration harness rather than adding a production test endpoint or new storage subsystem. | PASS | E54, E56, E59, E28 | Native PostgreSQL isolation/change/replay/reference contracts |
| 17 | Use the existing browser workspace seam for the small presentation contract: event tag editing, reload persistence, saved-draft coverage/updating status, and premium timeline/family-tree visibility. Do not duplicate every worker recovery scenario in browser tests. | PASS | E66, E52 | Controlled workspace editing/reload/coverage/premium display |
| 18 | Family-tree acceptance scenarios cover a relationship mention, a relevant correction, and unrelated narration. Preserve server-owned entitlement checks and prove that internal event indexing for a non-Family storyteller does not grant premium tree/timeline display access. | PASS | E53, E24, E52 | Mention/correction/unrelated and server-owned entitlement |
| 19 | Migration and account-transfer scenarios preserve shared identity and manuscript references, retain unresolved legacy matches, and replay without extra rounds or milestones. Cross-project references and unauthorised event edits are rejected. | PASS | E59, E55, E33, E54 | Preserved migration/transfer IDs/unresolved matches and rejected cross-scope edits |
| 20 | Prior art includes the existing authenticated agent-turn and family-context tests, private-draft milestone/recovery tests, outbox broker tests, preview persistence/review tests, response-stage tests, disposable PostgreSQL timeline migration tests, and workspace browser tests. Reuse their public boundaries and fixtures; add new seams only where the required behavior cannot be observed through them. | PASS | E01, E38 | Existing public boundaries/native fixtures reused |

## Test references

All test names/lines were resolved from the actual source, rather than inferred from filenames. Baseline references passed in the retained whole native suite; the new canonical/budget references passed in the separate focused receipt.

- **E01**: [test_authenticated_rounds_extract_original_evidence_and_save_checkpoint_via_temporal](../tests/test_canonical_evaluation.py#L81)
- **E02**: [test_unverified_live_provider_cannot_be_dispatched_or_labeled_as_acceptance](../tests/test_canonical_evaluation.py#L55)
- **E03**: [test_worker_request_cap_covers_shared_clients_before_dispatch](../tests/test_evaluation_budget.py#L7)
- **E04**: [test_inflight_output_reservations_prevent_concurrent_overspending](../tests/test_evaluation_budget.py#L100)
- **E05**: [test_cases_have_reproducible_context_metadata](../tests/test_evaluation_cases.py#L16)
- **E06**: [test_checked_in_cases_pass_through_the_runtime_boundary](../tests/test_evaluation_cases.py#L29)
- **E07**: [test_recorder_adds_pre_action_context_normalized_actions_and_reports_overflow](../tests/test_trajectory_evaluation.py#L44)
- **E08**: [test_recorder_keeps_observable_results_and_omits_private_fields](../tests/test_trajectory_evaluation.py#L24)
- **E09**: [test_protocol_tool_events_normalize_tool_name_and_arguments](../tests/test_trajectory_evaluation.py#L117)
- **E10**: [test_evaluator_credits_a_bounded_retry_but_not_a_duplicate_success](../tests/test_trajectory_evaluation.py#L188)
- **E11**: [test_deterministic_evaluators_check_order_budget_and_state](../tests/test_trajectory_evaluation.py#L222)
- **E12**: [test_provider_payload_minimizes_storyteller_text_and_identifiers](../tests/test_trajectory_evaluation.py#L161)
- **E13**: [test_openai_compatible_judge_uses_template_and_records_safe_usage](../tests/test_trajectory_evaluation.py#L269)
- **E14**: [test_judge_calibration_requires_explicit_human_review](../tests/test_trajectory_evaluation.py#L307)
- **E15**: [test_langfuse_publisher_creates_step_observations_and_targets_step_scores](../tests/test_trajectory_evaluation.py#L453)
- **E16**: [test_runner_publishes_trace_and_idempotent_scores_to_langfuse_double](../tests/test_trajectory_evaluation.py#L598)
- **E17**: [test_runner_can_add_a_semantic_judge_and_compare_variants](../tests/test_trajectory_evaluation.py#L638)
- **E18**: [test_unavailable_judge_is_separate_from_deterministic_acceptance_evidence](../tests/test_trajectory_evaluation.py#L662)
- **E19**: [test_worker_turn_timeout_cancels_execution](../tests/test_codex_worker.py#L267)
- **E20**: [test_install_skill_replaces_one_skill_and_cleans_archive](../tests/test_install_codex_skill.py#L7)
- **E21**: [test_skill_install_rebuilds_the_api_and_codex_worker_without_a_harness](../tests/test_runtime_configuration.py#L46)
- **E22**: [test_omitted_period_finds_recent_photos_without_inheriting_history](../tests/test_llm_place_photos.py#L201)
- **E23**: [test_explicit_place_uncertainty_blocks_mapping_even_when_a_city_is_named](../tests/test_place_journey.py#L191)
- **E24**: [test_family_feature_requires_paid_family_entitlement_and_configured_price](../tests/test_family_context.py#L158)
- **E25**: [test_organiser_validates_sources_before_publishing](../tests/test_collection_routes.py#L110)
- **E26**: [test_checked_in_five_case_fixture_is_exactly_250_rounds_and_covers_the_contract](../tests/test_memoir_five_case_evaluator.py#L27)
- **E27**: [test_langfuse_round_scores_keep_skill_invocation_and_output_grades_separate](../tests/test_memoir_five_case_evaluator.py#L121)
- **E28**: [test_one_reply_has_distinct_events_and_later_reply_enriches_the_same_identity](../tests/test_shared_memory_events_postgres.py#L112)
- **E29**: [test_empty_extraction_advances_only_its_committed_input](../tests/test_shared_memory_events_postgres.py#L171)
- **E30**: [test_durable_narrator_acceptance_survives_missing_reply_and_replay](../tests/test_shared_memory_events_postgres.py#L140)
- **E31**: [test_new_evidence_for_an_old_event_changes_its_passage_and_preserves_unrelated_bytes](../tests/test_shared_memory_events_postgres.py#L711)
- **E32**: [test_similar_events_ambiguous_matches_and_long_periods_share_originals_without_merging](../tests/test_shared_memory_events_postgres.py#L1567)
- **E33**: [test_empty_candidates_are_unambiguous_for_new_and_existing_canonical_events](../tests/test_shared_memory_events_postgres.py#L90)
- **E34**: [test_explicit_tag_correction_preserves_identity_and_fences_later_model_estimate](../tests/test_shared_memory_events_postgres.py#L181)
- **E35**: [test_unsupported_numeric_dates_are_rejected_at_the_public_persistence_boundary](../tests/test_shared_memory_events_postgres.py#L888)
- **E36**: [test_supported_age_estimates_retain_original_language_expression_and_birth_basis](../tests/test_shared_memory_events_postgres.py#L1189)
- **E37**: [test_conflicting_attributed_dates_remain_unresolved_until_an_explicit_author_correction](../tests/test_shared_memory_events_postgres.py#L1544)
- **E38**: [test_existing_composer_worker_uses_shared_event_ids_and_originals_without_reextracting](../tests/test_shared_memory_events_postgres.py#L392)
- **E39**: [test_authenticated_chat_completes_while_independent_partition_preparations_are_held](../tests/test_shared_memory_events_postgres.py#L696)
- **E40**: [test_composer_checkpoint_waits_for_extraction_and_coalesces_at_claim_time](../tests/test_shared_memory_events_postgres.py#L321)
- **E41**: [test_assistant_only_reply_does_not_count_and_edits_do_not_increment](../tests/test_private_rounds_postgres.py#L62)
- **E42**: [test_existing_conversation_memory_edit_and_delete_update_canonical_evidence](../tests/test_shared_memory_events_postgres.py#L1299)
- **E43**: [test_genuine_storyline_enrichment_preserves_unrelated_passages_exactly](../tests/test_shared_memory_events_postgres.py#L540)
- **E44**: [test_source_changes_immediately_hide_dependent_drafts_and_reject_late_output](../tests/test_shared_memory_events_postgres.py#L627)
- **E45**: [test_tag_correction_invalidates_old_and_new_groups_without_changing_rounds](../tests/test_shared_memory_events_postgres.py#L647)
- **E46**: [test_latest_validated_draft_is_available_with_coverage_while_update_is_running](../tests/test_shared_memory_events_postgres.py#L366)
- **E47**: [test_terminal_extraction_failure_stops_draft_polling_until_the_author_retries](../tests/test_shared_memory_events_postgres.py#L1440)
- **E48**: [test_terminal_composer_failure_exposes_a_retry_instead_of_perpetual_updating](../tests/test_shared_memory_events_postgres.py#L1459)
- **E49**: [test_protected_draft_keeps_its_bytes_and_saves_enrichment_as_a_revision_bound_proposal](../tests/test_shared_memory_events_postgres.py#L1130)
- **E50**: [test_authenticated_voice_turn_retains_original_chinese_and_failed_reply_does_not_count](../tests/test_shared_memory_events_postgres.py#L994)
- **E51**: [test_active_composer_keeps_frozen_milestone_and_locale_while_later_targets_arrive](../tests/test_shared_memory_events_postgres.py#L799)
- **E52**: [test_authenticated_saved_draft_returns_shared_coverage_and_keeps_premium_display_gated](../tests/test_shared_memory_events_postgres.py#L784)
- **E53**: [test_story_workspace_only_dispatches_relationship_tree_and_never_duplicate_timeline](../tests/test_shared_memory_events_postgres.py#L824)
- **E54**: [test_event_person_and_chronology_references_cannot_cross_project_scope](../tests/test_shared_memory_events_postgres.py#L949)
- **E55**: [test_capability_transfer_preserves_canonical_ids_draft_dependencies_and_retry_state](../tests/test_shared_memory_events_postgres.py#L1106)
- **E56**: [test_stale_event_edits_recognize_native_postgrest_conflicts_without_misclassifying_internal_failures](../tests/test_shared_memory_events_postgres.py#L753)
- **E57**: [test_bounded_partition_preparation_reuses_successes_after_provider_failure](../tests/test_shared_memory_events_postgres.py#L662)
- **E58**: [test_a_changed_access_policy_refuses_an_older_frozen_composer_result](../tests/test_shared_memory_events_postgres.py#L1608)
- **E59**: [test_legacy_migration_preserves_ids_original_evidence_and_private_flags_on_replay](../tests/test_shared_memory_events_postgres.py#L1051)
- **E60**: [test_saved_legacy_composer_cache_is_imported_with_stable_event_and_section_references](../tests/test_shared_memory_events_postgres.py#L1201)
- **E61**: [test_real_worker_and_temporal_coalesce_busy_lane_to_latest_available_inputs](../tests/test_memoir_lanes_temporal.py#L22)
- **E62**: [test_real_temporal_worker_interruption_recovers_failed_range_without_new_turn](../tests/test_memoir_lanes_temporal.py#L143)
- **E63**: [test_configured_deadline_stops_hung_provider_and_exposes_bounded_retry](../tests/test_memoir_lanes_temporal.py#L231)
- **E64**: [test_failed_and_timed_out_timeline_ranges_remain_pending_and_late_worker_is_fenced](../tests/test_shared_memory_events_postgres.py#L258)
- **E65**: [test_story_workflow_retains_original_testimony_when_provider_delivery_fails](../tests/test_shared_memory_events_postgres.py#L205)
- **E66**: [test_saved_coverage_and_timeline_tag_edit_survive_browser_reload](../tests/test_shared_memory_browser.py#L252)
- **E67**: [test_nondefault_private_cadence_does_not_change_the_independent_round_allowance](../tests/test_shared_memory_events_postgres.py#L1587)
- **E68**: [test_an_unreviewed_or_oversized_canonical_candidate_never_becomes_a_ready_saved_draft](../tests/test_shared_memory_events_postgres.py#L436)
