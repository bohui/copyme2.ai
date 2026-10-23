# Active skill optimization campaign

Original campaign branch: `optimise-all-skills`; PR117 is now merged. The
post-merge live baseline is main `527fc73`; the checkout moved to
`optimise-all-skills-2` during verification and that existing continuation
branch retains the review report. Original baseline:
`d5dd21407bdf29ba35ef2686db4063ccba108420`.

Each Lane B skill gets its own execution/prompt analysis, bounded live baseline, concrete proposal, approved implementation and quality comparison. The user changed the interviewer scope to review only. No service activation or feature-branch prompt publication is included.

Post-merge update: the separately requested background-question handoff was
reviewed live after publishing its two v2 prompt receipts on main (`527fc73`).
All 93 prompt pins passed the remote check. [The fresh handoff review](lane-b-question-priorities-live-20261023.md)
fails full acceptance: 13/16 low-route cases saved and 10/16 passed the frozen
behavior/semantic gates. The configured pooled route enforces max effort; the
existing dedicated low route was tested only in isolation. No shared route or
running service was changed. Further contract/priority/privacy corrections are
proposed, not implemented; all earlier Lane B quality blockers remain open.

## Interviewer review

The current reply-v2 path already has a tool-free direct Responses request, a stable developer prefix, changing current narration last, host-owned metadata and Lane B extraction. Its compiled reply instruction is 1,986 characters; ordinary privacy review is 993 characters. The normal foreground total is 2,979 characters across two requests, before schemas and narration. Catalog size does not equal transmitted prompt size.

Privacy-review v4, optional opening v1 and repair-codes v5 now have valid published receipts. All 93 repository prompt pins passed the remote check on this baseline. The parallel/revisable flow from PR113 is present but its runtime flag remains off by default. It replaces only the current bubble and waits for reviewed final saving.

The previous live acceptance remains incomplete: correction-after-stop failures, slow privacy/repair cases and absent deployed-worker/browser-paint timing were recorded before the newer privacy/repair prompts. The 325 merged regression checks establish controlled behavior, not live semantic acceptance of the latest combined flow. A fresh focused review run on this baseline passed 78 reply, transport, compatibility and revision checks. Its first sandbox-denied launch and verified cleanup follow-up are retained. No interviewer code or prompt changes are proposed in this campaign.

A fresh interviewer run was already starting when the user redirected work. It was stopped by signalling its verified owned process. Nine calls are retained with four completed English turns and a cancelled fifth; this interrupted cohort is not a new acceptance comparison. Its disposable database and process allocations are cleaned; an outer registration-prefix cleanup failure and verified follow-up are retained.

## Lane B inventory

| Skill | Production execution | Round status |
| --- | --- | --- |
| memoir-author-timeline | model; accepted_source | Approved coordinate fix implemented; four-case comparison passed, broader completion gate remains open |
| memoir-place-journey | embedded; place_evidence | Reviewed within timeline: same model call, separate geographic contract; no standalone call to remove |
| memoir-memory-context | model; periodic | Approved direct profile/summary transport implemented; live model time reduced, full quality gate remains open |
| memoir-composer | model; periodic | Approved direct transport implemented and measured: 33–64% faster checkpoint saves; full quality fails, held-out coverage incomplete; selected-outline profiling pending |
| memoir-historical-news-research | provider; place_selection | Fresh bilingual live baseline:31–36s,0 verified clues; strict safety holds, usefulness unresolved; no application change |
| memoir-place-photo-research | provider; place_selection | Pending |
| memoir-place-groups | deterministic; place_change | Pending |
| memoir-story-game | model; game_button | Pending |

Family-tree generation is marked unwired by the production registry and remains excluded from the active-round count. Place grouping is deterministic and must not gain an LLM call merely for profiling.

## First Lane B round: author timeline

The current two-lane extraction contract contains 16,570 instruction characters plus a 10,712-character schema in the inspected English attribution/strategy/reply-v2 configuration. The general Codex app-server may add more context; that overhead must be measured on the wire. Source windows are bounded at 2,304 characters, with at most eight candidate events.

| Step / source | Work, inputs and output | Lane / dependency |
| --- | --- | --- |
| 1. Source acceptance and SQL outbox | Durable original/version and pending timeline work; A classifies extract versus reply-only. | A handoff; B does not delay the visible reply. |
| 2. `memory_event_worker.py` broker and SQL lane claim | One owned token, source/event/policy revisions, bounded snapshot and coalesced catch-up. | B; authoritative admission. |
| 3. `lifetime_memory_composer.py:_execute_lifetime_lane` | Due profile work can precede extraction; policy-incomplete and pending A decisions yield/defer. | B; profile is a separate skill dependency. |
| 4. `_extract` | Read the authoritative whole source for validation; build one source-window packet with exact originals, candidate events, preferences and attribution. Reply-only work skips the model. | B; no fabricated context. |
| 5. `build_bounded_lane_input` / `send_bounded_lane_request` | Rebuild typed fence, validate packet and total token budget; guard actual API-to-worker body admission. | B; no caller-supplied model instructions. |
| 6. `run_bounded_lane` | Revalidate, compile host-owned contract/schema, create a fresh governed home, initialize app-server/thread and invoke a schema-bound turn. | B; model-stage critical path. |
| 7. `_extract` validators | Validate events, restored Unicode offsets, places, prepared questions, continuity, attribution and strategy. Retry at most three times with fixed rejection codes and identical evidence. | B; output remains a proposal. |
| 8. SQL page commit | Atomically check token/digest/revisions, save events and derived hints, advance source coverage. | B; no coverage advance on failure. |
| 9. Checkpoint / summary / next consumers | Selective summary and profile work have their own prompts; prepared hints feed later A turns and canonical events feed composer. | B; extraction timing alone is not full checkpoint completion. |

### Prompt inventory

| Managed component | Purpose / condition | Source chars / rendered chars | Published pin |
| --- | --- | ---: | --- |
| `memoir/skills/memoir-author-timeline/continuity` | Descriptive continuity proposals in reply-v2; privacy controls remain separately governed. | 987 / 987 | v1, `e4daebd5db07` |
| `memoir/skills/memoir-author-timeline/attribution` | Attribute originals, dispositions and event/place links when attribution context exists. | 1253 / 1253 | v1, `cc01a7e1ad07` |
| `memoir/skills/memoir-author-timeline/contract` | Shared canonical-event identity, revision and source rules. | 2387 / 2387 | v1, `faabc0d8bb70` |
| `memoir/skills/memoir-author-timeline/derived-hints` | Bounded prepared questions and place hints for future turns. | 1193 / 1193 | v2, `099e4117d961` |
| `memoir/skills/memoir-author-timeline/extract` | Compatibility extraction when two lanes are off. | 310 / 8672 | v3, `9a9adf7bd0fc` |
| `memoir/skills/memoir-author-timeline/extract-with-hints` | Active two-lane extraction template plus canonical events/hints schema. | 342 / 8704 | v2, `38ad20878043` |
| `memoir/skills/memoir-author-timeline/instructions` | Timeline semantic and operational contract referenced by extraction templates. | 3426 / 3426 | v3, `c79a9bf333ef` |
| `memoir/skills/memoir-author-timeline/shared/grounding` | Shared exact-source, uncertainty and evidence grounding rules. | 2632 / 2632 | v1, `66bedf7ad003` |
| `memoir/skills/memoir-author-timeline/window` | Relative-window evidence and fixed retry feedback, carried in the request payload. | 903 / 903 | v1, `42cc8858f050` |
| `memoir/skills/memoir-place-journey/extraction` | Coarse place extraction embedded in the same timeline pass. | 2959 / 2959 | v3, `d2a4b04a177f` |
| `memoir/skills/memoir-interviewer/strategy-proposal` | Propose the next strategy from current narration, only when strategy is enabled. | 519 / 519 | v1, `aa6553e3c0e8` |
| `memoir/shared/bounded-context/en-AU` | English memoir locale and shared bounded-source policy. | 93 / 954 | v2, `c19926c3affa` |
| `memoir/shared/bounded-context/zh-CN` | Chinese memoir locale and shared bounded-source policy. | 93 / 954 | v2, `b44dae81524a` |
| `memoir/shared/bounded-context/policy` | Shared bounded-context privacy and original-evidence rules. | 884 / 884 | v1, `d92070acba1a` |
| `memoir/shared/place-conflicts` | Conditional resolved place-conflict evidence guidance. | 239 / 239 | v1, `8cffba4dd91a` |
| `memoir/skills/memoir-memory-context/summary` | Selective derived summary during checkpoint maintenance, owned by memory context. | 1558 / 1558 | v1, `01e01f507ce1` |

Exact hashes, full contracts and later live request bodies reside under `var/optimise-all-skills-20261022/02-author-timeline/`. The first model baseline uses actual native Codex 0.155.1 and real disposable SQL, with controlled A intake and API-to-worker transport. It does not establish deployed 0.156.1 worker performance or Temporal completion.

### Live diagnostic baseline

The frozen four-case cohort used the canonical extraction and semantic validators, real disposable SQL admission and commit, native Codex 0.155.1, the existing `memoir-luna-low` alias and requested low effort. Foreground intake and the API-to-worker HTTP seam were controlled fixtures. It is an extraction-phase baseline, not a deployed-worker, complete checkpoint or browser latency result. Each case starts with independent saved SQL state; later/resumed and long-window cases remain for confirmation.

Host access to the configured gateway failed. The successful cohort used a bounded task-owned container-exec relay to localhost inside that same healthy gateway, without modifying/restarting services. Both gateway duration and relay/application overhead are recorded. SSE was buffered, so its first-byte marker is not user-visible text.

| Scenario | Gateway durations per attempt | Extraction through SQL save/failure | Controlled intake through terminal state | Attempts | Observed result |
| --- | --- | ---: | ---: | ---: | --- |
| English childhood violin / 1978 / Hobart | 15.53 s | 17.26 s | 18.49 s | 1 | Saved; supported stage/year and exact evidence retained. |
| Chinese childhood violin / 1978 / Chengdu | 14.67 s | 15.82 s | 17.44 s | 1 | Saved; supported stage/year and exact Chinese evidence retained. |
| English bookshop / 1988–1992 / Perth | 17.31, 17.69, 22.04 s | 59.53 s | 60.46 s | 3 | Failed: all three place-research quotes had mismatched numeric spans. No page commit. |
| Chinese bookshop / 1988–1992 / Perth | 15.64, 18.35, 15.95 s | 53.33 s | 54.29 s | 3 | Saved on third attempt, retaining the event period but returning no research window. |

Three of four cases saved and satisfy the frozen timeline/source rubric; the round does not pass. The Chinese research omission is an additional downstream limitation, not a newly invented passing criterion. The median extraction-to-terminal duration across all four cases, including the failure, is 35.30 s. There is one sample per scenario, insufficient for tail percentiles. These background timings do not establish the foreground five/ten-second target.

Evidence: `var/optimise-all-skills-20261022/02-author-timeline/baseline-r7-live.json` retains exact inputs, provider requests/outputs, schema, compiled instructions, usage, validators' retry inputs, SQL commits and saved events. The corresponding check receipt verifies removal of both owned allocation roots. Earlier calibration/connection runs remain alongside it: 18 total provider-bound attempts, nine model completions and nine connection failures; two earlier harness failures dispatched zero model calls. A separate earlier English model completion took 17.22 s and is not pooled into this cohort. No paid judge calls were made.

The captured native request contains the 16,570-character domain instructions, 3,957 characters of framework messages, 1,874 characters of tool schemas and the changing bounded source packet. The tools include user input, image viewing and web search; extraction does not need them. A direct tool-free transport remains a second hypothesis, but retrying three entire generations is the larger demonstrated cost.

### Offline failure replay and downstream dependency

A zero-call diagnostic replayed all eight captured outputs through the unchanged canonical `_extract` path. Worker transport and publication admission were fixtures, so this replay proves validator behavior only. Editing only research coordinates cleared two of five rejected outputs; its initial expectation that all five would clear failed, and that failed check is retained in `coordinate-counterfactual.json` and its check receipt. The other outputs exposed bad prepared-question coordinates and one quote copied from the assistant rather than the admitted narrator source.

A second input-edit diagnostic changed only research/prepared-question coordinates whose unchanged quotes occur once in the admitted source. Seven of eight captured outputs then validated, including both date-range cases' first attempts. The assistant-only fabricated quote remained rejected. Existing valid null-spanned prepared questions were also resolved, matching today's normal behavior. Evidence: `derived-coordinate-counterfactual.json`, harness `replay-derived.py`, and the matching successful isolated-check/cleanup receipt. These are counterfactual edits to copies of captured model output, not implemented optimization, live candidate latency or SQL-save acceptance.

The original research-only proposal is superseded by the combined derived-evidence proposal below. Approval of the narrower proposal would not authorize the added prepared-question change.

The accepted research window is not disposable formatting. `AgentStorage.research_places` loads its owning active source; `place_research.research_places` verifies its exact original quote and projects a public search period/year. `story_routes.context_readiness` uses that projection for the derived workspace. `agent_routes.place_photos` supplies it to photo research and schedules selected-place historical news. Missing research produces an empty period; it must not be silently dropped as a latency shortcut. Prepared questions separately feed later interviewer turns, so their source grounding must remain strict.

### Approved change set: derived-evidence coordinate resolution in Lane B

| Change and affected code | Measured cost / expected gain | Retained quality contract | Validation and rollback |
| --- | --- | --- | --- |
| Let the existing place-research validator receive the host-owned source window through Pydantic validation context, supplied only by `two_lane_memory.derived_hints`. Resolve derived prepared-question coordinates in that same B-only path. Retain field/type/list/date validation; preserve already-correct explicit spans; resolve an incorrect numeric span only when its unchanged quote occurs exactly once in that admitted source. Revalidate the resolved absolute span. A repeated quote requires already-correct coordinates. Files: `apps/api/place_journey.py`, `apps/api/two_lane_memory.py`, focused regression tests. | Both date-range first attempts validate in the combined input-edit replay. Avoiding the extra two calls could save roughly 34–40 seconds on these diagnostic cases. This is an estimate, not measured candidate performance; ordinary cases should have no material latency change. Research-only repair would not resolve the Chinese case. | Keep the same model, effort, prompts, output schema, transport, retry ceiling, policy/owner/source fences and SQL commits. Reject missing required fields, wrong types, extra fields, impossible dates, fabricated/ambiguous quotes and over-limit lists. Never discard a proposal to make it validate. Existing optional/null question spans retain their current contract. Continuity/privacy controls and foreground question validation receive no repair or change. | Replay the captured first-attempt outputs through the actual candidate validator; compare the same four live cases; add later/resumed and nonzero-window held-outs. Cover wrong explicit coordinates, duplicate quotes with valid/invalid coordinates, Unicode, missing required fields, bad types, oversized arrays and stale-policy commits. Retain the assistant-quote rejection. Run focused timeline/SQL checks and `make test-place-research`. Roll back these two localized code changes if quality or completion regresses. |

There is no new background deferral: this work is already in Lane B. The next consumers need the same validated events, attribution, places/research windows and prepared questions. Existing durable retry and commit ownership remain responsible for eventual state.

The user approved the combined research/prepared-question change on 23 October 2026. It is implemented in the two modules named above. Runtime configuration, managed prompts, output schema, model route and transport remain unchanged. The compiled instruction text and schema match the pre-change snapshot exactly. Managed prompt changes, transport replacement and the remaining Lane B rounds remain separate decisions.

Concurrent local edits appeared in `apps/api/story_game_runtime.py` and `tests/test_story_game_runtime.py` during this investigation. They are preserved and have not been staged or included in the timeline change. The measured timeline modules matched their baseline hashes at the pre-change check; candidate evidence records the approved changed hashes separately.

## Implemented result — 23 October 2026

The model still supplies its proposal. After strict field/date validation, Lane B resolves an incorrectly counted research/question span only from its unchanged, unique original quote. Correct explicit coordinates retain the chosen occurrence. Missing required research fields, invalid types/dates, fabricated quotes, ambiguous references and oversized lists still reject. Foreground question evidence and continuity/privacy control validation keep their previous behavior.

### Matched live comparison

Each arm used the same frozen four scenarios, `memoir-luna-low` route, requested low effort, compiled domain instructions and schema. The gateway reported `gpt-5.6-luna` with low effort. There is one sample per case; these are diagnostic measurements rather than a statistically established speedup. Native Codex, the buffered container relay and controlled intake/worker seam are the same as baseline. Shared app services were not restarted or activated.

| Scenario | Before: extraction through SQL save/failure | After: extraction through SQL save | Attempts before → after | Quality/state review |
| --- | ---: | ---: | ---: | --- |
| English childhood / 1978 | 17.26 s | 22.56 s | 1 → 1 | Supported event, stage, year and exact evidence saved in both. Candidate terminal time was 30.7% slower; gateway generation itself was 14.80 s versus 15.53 s. |
| Chinese childhood / 1978 | 15.82 s | 15.80 s | 1 → 1 | Supported event, childhood stage, year and Chinese original saved in both. |
| English bookshop / 1988–1992 | 59.53 s, **failed** | 17.96 s, **saved** | 3 → 1 | Candidate retained the period, current-original references, research window and grounded questions. The baseline number is time to failure, not valid-response latency. |
| Chinese bookshop / 1988–1992 | 53.33 s | 23.71 s | 3 → 1 | Candidate retained the period and research window, which the baseline's eventual successful reply omitted. Valid saved-result latency fell 55.6%. |

The median extraction-to-terminal time across all four rows fell from 35.30 s to 20.26 s (42.6%), including the baseline failure. Main-cohort model calls fell from eight to four, and saved cases increased from three of four to four of four. All four candidate results pass the frozen semantic/source rubric on assistant review; this is not independent human review. The slower ordinary English result is retained: its task-relay wall time was 21.47 s for 14.80 s of gateway work while other required checks ran. No ordinary-case speedup is established, and the foreground five/ten-second goal was not measured.

Full synthetic inputs, model outputs, saved state, raw-report hashes, runtime hashes, usage and check receipts are preserved in [the committed evidence](evidence/lane-b-derived-coordinates-20261023.json). The ignored raw transcripts remain under the round directory. Across calibration, baseline, candidate and confirmation runs, there were 29 provider-bound attempts: 20 model completions and nine retained connection failures. Two initial intake-fixture failures made zero provider calls. No model judges were called.

### Confirmation and remaining failure

| Gate | Observed evidence | Status |
| --- | --- | --- |
| Main four-case semantic fidelity and SQL saving | Four exact-source candidate results saved on first attempt; date/stage/place/identity checks retained. | Pass for this diagnostic cohort. |
| Existing saved state | English held-out sequence loaded a saved childhood swim event before accepting a later bus-driving period. The old event stayed byte-for-byte unchanged; both extraction roots completed. Profile proposals were controlled fixtures. | Pass within the recorded scope. |
| Nonzero source window | A separately frozen unique-padding Chinese case completed two real SQL windows, including offset 1792. Its bookshop event cites absolute source span 2583–2617 with the supported 1995–1999 interval. That later model output had no derived research/question proposal, so live repair of those optional fields at a nonzero offset is not demonstrated; focused tests cover them. | Event-boundary saving passes; that narrower live repair observation remains unavailable. |
| Repeated-placeholder source | The original Chinese held-out case failed after three completed generations with ambiguous attribution references. The unchanged attribution validator rejects the same captured proposals; their research/question arrays are empty. No source or rejected proposal was dropped to force completion. The added unique-padding case does **not** replace this failure. | Completion fails; strict rejection passes. |
| Full deployed worker / Temporal / browser | Native 0.155.1 extraction and real SQL, with explicitly controlled dependencies. No deployed 0.156.1 worker or browser run. | Unverified. |

The approved coordinate change passes its focused contract and main comparison. Overall author-timeline acceptance remains **incomplete**, because the repeated-source completion failure and unobserved deployment boundary remain open. Other wired skill rounds are still pending; this is not completion of the all-skills goal or issue #53.

### Regression checks

- 320 focused span, extraction, place, foreground-question, lane ownership and SQL persistence checks passed, including the initial 101-check group. The pre-change run reproduced three failures; those failures and all cleanup receipts are retained.
- Unedited captured-output replay: seven of eight proposals validate with the candidate, including both date-range first attempts. The assistant-only fabricated quote remains rejected.
- `make test-place-research` passed with 600 JavaScript, 429 API/database and 95 standalone checks. Its existing API-to-SQL-to-web replay now injects both coordinate mistakes and verifies that extraction runs once, while dated photo/news research remains available.
- Disposable SQL/process cleanup was verified for every completed candidate and confirmation run. There are no prompt changes or new Langfuse versions in this change set.

Implementation commit: `d95adc970372dbb599103656dfbc0c1b66efc28d`. Both changed runtime files match the exact hashes exercised by the live candidate.

### Upstream integration prerequisite

`origin/main` advanced to `520af4b1` with PR114 while this round was running. The measured extraction/span modules are unchanged there; its shared request helper only adds an optional diagnostic identifier. The comparison stays on the frozen `d5dd2140` base. At the time of PR115 profiling, a read-only Langfuse check found no version matching the newer privacy prompt (versions 1–4 checked). PR116 subsequently committed its genuine version-5 receipt. On `357b343e`, `make prompt-check` verified all 93 published pins. No new publication or service restart was required in this follow-up.

### Approved attribution retry follow-up — completion still fails

The user approved the named retry-feedback change with “yes follow that plan” on 2026-10-23. The implementation adds exactly one error alias in `lifetime_memory_lane_engine.py`: `Attribution requires an exact unambiguous span` maps to the existing `PAGE_AMBIGUOUS` code. Model, effort, prompts, output schema, transport, source admission and all validators remain unchanged. Compiled instructions/schema were checked byte-for-byte before and after.

The exact original held-out `heldout-zh-window` input was replayed through the same canonical dispatcher and real disposable SQL, with native Codex and a six-call ceiling (at most three per page). It **failed after three calls**, taking 10.34, 9.80 and 7.63 seconds of gateway work. Retry packets were `[None, PAGE_AMBIGUOUS, PAGE_AMBIGUOUS]`, so the feedback reached the model. All three responses still gave an incorrect end position for the repeated placeholder sentence. The unchanged attribution validator rejected them; no page was committed. This establishes correct feedback and retained strict rejection, **not improved completion or latency**. The earlier failed input has not been replaced or excluded.

Six bilingual regression cases cover recovering on a correctly positioned occurrence, continued ambiguous rejection, continued fabricated-quote rejection, identical source/fence across attempts, absolute offsets in a nonzero source window and the unchanged three-attempt ceiling. The 136 focused extraction/lane/span checks passed. Required `make test-place-research` passed: 601 JS checks, 429 API/database checks and 95 standalone tests. All native allocations were removed.

A broader 179-check run reached its 120-second limit after displaying two SQL attribution failures. Both failures reproduce with the exact merged-main retry mapping in a separate process: author corrections cause private attribution reads to return HTTP503 while accepted-policy maintenance is pending. These are retained baseline issues, with no production fix in this change. The first sandbox-denied check launch and an initial fixture schema-version error are also preserved with cleanup receipts.

Full source, outputs, checks and dependency/harness hashes: [attribution feedback evidence](evidence/lane-b-attribution-feedback-20261023.json). A further attribution optimization needs a new proposal and approval; strict ambiguous-span validation will not be relaxed.

### Remaining order

Continue with `memoir-memory-context`, embedded place journey, composer, historical news, place photos and deterministic place grouping. The interviewer remains review only. The user explicitly placed story-game optimization last; PR116's existing game changes are preserved and are not part of this follow-up.


## Memory-context round — live baseline, proposal awaiting approval

The user authorized the next Lane B investigation and placed story-game optimization last. This round covers scheduled narrator-profile patches and the selective working-summary prompt owned by `memoir-memory-context`. The current application uses the timeline lane for both. The baseline below predates the approved direct transport; managed prompts, schemas and runtime configuration remain unchanged.

### Execution and prompts

| Step / source | Trigger and work | Output and consumer / dependency |
| --- | --- | --- |
| 1. SQL `schedule_lifetime_profile_round`, `read_lifetime_profile_page` | Default completed rounds 1, 5, 10, 20, 30…; coalesce unprocessed originals into bounded windows. Read current field locks, manual stop, eligible targets and saved profile. | Profile pages are owned by the existing timeline token. Empty targets/manual stop skip the model; reply-only pages preserve state. No current A reply waits for this model. |
| 2. `lifetime_memory_composer._execute_lifetime_lane` | Process due profile pages before timeline extraction, subject to current source/policy/owner/activation. | Profile can delay subsequent B event extraction and later-turn hints; a separate profile scheduler is not introduced. |
| 3. `background_profile.extract_profile` / `profile_contract` | Host builds one exact original window plus eligible fields, saved reference and revisions. Generate `profile_patch` with at most six changes. | Same bounded worker transport and native Codex app-server as timeline. The schema enumerates only writable targets and the current source/version. |
| 4. `validate_profile`, SQL `commit_lifetime_profile_page` | Validate fields, value types/limits, exact original quotes and relative-to-absolute spans; at most three attempts. Recheck live manual authority, revision, source and token at commit. | Canonical profile and UI readiness. A prior saved profile is context, not testimony. No deletion or full replacement is permitted. |
| 5. SQL `advance_two_lane_checkpoint` | Compact covered older sources only when the accepted interval exceeds 16 active windows or 12KB, or follows an existing semantic summary. Small intervals retain lossless originals without an LLM summary. | The newest source remains outside summary coverage; full originals stay retrievable. |
| 6. `_summarize`, `summary_contract`, `validate_summary` | Generate selective items from one current original and the previous accepted summary; exact current/prior citation IDs are enumerated. At most three attempts with fixed evidence/budget/schema feedback. | SQL summary pages accumulate into an accepted checkpoint: at most 16 items and 8192 JSON bytes. Reply-only/tombstone pages preserve prior items without a model call. |
| 7. Actual HTTP admission and final SQL save | `LaneRequestBody`, `LanePublication`, native request admission, source/policy/token checks, checkpoint publication. | Worker output remains a proposal until the real fenced save. Summary reaches later A context; it is never original testimony. |

| Instruction / schema | Purpose and actual use | Size / publication |
| --- | --- | --- |
| `skills/memoir-memory-context/SKILL.md` (`…/instructions`) | Full narrator-profile instructions: evidence, attribution, field meaning, manual authority and patch contract. Loaded only for admitted profile generation. | 5,588 characters; v1, SHA `a28a203eb72c…`. |
| `skills/memoir-memory-context/prompts/summary.md` (`…/summary`) | Selective summary, uncertainty/correction preservation, current/prior quote rules and fixed retry feedback. | 1,558 characters; v1, SHA `01e01f507ce1…`. |
| `ProfileProposal` / `ProfileChange` / `ProfileRef` | Strict typed profile output, target/source enums and exact reference fields. | 1,456 schema characters in ordinary cases; 1,419 after manual field exclusions. |
| `SummaryProposal` / current/prior evidence choices | Bounded item shape and source/version combinations, changing with accepted prior citations. | 1,381 schema characters on the first measured window; later schemas grow with admitted identities. |
| Native Codex framework input and tool definitions | The app-server additionally enables `request_user_input`, `view_image` and `web_search`, although these model phases only produce JSON and need no tools. | Provider usage attributes **4,684 input tokens per call** to tools, including 3,712 cached tokens. This is about **61–67%** of measured input tokens. Full wire requests are preserved in the evidence. |

Both managed prompt sources and their genuine receipts were verified; all 93 repository pins passed `make prompt-check`. Profile and summary have no additional loaded locale prompt in `lane_contract`; current language/privacy/manual context travels in the host-owned packet. The ordinary interviewer and timeline prompts are separately inventoried above. Their replies/events and summary-only profile dependency were explicitly controlled fixtures in this baseline, not additional live generations.

### Frozen live diagnostic cohort

Configured route `memoir-luna-low`, served model `gpt-5.6-luna`, requested and observed effort `low`; native Codex 0.155.1; same task-owned gateway relay as the timeline round; actual disposable SQL admission and persistence. Each selected scenario has one complete sample. This measures background model phases and their controlled canonical workflow, not browser delivery or deployed-worker acceptance. The 5/10-second foreground target does not apply automatically to these background completion times.

| Scenario | Gateway generation seconds, including retries | Controlled case to saved readback | Saved result / frozen quality review |
| --- | --- | ---: | --- |
| English opening profile | 28.20 | 30.94 s | Alan Reed, 1960, original date wording, Hobart birthplace, Brisbane childhood and explicitly supported male artwork hint. Pass. |
| Chinese opening profile | 14.65 | 16.70 s | 林宁, 1963年4月, 河北承德 birthplace and 天津 childhood; no gender guess or Sydney birthplace. Pass. |
| English saved-state correction | 8.06, 7.88 | 22.84 s across five controlled turns | First live profile saved 1960/Hobart. The round-five reference reloaded it; the explicit correction saved 1958 and retained Hobart. Three intervening reply-only turns made no profile calls. Pass. |
| Chinese protected fields / relative facts | 10.38 | 12.49 s | Manual 顾青 and blank birth year/place were preserved; father's 1942/Nanjing/gender were not borrowed. An extra unknown-date expression was saved alongside 武汉 childhood. **Fails the frozen “only childhood” expectation**; interpretation of unknown date wording remains unresolved. No fabrication or manual-field overwrite is demonstrated. |
| English summary with saved prior | 9.86, 5.34, 7.63 | 38.95 s | First window needed one `SUMMARY_EVIDENCE` retry. Final checkpoint retained the 1958/Hobart statement, childhood kite and unknown childhood year; prior SQL summary was consumed by the next window. Pass. |
| Chinese corrected-colour summary | 10.00, 6.38 | 31.78 s | Final saved summary records 天津 childhood and explicitly corrects purple to blue with unknown year and citations to both originals. Pass. |

The six completed selected cases used ten actual model calls. The baseline has **14 total paid completions**, all retained: the four earlier summary generations reached a saved checkpoint but final verification passed a coverage position to a `policy_epoch` parameter. The corrected verifier reran only those two cases. Initial small summary fixtures and their first retry dispatched zero summary calls because the real compaction threshold was not reached. The revised manifest freezes the same factual originals plus fifteen neutral reply-only originals before the final source, crossing the real >16-window threshold without changing production thresholds or granting model authority. All seventeen older windows were processed, with only the two factual windows requiring model generation; the newest source was excluded. The earlier setup/readback failures are calibration evidence, not successful application acceptance.

First-response bytes from the relay are not meaningful UI text. All native allocations and SQL state were cleaned up. Profile/summary quality above is assistant review against the pre-dispatch rubric, not independent human evaluation. One profile semantic gate remains unmet, so this is not all-skill acceptance.

### Approved optimization: direct Responses for profile and summary only

| Proposed change / affected code | Measured cost and expected gain | Retained quality contract | Verification / rollback |
| --- | --- | --- | --- |
| Route only `profile` and `summarize` in `lifetime_memory_lane_engine.run_bounded_lane` through the existing direct Responses approach, reusing bounded SSE/completion decoding and the immutable lane request-body guard. Keep event extraction/composer/interviewer routing unchanged. Add focused direct-transport and real-SQL fence regressions. | Remove the 4,684 tool tokens per measured request, generic framework input and fresh app-server session. No latency percentage is promised: most observed time is generation, and the first profile alone used 1,034 reasoning tokens. Measure actual gain rather than infer it from character counts. | Identical domain prompts, canonical input, output schema, configured model/effort/output allowance, source/policy/manual authority, Issue14 admission, actual-byte guarding, strict JSON/evidence validators, retries and durable commits. No source, quote or rejected proposal is discarded to make a result validate. | Repeat all six frozen scenarios with each arm's own saved state; require all frozen quality gates, including the protected-field case. Add held-out nonzero-window profile and summary evidence. Check stale owner/source/policy/token/manual changes at real provider-byte admission, cancellation, incomplete/tool output and unchanged prompt/schema hashes. At most 27 candidate plus nine held-out calls; combined round cap 54 including 14 baseline calls; 90 seconds/provider call, no judge calls. Restore the existing native path for these phases on failure. |

The user explicitly approved this change: “implement direct LLM calls for profile and summary, rerun profiling and quality checks, and update PR117 without merging.” It is implemented on `optimise-all-skills`, overriding the workflow skill's default main-checkout rule. This transport-only change needs no new prompt version. Shortening the profile instructions is a separate subsequent hypothesis so the cause of any measured change stays clear. Further parallelizing profile and timeline would require fresh admission/revision design, because profile commits can invalidate a concurrently captured page; no such scheduling change is proposed here.

Full inputs, model outputs, saved state, exact requests, source/harness inventories, all failed runs and cleanup receipts: [memory-context baseline evidence](evidence/lane-b-memory-context-baseline-20261023.json).

### Direct transport implementation and live comparison

Only `profile` and `summarize` branch into direct Responses in `lifetime_memory_lane_engine.run_bounded_lane`. They skip native app-server/thread creation and use no tools. The existing reply transport's SSE/completion decoder is shared without changing the foreground request, cache key or 512KB response ceiling. Memory-context uses a bounded 2MB response ceiling. The immutable `LaneRequestBody` holds the real publication guard while HTTP consumes the body and rechecks Issue14 admission immediately before yielding bytes. Complete JSON proposals still pass the original semantic/evidence validation, three-attempt ceiling and fenced SQL commit. Event extraction and composer retain their native route.

All ten selected baseline compiled prompt/schema contracts matched the candidate compiler byte for byte on the same captured fences. The direct request preserves canonical packet, schema field order, `codex_output_schema`, model alias `memoir-luna-low`, served `gpt-5.6-luna`, requested/served `low` effort, and the same effective diagnostic 16,384-token output ceiling. Native framework/tool context is the approved removed variable. Candidate cache hits were zero; baseline tool context included cached tokens, so this is not a controlled cache experiment. Each arm loads its own saved prior output; no baseline-generated summary or profile is injected into the candidate.

| Frozen scenario | Model seconds before → after (all attempts) | Reduction | Controlled case to saved readback before → after | Calls before → after | Final quality |
| --- | ---: | ---: | ---: | ---: | --- |
| English opening profile | 28.20 → 8.49 | 69.9% | 30.94 → 11.21 s | 1 → 1 | Pass: all six narrator fields, exact source evidence; date wording `1960`. |
| Chinese opening profile | 14.65 → 6.10 | 58.4% | 16.70 → 7.76 s | 1 → 1 | Pass: 林宁, 1963年4月, 河北承德, 天津; no gender/current-city inference. |
| English saved-state correction | 15.94 → 9.02 | 43.4% | 22.84 → 14.79 s, five controlled turns | 2 → 2 | Pass: saved/reloaded 1960 → 1958, Hobart retained, three neutral turns make zero calls. |
| Chinese protected fields / relative facts | 10.38 → 4.64 | 55.3% | 12.49 → 6.76 s | 1 → 1 | **Fail, unchanged category:** protected fields remain intact and father facts are not borrowed, but an unknown-date expression is still saved. |
| English saved-prior summary | 22.82 → 7.66 | 66.4% | 38.95 → 22.59 s | 3 → 2 | Pass: 1958/Hobart and Brisbane/kite/year uncertainty retained; newest Sydney source excluded. |
| Chinese correction summary | 16.38 → 7.58 | 53.8% | 31.78 → 23.25 s | 2 → 2 | Final checkpoint passes: 天津, purple explicitly corrected to blue, year unknown, both originals cited. |

This selected cohort used nine candidate calls versus ten baseline calls. Input tokens total 74,873 → 15,769 (78.9% lower, including the avoided retry). Per-call median generation time was 8.96 → 4.53 seconds across different attempt counts; that descriptive statistic is not a paired latency distribution or a tail guarantee. There is one sample per scenario, taken later than baseline, with possible provider/load drift. The controlled case includes SQL intake, fixtures and readback; neither it nor relay first byte is browser paint or meaningful user-visible text. These are background completion times, so no 5/10-second foreground acceptance is claimed.

Two held-out cases, frozen before implementation, used three additional calls:

- Chinese nonzero-window profile processed real SQL windows starting at 0 and 1,792. The neutral first window returned no facts. The second saved 周岚, 1972, 南京 and 苏州 with absolute original evidence after host normalization, without gender inference. **The required birth-date expression was omitted**, so the complete held-out rubric fails. Model time 2.28 + 5.56 seconds; controlled case 10.62 seconds.
- English attributed summary kept the aunt's unverified 1955/Dunedin statement separate from narrator 1974/Nelson, retained exact source quotes, covered seventeen older windows and excluded the newest Wellington source. Pass. Model time 3.04 seconds; controlled case 16.16 seconds. The model's miscounted quote coordinates were resolved by the existing exact-unique-quote validator; this transport change does not alter that validator.

Inspection also found an existing intermediate citation weakness: in both arms, the first Chinese summary mentions the blue correction from `recent_dialogue` while citing only the current purple-kite original. The final checkpoint adds the second original and is correctly cited. This is retained as a separate quality concern; final-checkpoint success does not prove every intermediate proposal has complete semantic citation coverage.

All six candidate cases and both held-out cases completed their SQL workflow and cleaned task-owned processes/databases. The round has 26 actual provider-bound completions: fourteen baseline/calibration, nine candidate and three held-out, within the approved 54-call ceiling; no judge calls. The candidate harness incorrectly labels its scope as native and states a 300-second per-case limit in two copied metadata fields; its actual code uses direct Responses and a 600-second case timeout. Source, wire requests and phase records establish the actual route, and this metadata defect is disclosed without rewriting the raw run.

The observed speedup and transport/state guards pass their diagnostic checks. **Full quality acceptance fails** because the protected-profile gate and nonzero-window date-expression gate remain unmet; intermediate summary citation quality also needs follow-up. This candidate remains unmerged in draft PR117. No prompt publication, shared service activation, deployed-worker, Temporal or browser acceptance was performed. The existing native branch can be restored for these two phases without changing their domain contracts; this PR is not authorization to roll out the candidate as fully accepted.

Verification retained the unsuccessful checks as well as passing ones:

- 197 focused transport/profile/lane/reply/span checks passed. Ten direct profile SQL cases cover owner, source, policy, token, manual locks, stop, rollout and a manual change after send. Six focused summary SQL/feedback checks passed, including policy change after send. These SQL cases also pass in the broader lifecycle run.
- `make test-place-research` passed: 601 JavaScript, 429 API/database and 95 standalone checks. This covers the shared decoder's existing foreground consumers and place/photo/news workflows.
- The wider profile/summary/reply/worker run had 110 passes and 30 failures. The combined core/legacy-admission run had 233 passes and 33 failures. **All 63 failed test identities fail again when both changed transport modules are loaded from merged main `357b343e`**. Failures include older removed `_home`/legacy worker interfaces, request contracts and existing SQL profile/summary fixtures. They are not counted as passes or silently excluded from the report.
- An initial summary regression test insertion misplaced an existing assertion, causing five `NameError` failures after the boundary assertions. The assertion was returned to its original test; the corrected six-case check passes. Both logs remain. One baseline replay launch was denied by the backend-operation lock while the place suite was active; it dispatched no models, was retried after completion, and is recorded separately.
- Every completed native allocation/isolated check has verified cleanup. The live SQL databases were disposable synthetic state; no shared app process was restarted or reconfigured.

Full candidate/held-out outputs, saved state, comparison metrics, prompt/schema equality, source and harness hashes/code, all check logs and cleanup receipts: [memory-context direct transport evidence](evidence/lane-b-memory-context-direct-20261023.json). The baseline evidence is retained unchanged. Next quality proposals must address unknown-date field meaning, date-expression completeness and intermediate summary citations without relaxing the frozen gates. The next separate optimization round remains Lane B; story-game is last.

## Third Lane B round: composer

Baseline revision `7bfc119734a44ad6d6a46d4a366288b40adcf3ba`; existing branch and checkout. The baseline flow below describes the periodic canonical composer before the approved direct transport. Its selected-outline collection flow is also inventoried but is a separate conditional path, not included in periodic timing. The approved implementation and fresh comparison follow the retained baseline/proposal.

| Step / production source | Trigger, input and work | Output / dependency |
| --- | --- | --- |
| 1. SQL `claim_memoir_lane`, `memory_event_worker.MemoryEventWorker.execute_lane` | Owned pending composer milestone, sufficient completed rounds, accepted/extracted sources, pinned preferences and canonical event snapshot. Worker renews its 60-second lease every 20 seconds, within the run deadline. | Durable Lane B work; the current chat reply does not await it. |
| 2. `progressive_composer.batch_job`, `canonical_composer.composition_request` | Build a bounded batch: at most five new original windows, sixteen admitted sources and eight events, plus saved prior manuscript/summary and exact manifests. | One authoritative request; previous prose and summaries do not become testimony. |
| 3. `compose_shared_snapshot` preparation | New message batch gets one `prepare` model call and a durable source-linked checkpoint. The non-batch compatibility path prepares dirty events with bounded concurrency (default three, maximum four). | Derived context for drafting; copy canonical references exactly. Batch summary maximum 4,000 characters. Preparation precedes draft. |
| 4. `compose_candidate`, local `plan` operation | Validate grounded canonical request and choose supported output kind, chapter IDs and counter. Empty/insufficient evidence can finish without drafting. Reuse completed same-authority phase checkpoints. | Host plan, not an LLM outline in this periodic path. |
| 5. `composer_call` → bounded lane → native `run_bounded_lane` | Compile phase prompt/schema, enforce original packet/artifact lineage and budget, guard actual worker/provider dispatch, create fresh governed native session, generate a structured draft. | Candidate plus registered phase output. General native tools/framework remain present in this baseline. |
| 6. Local deterministic/evidence validation | Restore unaffected passage bytes; pin server-known metadata and normalize supported actions; validate schema, word ceiling, source/event spans, prior/protected text and canonical evidence. Compact requests may fall back to the full request on repair. | Invalid candidates return to drafting with fixed validator output, within three draft attempts. |
| 7. Separate `review` model call | Inspect the exact valid candidate against original evidence, including attribution, uncertainty and unsupported emotions/chronology. | Requires ready-for-user-review true, publication false and no blocking finding. A blocking review returns to draft within the same ceiling; this check is not backgrounded after acceptance. |
| 8. Local render and SQL publication | Render manuscript/preview, recheck authority and atomically save page/root, stable sections, dependencies and coverage; protected edits remain proposals. | Private reviewable draft for later workspace consumers. Model review never grants publication. |
| 9. Separate `CollectionJobWorker` / `run_bounded_job` | User-selected `BuildOutline` jobs use bounded original-window leaf calls and child-section merge calls, durable claim/pages, exact membership and publication guards. | Organised selected collection, not the periodic draft/review pipeline. This path needs its own live scenarios before an optimization claim. |

| Managed instruction / source | Purpose / composition | Source → rendered characters; published pin |
| --- | --- | --- |
| `memoir-composer/prepare` | Event preparation; batch mode adds the delta-summary instruction. | 720 → 720; v1 `1012d18f9086…` |
| `memoir-composer/batch/prepare` | Summarize the five new messages, preserve evidence/uncertainty. | 297; v1 `6109366cd545…` |
| `memoir-composer/draft` | Grounded draft, canonical evidence, prior/protected text, incremental repair and output contract; references narrative enrichment once. | 5,406 → 9,005; v2 `878af912ccd3…` |
| `memoir-composer/review` | Exact-candidate factual/editorial review and incremental context; references review guidance and enrichment. | 1,611 → 8,881; v3 `0ea3aef24d8c…` |
| `memoir-composer/shared/narrative-enrichment` | Supported scene detail, voice, rhythm and metaphor without invented personal facts. | 3,630; v1 `7c448673acdf…` |
| `memoir-composer/shared/editorial-review` | Assertion-level evidence-to-prose review, uncertainty/rights and concise findings. | 3,698; v1 `556d3570da3a…` |
| `memoir-composer/batch/compose` | Stable IDs, exact unchanged prose, current-event evidence and acknowledgement exclusion. Appended to both draft and review in batch mode. | 578; v1 `5f16e68a08bc…` |
| `shared/bounded-context/en-AU`, `zh-CN`, `policy` | Both locale wrappers resolve the same authority/privacy/partition guidance. | Each wrapper 93 → 954, v2 `c19926c3affa…` / `b44dae81524a…`; policy 884, v1 `d92070acba1a…` |
| `shared/place-conflicts` | Conditional attribution-conflict guidance when the authoritative fence includes attribution coverage. | 239; v1 `8cffba4dd91a…` |
| `memoir-composer/outline/leaf/en-AU`, `zh-CN` | Selected-original collection grouping with exact source membership. | 99 → 1,110; v2 `a32e8ad5e538…` / `a3108ba8705f…` |
| `memoir-composer/outline/merge/en-AU`, `zh-CN` | Merge bounded child sections without changing membership. | 100 → 1,111; v2 `b1af3ebef854…` / `80fdf1243c33…` |
| `memoir-composer/outline/shared/prefix`, `suffix` | Shared grouping restrictions and typed JSON output. | 735 / 330; v1 `c73e56cbc14f…` / `754884920290…` |
| Dynamic prepare/draft/review schemas | Strict typed output; draft canonical reference choices depend on the current fence. Server-owned fields are still requested, then pinned by the host. | Unbound compact schema 917 / 6,970 / 428 characters. Exact fenced schemas/hashes retained per dispatch. |
| Native framework/tool input | Generic agent context in each fresh session; actual usage and cache measured on the wire. | Not a managed domain prompt; do not omit it from total context cost. |

The composer `SKILL.md` is a workflow guide and is not concatenated into these phase instructions. The periodic batch compiles to 1,971 preparation, 10,537 draft and 10,413 review instruction characters before schema/packet/native overhead. Non-batch totals are 1,674 / 9,959 / 9,835. Selected-outline leaf/merge instructions are not loaded in periodic composition. Evaluator instructions from older live probes are not added to this baseline; there are no paid judges.

The measured pages include attribution coverage, adding the conditional 239-character conflict fragment: actual totals are **2,210 / 10,776 / 10,652**. The first draft schema is 8,242 characters after reference binding and the later schema is 9,436. Both locale wrappers render the same authority text; target-language selection is in the pinned request.

All three periodic phases use the configured composer model (fallback to the global model), worker effort override or `MEMORY_SPARK_MEMOIR_COMPOSER_REASONING_EFFORT` (default low). The live route was `memoir-luna-low`, served `gpt-5.6-luna`, requested and observed effort low, native CLI 0.155.1. Selected-outline uses its bounded job/global model and worker/global native effort settings; its served model/effort is unmeasured. No deployed CLI version is inferred from this isolated run.

The frozen bilingual baseline has one round-five sample and its own SQL-backed round-ten continuation per language. It requires both source-grounded events, distinctive original details, unknown-year preservation, no invented facts, new tyre-patching evidence on continuation, unchanged independent school passage bytes/stable identity, exact citations and private publication status. Canonical event extraction, empty policy reviews and completed-round scheduling are declared SQL setup fixtures; selected prepare/draft/review generation, worker claims/heartbeats, checkpoints, validation, rendering and saves use application code. Baseline maximum 28 provider calls includes calibration; candidate reserve 28 and held-out reserve 14, total round maximum 70; no judges. Provider maximum 180 seconds, each bilingual sequence 1,200 seconds, baseline deadline 2,600 seconds and isolated runner 2,700 seconds. The held-out protection/attribution plan is reserved before implementation.

Calibration is retained. The first zero-call setup used a nonexistent conversation `locale` column; the next verified that UI/profile language does not select draft-edition language. The edition-selection RPC corrected the fixture without production changes. The first paid attempt omitted the outer worker heartbeat: preparation/draft/review completed in 12.55/41.06/6.03 seconds (English) and 12.35/43.88/6.14 seconds (Chinese), then SQL correctly rejected the expired lease. Six paid completions, no draft save. The rerun uses the actual `MemoryEventWorker.execute_lane` wrapper, not a relaxed lease or validator. These failed calibration attempts remain in the 28-call budget and do not establish deployed reliability or latency acceptance.

### Native composer live baseline

| Language / checkpoint | Prepare / draft / review model seconds | Actual worker claim → completed SQL root | Persisted result and gate outcome |
| --- | --- | ---: | --- |
| English round 5 | 12.82 / 43.01 / 5.37 | 68.29 s | Both events, blue tin, Ms Vale and unknown school year saved. Reviewer returned ready with no findings, but the prose adds an unsupported **classroom** setting. Strict factual-quality gate fails. |
| English round 10 | 9.72 / 54.34 / 6.10 | 75.65 s | Own saved manuscript reloaded; tyre patch, rubber/glue and practice beside Father added. School paragraph bytes preserved, including the earlier classroom defect. |
| Chinese round 5 | 12.34 / 42.96 / 6.09 | 65.75 s | 成都, blue tin, father, 王老师 and unknown school year retained in first-person prose. All source/JSON checks and private review pass. |
| Chinese round 10 | 11.45 / 53.77 / 6.03 | 78.94 s | Own prior manuscript reloaded; new patch/glue testimony incorporated. School text changes `辨认地图` to `看地图` and its stored partition key changes. **Fails the frozen byte-preservation gate**, despite preserving the main meaning. |

The full five-round-plus-continuation controlled sequences, including setup and both saved readbacks, took 145.27 seconds (English) and 145.92 seconds (Chinese). Each has six successful native calls, no application repair, and six observed production heartbeats. These are single samples, not a latency distribution. The earlier Chinese run reached preparation, then the gateway returned an SSE upstream timeout with HTTP 200, no final document and no usage; the budget adapter correctly rejected it. Only that language was rerun, without editing the source manifest or application. All attempts are retained: **20 provider-bound attempts, 19 completed generations and one upstream failure with unknown usage**, including the six no-heartbeat completions. This is within the original 28-call baseline ceiling.

Every measured request still enables three unused native tools (`request_user_input`, `view_image`, `web_search`), billed at 4,684 input tokens, 3,712 cached. Across the twelve selected requests these account for 56,208 of 149,203 input tokens (37.7%; per request about 28–63%). Drafting consumes about 74% of selected model time. Structured draft output is 5,084–8,061 characters, with only 183–691 characters of displayed headings/prose; the remainder includes required evidence and metadata, so it cannot all be discarded. Server-owned output fields and duplicated prompt guidance are later hypotheses, not implemented changes.

The model's review pass is useful but is not a complete quality certificate: it approved all four candidates without finding the classroom detail. Both school paragraphs also cross-reference bicycle sources, so purely independent-event passage preservation is not fully exercised by this cohort. Exact evidence-reference validation cannot alone prove prose entailment. Assistant semantic review and actual SQL bytes establish these limits; there is no independent human evaluation. No personal facts, citations or failing proposals were removed by the harness, and no expected output was injected into a later turn.

### Approved change: direct composer phase transport

| Named change / files | Measured cost / expected effect | Retained contracts and quality gate | Validation / rollback |
| --- | --- | --- | --- |
| Extend the existing direct Responses branch in `lifetime_memory_lane_engine.run_bounded_lane` to **prepare, draft and review**. Reuse bounded completed-document decoding and real lane body admission. Add phase-specific transport and real SQL checkpoint/protection regressions. | Remove native tool/framework input and fresh session startup from each selected call: 4,684 tool tokens per call are measured. Composer speedup is unmeasured; input removal need not translate proportionally into generation time, especially for its long draft output. | Keep all three model phases and the separate exact-candidate review before saving. Keep prompts, schema, canonical packet, model/effort/output bound, original/owner/policy/artifact lineage, heartbeat/retry/checkpoint logic, prose validation, protected edits and SQL publication. Full strict quality gates remain required; baseline defects do not excuse candidate failures. Selected-outline jobs retain their current native route. | Repeat the same four checkpoints with each arm's own saved state, then the frozen bilingual attribution/protected-passage held-outs. Candidate maximum 28 plus held-out 14 calls; total composer-round cap 70 includes all 20 baseline attempts. Test actual-byte stale authority, phase proofs, incomplete/tool output, cancellation and private/protected commits. Rollback removes only the added composer phases from the direct branch. |

The user explicitly approved this composer-only change on 23 October 2026 ("Approve composer transport (Recommended)"). It is implemented on the existing `optimise-all-skills` branch and checkout, following the instruction to update PR117 without merging. No managed prompt, schema or runtime configuration changes or publication are included. Selected-outline profiling and full independent/protected/attributed passage acceptance remain pending; game remains last.

Synthetic scenarios, phase metrics, exact before/after school text, gate outcomes, provenance and cleanup inventory: [composer baseline evidence](evidence/lane-b-composer-baseline-20261023.json). The index hashes a [lossless gzip JSON archive](evidence/lane-b-composer-baseline-20261023.json.gz) containing every full provider request/output, persisted manuscript/section, worker timeline, failed calibration/timeout and harness/helper source. Standard Python `gzip.open` reads the archive; the index includes a command. Compression removes no evidence.


### Composer direct transport: implementation and fresh comparison

`run_bounded_lane` now sends `prepare`, `draft` and `review` through the existing direct completed-document transport, alongside profile/summary. The application diff adds these three phases to that branch and generalizes its provider-configuration error. There is no new transport abstraction or model phase. Each request disables tools, retains the exact domain instruction/schema/canonical packet and configured model/effort, and crosses the real `LaneRequestBody` owner/source/policy/token/phase-proof/Issue14 guard immediately before provider bytes. Parsing still rejects incomplete, differing, tool-bearing, credential-bearing and invalid JSON replies. Canonical validators, the separate exact-candidate review, three-attempt repair limit, phase checkpoints, worker heartbeat, SQL commits and protected/private output behavior remain in the existing callers. Extraction and selected-outline collection jobs retain their native route.

All twelve captured baseline instruction/schema pairs recompile byte for byte on the same recorded fences. The frozen source manifest is unchanged, and each candidate continuation reloads its own first SQL save. Both arms requested `memoir-luna-low`, low effort and a diagnostic 16,384-token output ceiling; served model/effort were `gpt-5.6-luna`/low. Both original wire requests requested reasoning summary auto, and the gateway reports detailed summaries. Native tools/framework/session/cache scaffolding is the approved variable. Baseline tool cache was warm; most direct input was uncached. Runs were sequential and later than baseline, so provider/load drift remains uncontrolled.

| Language / checkpoint | Baseline → direct worker claim to completed SQL root | Reduction | Direct prepare / draft / review provider seconds; calls | Outcome |
| --- | ---: | ---: | --- | --- |
| English round 5 | 68.29 → 27.56 s | 59.6% | 6.03 / 13.57 / 4.12; 3 | Saved both supported events and exact original evidence; no classroom addition observed. |
| English round 10 | 75.65 → 27.61 s | 63.5% | 4.48 / 15.13 / 4.23; 3 | Own prior loaded; tyre/rubber/glue/practice facts added. **School paragraph rewritten: frozen preservation gate fails.** |
| Chinese round 5 | 65.75 → 25.22 s | 61.6% | 5.17 / 12.91 / 3.61; 3 | Saved both events, blue tin, 王老师 and unknown school year. |
| Chinese round 10 | 78.94 → 52.58 s | 33.4% | 6.01 / 15.21 / 4.47, then draft 14.56 / review 4.53; 5 | Reviewer blocked unsupported “后来” chronology; existing repair removed it before save. School text and partition identity preserved. |

All four candidate checkpoints passed deterministic validation, exact-candidate model review and private SQL save/readback. The reviewer’s rejected Chinese draft is retained; excluding it would overstate the gain. The complete controlled sequences took 56.32 seconds English and 79.26 seconds Chinese versus 145.27/145.92 baseline. Actual production-wrapper heartbeats were observed twice and three times respectively. Across the four checkpoints, model time fell 263.99 → 114.04 seconds (56.8%); input tokens fell 149,203 → 104,637 (29.9%) **including the two repair calls**. Calls rose 12 → 14 and output tokens rose 12,972 → 15,647. There are no direct tool tokens; the baseline’s twelve selected calls had 56,208. These are single samples per checkpoint, with no browser, Temporal or deployed-worker timing and no foreground five/ten-second acceptance claim.

Actual English school text shows the remaining issue. The first candidate saved “I do not remember the year, but I remember the lesson as part of that childhood account: bicycles in the shed, and maps at school.” Its continuation saved “I do not remember the year. The memory sits alongside the shed and the blue tin: one kind of learning at school, another beside Father.” The SQL partition key remained stable, but the paragraph bytes did not. Both baseline arms and the English candidate supplied an empty `preserved_sections` list: the school paragraph also cited the dirty bicycle event, so the host correctly could not prove its independence. The Chinese candidate’s separate school-only paragraph was eligible for host restoration. This is a limit of the generated passage/dependency boundary, not a reason to drop canonical citations or weaken the preservation gate. The English baseline preserved its school bytes, so the candidate does not establish no-regression quality.

### Frozen composer held-outs and acceptance

The exact bilingual held-out originals/rubric were reserved before implementation. Both use childhood chess with a brother, a separate aunt’s unverified 1964 harbour account, then new notebook/move testimony. Canonical event setup uses the same source-exact SQL fixture as the baseline; the aunt stays unplaced rather than being assigned narrator childhood. After each first actual model save, its own chess paragraph(s) were marked approved through the existing SQL protection-test fixture. No baseline prose was injected. A zero-call setup verified both editions and real phase admission before the paid run.

- **Chinese protection/state checks pass:** six calls saved both checkpoints. The approved paragraph’s full SQL `bundle::text` bytes and partition key survived exactly; it remains approved/human-locked. Root state is `proposed`, approval is required and publication stays false. New notebook/move prose has current original citations, no approved flag and only a proposed preview. The protected row’s proposal repeats its existing bytes; the new material is a separate unapproved record. This proves preservation and a private root proposal, not an edited protected-passage replacement. The phrase “一页页可以回看的记录” suggests a quantity of written material not established by the sources; full semantic quality is not certified by the reviewer’s pass.
- **English protected continuation is incomplete:** the first checkpoint needed five calls because its reviewer requested attribution/detail corrections, then saved a repaired private draft. Later preparation and drafting used calls six/seven. The task-owned proxy refused the next review at the frozen seven-call language ceiling, before provider dispatch. Worker diagnostics surfaced `ResponseNotRead`/retry from the HTTP429 budget denial. No second exact-candidate review, commit or readback occurred. This is retained as a budget-limited held-out failure; it does not demonstrate an upstream model failure or a passing protected save. The ceiling was not enlarged after seeing the result.
- **Attribution-prose coverage is inconclusive in both languages:** the initial metadata retains aunt attribution and unverified year, and the model explicitly defers that unplaced event outside the childhood sample. Neither invents a harbour location or converts it into the narrator’s recollection, but neither writes the story in finished prose. Deferral is disclosed rather than counted as full attribution acceptance.

The composer round totals **47 actual provider-bound attempts: 20 baseline/calibration, 14 candidate and 13 held-out**. Forty-six completed; the earlier baseline upstream failure has unknown usage. The additional task-proxy denial is not a provider-bound call. The unchanged round ceiling is 70, candidate ceiling 28 and held-out ceiling 14/seven per language; no judges. Every live and isolated-test allocation has verified task-owned process/database cleanup, and no selected direct call created a native model home.

| Gate | Result |
| --- | --- |
| Approved direct route; unchanged domain prompts/schema/model/effort | PASS for captured contracts and observed configured/served route. |
| Actual-byte authority, proof chain, cancellation, review repair and SQL checkpoint resume | PASS in focused tests and the recorded SQL/live cases. |
| Meaningful background speed improvement | PASS in this diagnostic cohort: 33–64% faster claim-to-save, including repair. More samples/deployment remain unmeasured. |
| Frozen no-regression/source/prose preservation quality | **FAIL**: English school bytes changed; Chinese held-out prose extent also needs review. Existing profile/date-expression and intermediate summary citation blockers remain. |
| Bilingual protected continuation and attribution prose | **INCONCLUSIVE**: Chinese SQL protection passes; English stops at its finite budget; neither exercises finished attributed harbour prose. |
| Browser / Temporal / deployed worker; full #53 ACs | **UNVERIFIED / NOT COMPLETE**. |

Verification: **234 focused transport/lane/reply/canonical/progressive checks plus 11 direct composer SQL integration cases pass**. The SQL cases cover missing preparation/draft proofs before later provider bytes, stale owner/source/policy, policy change after send, blocking-review repair and exhaustion, cancellation without commit and restart reusing preparation/draft checkpoints. `make test-place-research` passes **601 JavaScript, 429 API/database and 95 standalone** checks. An initial new cancellation test called an existing `asyncio.run` fixture inside an event loop and failed; constructing that fixture before the loop fixed the test. Its failing log is retained. The previously recorded wider profile/summary failures and merged-main reproductions remain part of PR117’s evidence, not new passing checks.

Full requests/responses, accepted and rejected drafts, worker timelines, protected bytes, final SQL records, compiled-contract equality, source/dependency/harness code and hashes, check logs and cleanup receipts are in [the composer direct evidence index](evidence/lane-b-composer-direct-20261023.json) and its [lossless gzip JSON archive](evidence/lane-b-composer-direct-20261023.json.gz). Baseline artifacts above remain unchanged. No managed prompts were published or services activated. PR117 remains a draft and must stay unmerged pending the failed/incomplete gates. Follow-up analysis should address passage dependency boundaries without discarding citations, exercise both protected/attributed continuations with a budget reserved for repairs, and profile the separate selected-outline path. Remaining Lane B skills continue before game; no new optimization is implied by this transport approval.


## Fourth Lane B round: historical-news research baseline

Revision `0e459fede7016c7cfc656fbdd97d1890bf2bb201`, existing branch/checkout. Investigation only; no news application, prompt, model or configuration optimization is implemented. The runtime feature flag defaults off, while the current local configuration enables it and selects `memoir-luna-low`. The baseline uses that configured route in an isolated process with synthetic sources and real disposable SQL. The service itself is not restarted or activated.

| Step / source | Input / work | Output and delivery dependency |
| --- | --- | --- |
| 1. `LifetimePublicationContext.close`, `background_skills.queue_research` | Register optional research after a delivered saved reply; release the foreground scope/lease before lookup. Selected-place photo requests also register `_selected_place_news` after their response. | Lane B. Code inspection confirms the governed stream sends `more_body=False` before closing/research; no current model reply awaits web discovery. |
| 2. `historical_news.enrich`, `UserStorage.historical_news_basis` | Read owned versioned sources/events and available saved place journeys. `accepted_hypothesis` / `research_places` validate a reviewed coarse place and exact source-bound year window; missing/conflicting/unsupported context skips. | Local source/policy preparation. Raw narration, addresses, IDs and private names do not become queries. |
| 3. SQL `begin_user_historical_news` | Under project lock, require no live foreground lease, opt-in, exact source sequence/context revision and a reviewed place/window. Suppress duplicate running/recent completed attempts. | Durable 45-second claim; failure suppression is distinct from a successful evidence cache. |
| 4. `HistoricalResearch.run` cache | Key public place/year queries by adapter/model identity and contract version; reuse a genuine successful entry for24hours, at most128 process entries. Private relevance is attached per current SQL generation. | A success-cache hit skips discovery. This cohort produced no success entry, so warm-cache speed is unmeasured. |
| 5. `GatewayHistoricalProvider.discover` | Direct Responses, required native `web_search`, source URLs included, low effort,3,000 output tokens. First city query, inspect its leads, then country query. The first discovery failure retries the same query within the two-request total cap. | Two sequential LLM/search requests maximum; each must have completed native tool receipts and observed URLs. No generic Codex session. |
| 6. `GatewayHistoricalProvider.inspect` / `historical_news_source` | Fetch each returned unique public HTML/text page in a cancellable/reaped child process with existing URL/DNS/robots/redirect/size safeguards. At most six reads; failed pages are not retried. | Independent page text/title/publisher/publication date. Search snippets never count as inspected pages. |
| 7. `validate_evidence` | Require exact supported excerpt/summary, event name/year/place, actual source metadata, public query relevance, native receipt, no date conflict or sensitive topic. Deduplicate without promoting history into testimony. | Zero to five external clues. Invalid leads reject; no metadata/quotes are repaired for the baseline. |
| 8. SQL finish, read and later consumer | Recheck current owner/source/policy/preference/context/claim deadline, persist ready/empty/unavailable, expose only current ready clues. Later interviewer selection remains optional and source-attributed. | No personal MemoryEvent or publication permission. The live baseline reads SQL consumer context; it does not generate a later interviewer question or observe browser paint. |

| Prompt/component | Purpose and actual use | Characters / published provenance |
| --- | --- | --- |
| `memoir-historical-news-research/prompts/discovery.md` | Sole transmitted managed instruction: native public search, at most two source-backed JSON leads, exact source passages, event-date/source-identity and sensitivity constraints. Query substituted into input. | 1,185 source characters;1,224–1,237 in the four measured requests. v1,`92bced910bfb…`; exact rendered hashes retained. |
| Skill `SKILL.md` | Application guide; not concatenated into discovery. | 1,939;v2 receipt. |
| `references/contract.md` | Evidence/privacy/claim/budget integration rules; not concatenated into discovery. | 3,379;v1 receipt. |
| Output shape and native web tool | JSON shape is inline in the instruction; no separate `text.format` schema or model reviewer. The web tool is required work, with provider-owned instructions/search context. | Request has only `web_search`; actual native overhead is not itemized. The managed prompt being below2k does not mean total provider context is below2k. |

The frozen English and Chinese sources both place the synthetic narrator in Sydney in2000 and include an unrelated private nickname/notebook detail. Exact source-bound place/window proposals and empty policy reviews are declared setup fixtures, using the same seam as the existing place-research tests. Actual hypothesis projection, SQL claim, live native discovery, public page process, strict validation, finish and fresh readback use application code. A zero-call preflight verified the real claim path. Baseline ceiling8 provider requests includes calibration, two per paid case,3,000 output tokens each,45-second engine deadline,75-second case/360-second run; candidate8/held-out8 reserved, total24; no judges.

| Case; one cold sample | LLM/search provider time; app discovery wall | Page inspection | Engine / full controlled case | Actual result |
| --- | --- | --- | --- | --- |
| English Sydney2000 | 17.27+13.49=30.76s;32.23s | Two reads,3.43s | 35.67 /36.41s | `unavailable`,zero clues persisted and zero in next SQL consumer. One page accessible but event-name/source-title checks fail; the second page cannot be inspected. |
| Chinese 悉尼2000 | 17.33+10.96=28.29s;28.81s | Two reads,1.88s | 30.70 /31.34s | `unavailable`,zero clues. The accessible lead’s excerpt is absent from the fetched text and source metadata differs; another page cannot be inspected. Leads also use geography outside the exact admitted Chinese place/country labels. |

All four Responses and native search calls completed, with52,065 input tokens (15,872 cached) and2,036 output tokens. The response reports model alias `memoir-luna-low` and effort low; the underlying served model is **unverified**, unlike the composer’s explicit served-model response. All task-owned relay/source/SQL processes were reaped and allocations cleaned. No provider failure or timeout occurred in this cohort; no tail percentiles, deployment, successful warm cache or useful clue latency is established.

Safety checks pass for these two cases: private nickname/source/owner/project IDs are absent from actual discovery bodies; duplicate current-context claims, missing source-bound periods and a disabled flag make zero extra calls; no public history becomes a personal event. The SQL `unavailable` result is durable. It is **not** a success evidence-cache entry: the24-hour duplicate suppression prevented another paid attempt, while the warm-success test correctly remained unexercised.

A zero-call replay checks the unchanged original proposals/receipts against the actual fetched pages. English’s accessible excerpt is verbatim, but the chosen event name is absent from that excerpt and the proposed page title omits the actual title suffix. Chinese’s accessible lead fails verbatim support and page-title/publisher equality; other geography/year failures are visible before fetching. These are observed contract mismatches, not a claim that the underlying historical event is false. No page, metadata field, quote or geography was manufactured to clear validation.

Search/discovery occupies90–94% of engine wall time, with86–92% in measured gateway work. The current1.2k prompt/direct transport already meets the instruction-size objective for this step. Early rejection of three provably invalid leads could avoid roughly1.8seconds per language here; this is a small offline estimate, not an implemented or measured gain. Starting both queries together could shorten the happy path, but it spends the second request before knowing whether the city query needs its allowed same-query retry. Preserving recovery needs an explicit design and outage cohort; it cannot be assumed from parallel execution. The immediate recommendation is to resolve source-grounding/accessibility coverage before claiming a larger quality-preserving optimization. All strict evidence, privacy and attribution gates remain in place.

The selected contract run has **98 passes and11 failures**. All eleven are older runtime-fixture failures (missing current policy-review RPC/publication setup); the same eleven identities reproduce when54 imported app modules are loaded read-only from merged-main`357b343e`. Both failure logs and the comparison are retained. Canonical SQL/provider/evidence checks in the original run pass; those facts do not establish live clue usefulness. Other local edits appeared during later checks; the captured news/provider/source/selection/storage/prompt/schema hashes still match, and those unrelated edits were preserved.

**Round gates:** public-query privacy, source-rejection safety, duplicate/missing/disabled controls and observed SQL persistence pass this diagnostic cohort. Useful inspected clue coverage is unmet (0/2), successful warm-cache/later-question/browser/deployed coverage is inconclusive, and no optimization/no-regression acceptance is claimed. This measurement preceded the separately requested handoff fix below; no news-research speed optimization was implemented. Remaining Lane B work, including selected-outline and photo research, precedes game.

[News baseline evidence and provenance](evidence/lane-b-historical-news-baseline-20261023.json) includes exact owned prompts/request fields, structured outputs, source/lead hashes, grounding diagnostics, SQL results, helper/harness provenance, all checks and cleanup. Its compressed companion retains that shared evidence. Full third-party page text and verbatim model excerpts remain in the ignored local [raw baseline](/Users/bohuihan/memoir/var/optimise-all-skills-20261022/05-historical-news/baseline-live.json), with hashes and paths in the committed inventory; the shared archive is explicitly not a lossless raw-response archive.

### User-requested correction: background question priorities

The user subsequently reported that completed historical research did not affect Lane A and requested that conflicts, person/event clarification, related news and topic/period expansion influence the question pool. This authorizes the functional handoff fix separately from the pending research-speed optimization. Six initial offline regressions failed: news was not selectable, plan-only confirmations could be ignored, `broaden_scope` was unavailable, and the active objective was missing from the compact brief.

The fix connects already-ready news to the existing neutral, cited question path in both reply adapters and the strategy SQL transaction. It includes plan confirmations in priority/answer retirement and adds a bounded background `broaden_scope` objective with its prepared questions. Current user controls still win. Clarifications precede topic expansion, ready news and ordinary follow-ups; the model judges relevance with the existing reply call. No unfinished background job is awaited, no extra foreground model call is introduced, and combined reply instructions stay at 1,986 characters. [Behavior, regression scope and activation requirements](lane-b-question-priorities.md).

The new controlled native checks verify real SQL and streamed API delivery, citation replay and exactly one reply generation per new turn in both languages. This is not live semantic/latency or deployed acceptance, and the earlier 0/2 useful-live-news result remains unresolved. The two prompt sources need merged-main publication and genuine receipts before activation. PR117 remains draft and unmerged; no service restart, schema deployment or prompt publication was performed.
