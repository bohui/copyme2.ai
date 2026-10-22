# Active skill optimization campaign

Branch: `optimise-all-skills`. Baseline: `d5dd21407bdf29ba35ef2686db4063ccba108420`.

Each Lane B skill gets its own execution/prompt analysis, bounded live baseline, concrete proposal, approved implementation and quality comparison. The user changed the interviewer scope to review only. No service activation or feature-branch prompt publication is included.

## Interviewer review

The current reply-v2 path already has a tool-free direct Responses request, a stable developer prefix, changing current narration last, host-owned metadata and Lane B extraction. Its compiled reply instruction is 1,986 characters; ordinary privacy review is 993 characters. The normal foreground total is 2,979 characters across two requests, before schemas and narration. Catalog size does not equal transmitted prompt size.

Privacy-review v4, optional opening v1 and repair-codes v5 now have valid published receipts. All 93 repository prompt pins passed the remote check on this baseline. The parallel/revisable flow from PR113 is present but its runtime flag remains off by default. It replaces only the current bubble and waits for reviewed final saving.

The previous live acceptance remains incomplete: correction-after-stop failures, slow privacy/repair cases and absent deployed-worker/browser-paint timing were recorded before the newer privacy/repair prompts. The 325 merged regression checks establish controlled behavior, not live semantic acceptance of the latest combined flow. A fresh focused review run on this baseline passed 78 reply, transport, compatibility and revision checks. Its first sandbox-denied launch and verified cleanup follow-up are retained. No interviewer code or prompt changes are proposed in this campaign.

A fresh interviewer run was already starting when the user redirected work. It was stopped by signalling its verified owned process. Nine calls are retained with four completed English turns and a cancelled fifth; this interrupted cohort is not a new acceptance comparison. Its disposable database and process allocations are cleaned; an outer registration-prefix cleanup failure and verified follow-up are retained.

## Lane B inventory

| Skill | Production execution | Round status |
| --- | --- | --- |
| memoir-author-timeline | model; accepted_source | Approved coordinate fix implemented; four-case comparison passed, broader completion gate remains open |
| memoir-place-journey | embedded; place_evidence | Pending |
| memoir-memory-context | model; periodic | Pending |
| memoir-composer | model; periodic | Pending |
| memoir-historical-news-research | provider; place_selection | Pending |
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

`origin/main` advanced to `520af4b1` with PR114 while this round was running. The measured extraction/span modules are unchanged there; its shared request helper only adds an optional diagnostic identifier. The comparison stays on the frozen `d5dd2140` base. A read-only Langfuse check found no published version matching main's newer `policy-review.md` content (versions 1–4 checked). That main-only publication/receipt prerequisite is not bypassed or folded into this code-only optimization. The PR must be integrated and its runtime/pins rechecked before deployment.

### Next proposed author-timeline change — not approved or implemented

The repeated-source failure currently falls back to `retry_reason=OUTPUT_SCHEMA`. The existing error-code vocabulary already contains `PAGE_AMBIGUOUS`, but the attribution validator's exact error is not mapped to it. The smallest next experiment is to add that exact error-to-code mapping in `lifetime_memory_lane_engine.py`, keep three-attempt limits and every validator unchanged, and replay the same frozen repeated-placeholder case. This would give the retry a relevant existing code; whether it improves completion is unproven. It needs its own approval under the optimization workflow before implementation. Tool-free transport replacement remains a separate hypothesis.
