# Author timeline call analysis and optimization

Baseline: `613930a263b0ed49ada3ea3b817f78d43fe81af5`, current remote main at round start. Selected skill: `memoir-author-timeline`. Configured local path: two lanes, `reply-v2`, strategy enabled, background model `memoir-luna-low`, requested effort `low`. Provider receipts report low effort on both measured transports; internal provider policy remains opaque. This is a background completion study; browser delivery and deployed-worker timings are unobserved.

## Requests by scenario, before optimization

These are model requests, not prompt-file counts. Counts assume valid first attempts and current source policy. E is unfinished extraction windows, P is eligible uncovered profile windows, S is eligible semantic-summary windows.

| Work scenario | Author-timeline extraction | Summary requests on timeline role | Separate memory-context requests | Conditions |
| --- | ---: | ---: | ---: | --- |
| Short narration, uncertain date, conflicting identity, topic change with testimony | 1 | 0 normally | 0 unless due | All event/place/question/continuity/strategy fields share one extraction response. |
| Current correction, including correction after a stop | 1 | 0 normally | 0 unless due | Current testimony must be delegated as extract; use saved canonical identity/revision. |
| Stop plus new allowed story | 1 | 0 normally | 0 unless due | Stop delivery and durable extraction are separate decisions. |
| SQL-recognized exact control phrase (for example Please stop., Hello, Thank you) | 0 | 0 if collector work is reply_only | 0 if collector work is reply_only | SQL attribution overrides the collector work hint. Only its recognized control/profile-introduction/withheld cases skip; arbitrary paraphrases can still dispatch. Legacy flag-off extraction lacks this skip. |
| Paraphrased stop/control outside SQL exact list (Please stop the interview here.) | 1 | Conditional S for its history | 0 if collector marks reply_only | Existing admission conservatively extracts; empty event result is still one request. |
| Technical replay or fully processed source | 0 | 0 additional for replay | 0 additional for replay | Reuse accepted source, committed page effects and prior cursors. Outstanding unrelated work can still run. |
| New source of N Unicode characters | ceil(N / 2048) | 0 unless history requires compaction | 0 unless due | Each later extraction window includes up to 256 preceding characters; maximum transmitted size 2304. |
| Crash/yield/retry | Remaining E | Remaining S | Remaining P | Committed pages survive; failed uncommitted requests can be repeated. |
| First completed short-story round | 1 | 0 | 1 | Profile automation active, targets unlocked, no previous coverage. |
| Round 5 after profile round 1, four short intervening sources | 1 | 0 if lossless checkpoint fits | 4 | Profile scans uncovered originals, not only the latest turn. |
| Round 10 after profile round 5 | 1 | Conditional S | 5 | Same single-window assumption. |
| Round 20 after profile round 10 | 1 | Conditional S | 10 | Coalesced first profile job at round 20 can instead scan all 20 sources. |
| Profile automation off, manually complete, all targets protected | E | Conditional S | 0 | SQL owns cadence 1, 5, 10, 20, 30... and exclusions. |
| Lossless history checkpoint within limits | E | 0 | Conditional P | SQL/hash/inventory work only, no model summary. |
| Semantic history checkpoint | E | One per eligible 2000-character history window S | Conditional P | Triggered when preceding checkpoint is already semantic, new original bytes plus prior evidence JSON exceed 12000, or active retained windows exceed 16. Current newest source is excluded. |
| Invalid model JSON/evidence/derived fields | Up to 3 per extraction window | Up to 3 per summary window | Up to 3 per profile window | Initial request plus at most two validator repairs; exhaustion fails without advancing successful cursor. |
| Policy pending, stale owner/token/source, paused generation, Lane A decision still pending | 0 admitted until resolved | 0 admitted until resolved | 0 admitted until resolved | These are admission gates, not extra timeline classifier calls. |

Valid first attempts cost **E + S author-timeline-role requests**, plus **P memory-context requests** in the same serial worker. Application validator attempts are bounded by **3(E + S + P)** per processing pass; later durable job retries can repeat unfinished work. Native transport/provider retries are an additional layer, not covered by that application bound. The profiling harness disables those retries and counts every outbound submission.

Foreground policy review and interview generation belong to `memoir-interviewer` and are excluded from these timeline totals. Public news/photo discovery uses separate provider workflows. A news update without new accepted narration does not itself dispatch this extractor. If a current source is delegated as extract but yields no events, its successful empty response still costs one call per window.

## Baseline execution and delivery dependency

| Step and source | Trigger/input | Work or external request | Output and consumer | Lane / delivery dependency |
| --- | --- | --- | --- | --- |
| 1. `lifetime_memory_runtime.py:188`, `:241` | Owned new turn or technical replay | Validate replay; accept original source/outbox before optional reply | Durable source/version; survives reply failure | A intake; no timeline model call |
| 2. `lifetime_memory_runtime.py:162`, collector path | Original source and current policy | Separate policy review and collector decide extract/reply_only; save reviewed reply and completed round | Typed handoff, current privacy/preferences | A, outside selected skill call count |
| 3. `memory_event_worker.py:200` | Durable pending timeline lane | Claim SQL snapshot/lease, heartbeat, bounded deadline | Immutable page fence/cursors | B; current delivered reply does not await extraction |
| 4. `lifetime_memory_composer.py:238` | Pending A work decision/privacy maintenance | Yield/defer if undecided/incomplete | No model request | B; no successful cursor advance |
| 5. `lifetime_memory_composer.py:247`, `background_profile.py:119` | SQL profile due and eligible originals | Profile request per uncovered window, maximum three attempts; commit profile | Protected profile state, readiness, later context | B, serial before timeline extraction; separate skill |
| 6. SQL `read_lifetime_memoir_lane_page_before_windows`, `:9507` | Unprocessed original/version | 2048-character cores, 256 overlap, up to eight canonical event candidates; current attribution/prefs | Exact window and immutable fence | B; no external search |
| 7. `lifetime_memory_composer.py:135` | Source window, work_mode | SQL attribution chooses work mode, overriding the collector hint; reply_only returns empty locally; otherwise read whole-source policy authority and assemble bounded packet | Original evidence, candidate metadata, hints and constraints | B; zero calls for skip |
| 8. `lifetime_memory_lane_engine.py:655`, `:706` | Validated page/fence | API-to-worker request under guard; worker checks role, budget, canonical payload and publication authority | Actual provider dispatch with compiled instructions/schema | B; current implementation extracts via fresh native app-server; other phases already direct Responses |
| 9. `two_lane_memory.py:37`, `lifetime_memory_lane_engine.py:193` | two-lane, strategy, attribution, reply-v2 flags | Compose governed artifacts and strict scoped schema into the same request | Event/place/question/continuity/strategy JSON | B; components do not each create calls |
| 10. `lifetime_memory_composer.py:156` | Complete provider output | Parse, schema, quotes/spans, whole-source recording veto, identity/revision and derived proposal validation; fixed retry code on failure | Validated proposal, at most two extra model requests | B; no partial proposal publication |
| 11. `lifetime_memory_composer.py:296` | Validated current page | Atomic SQL commit rechecks token, scope, policy, source and event revisions; empty/no-op advances coverage | Canonical events plus queued hints and progress | B; later interview can consume oldest pending clarification; composer uses canonical evidence |
| 12. `lifetime_memory_composer.py:274`, SQL `advance_two_lane_checkpoint` | Exhausted extraction pages | Lossless checkpoint without model, or bounded semantic summaries on prior history | Accepted context checkpoint for future A; originals remain retrievable | B; serial; can yield after eight pages per lease quantum |
| 13. `memory_event_worker.py:229` | Cancellation/failure/deadline or more work | Release/yield or durable bounded retry; preserve saved pages | Eventual catch-up, no false success | B; next source may coalesce into a later snapshot |

## Prompt inventory

All extraction components below compile into one request. Existing published pins are preserved; no feature-branch publication. Full compiled request/schema hashes are recorded per live page in local evidence. `instructions`, `contract` and `shared/grounding` are expanded by `prompt_composition.py`; extract and extract-with-hints are mutually exclusive templates. Locale policy is appended by the common lane contract. Runtime schema, envelope and fixed repair codes are host-owned Python rather than independently published model calls.

| Prompt/component | Purpose, conditions and composition | Model / effort | Published version | SHA-256 |
| --- | --- | --- | ---: | --- |
| `memoir/skills/memoir-author-timeline/instructions` | Timeline invariants; included through either extraction template. Source: `skills/memoir-author-timeline/SKILL.md` | memoir-luna-low / requested low | 3 | `c79a9bf333ef128a06db6462c28d8e1fa60e55c80f84bf4764d540970c5461e4` |
| `memoir/skills/memoir-memory-context/instructions` | SQL-protected profile targets; separate profile phase and requests. Source: `skills/memoir-memory-context/SKILL.md` | memoir-luna-low / requested low | 1 | `a28a203eb72c78943460cd65a79faffe3ec063efff27be0f513424a59063f082` |
| `memoir/skills/memoir-author-timeline/contract` | Canonical evidence, identity, revision, cursor and commit contract; template component. Source: `skills/memoir-author-timeline/references/contract.md` | memoir-luna-low / requested low | 1 | `faabc0d8bb702279984f0924263f412a7852d8639b8bee6733d859c4dbd6ae84` |
| `memoir/skills/memoir-author-timeline/derived-hints` | Private planning/photo context semantics and correction ownership; two-lane extraction. Source: `skills/memoir-author-timeline/prompts/derived-hints.md` | memoir-luna-low / requested low | 2 | `099e4117d961a2751a5d45da010ec3b4e8187b5fb7b91d655442a5dae4af68f8` |
| `memoir/skills/memoir-author-timeline/continuity` | reply-v2 continuity plus attribution/dispositions and event-place rules, same extraction request. Source: `skills/memoir-author-timeline/prompts/continuity.md` | memoir-luna-low / requested low | 1 | `e4daebd5db07d3bf93d5561c1c7d7c5528157a3c5cb1213742614592345dcbd1` |
| `memoir/skills/memoir-author-timeline/window` | Packet-level source window offsets, validator repair rules and temporal constraints; included in every extraction packet. Source: `skills/memoir-author-timeline/prompts/window.md` | memoir-luna-low / requested low | 1 | `42cc8858f0500ae355bf8db5e18361ca8b26f469ec20dd2530833d270fd1c01e` |
| `memoir/skills/memoir-author-timeline/extract-with-hints` | Two-lane extraction template; same shared components plus required derived arrays. Source: `skills/memoir-author-timeline/prompts/extract-with-hints.md` | memoir-luna-low / requested low | 2 | `38ad20878043ad6f8518404f5887e367d881b047e1cdbba481a223028835db24` |
| `memoir/skills/memoir-author-timeline/extract` | Plain extraction template when two lanes are absent; includes instructions, contract, grounding. Source: `skills/memoir-author-timeline/prompts/extract.md` | memoir-luna-low / requested low | 3 | `9a9adf7bd0fc193573fa23cdd405848a43f7005d1915ab73b9b46e42c28816ed` |
| `memoir/skills/memoir-author-timeline/attribution` | Prepared question priority, source-grounded coarse places and current conversation language; two-lane component. Source: `skills/memoir-author-timeline/prompts/attribution.md` | memoir-luna-low / requested low | 1 | `cc01a7e1ad07676fa95950c71b4ecc63bd2d4db4db530d208ac9fbc2e72d5dc9` |
| `memoir/skills/memoir-author-timeline/shared/grounding` | Exact original evidence, temporal expression, policy/veto and identity; template component. Source: `skills/memoir-author-timeline/prompts/shared/grounding.md` | memoir-luna-low / requested low | 1 | `66bedf7ad003eca9584c9c4f6432461c47d978a00cd2d550d52c184c7c551fbc` |
| `memoir/skills/memoir-place-journey/extraction` | Embedded coarse public place and bounded research hints; same extraction request. Source: `skills/memoir-place-journey/references/two-lane.md` | memoir-luna-low / requested low | 3 | `d2a4b04a177f3df72b5a90233f4c025a46bfc14870ac962f04004e0146791e4c` |
| `memoir/skills/memoir-memory-context/summary` | Selective semantic history summary with original citations; separate summarize phase dispatched on author_timeline role. Source: `skills/memoir-memory-context/prompts/summary.md` | memoir-luna-low / requested low | 1 | `01e01f507ce1888fc1bc1cf912db861c321afff05e3cd43d71341b4089a0a4d8` |
| `memoir/skills/memoir-interviewer/strategy-proposal` | Optional comfort/explore/shape proposal; same extraction request when enabled. Source: `skills/memoir-interviewer/prompts/strategy/proposal.md` | memoir-luna-low / requested low | 2 | `538cc2b6bf978ab716411ecc793a0d2aec0862b24ca23aa17b2bc296d632d860` |
| `memoir/shared/place-conflicts` | Prior conflicting place coverage; conditional extraction shared rules. Source: `apps/api/prompts/shared/place-conflicts.md` | memoir-luna-low / requested low | 1 | `8cffba4dd91a42e65e8b14dab3f5d6aa84fe926f00c00994da49e646c84a2d5f` |
| `memoir/shared/bounded-context/en-AU` | Current edition/locale and shared bounded policy; one locale variant per extraction. Source: `apps/api/prompts/shared/bounded-context/en-AU.md` | memoir-luna-low / requested low | 2 | `c19926c3affa25a3ca901990aa22ae84eda5c8b6b4d27750d235d5efaa1f9e0c` |
| `memoir/shared/bounded-context/zh-CN` | Current edition/locale and shared bounded policy; one locale variant per extraction. Source: `apps/api/prompts/shared/bounded-context/zh-CN.md` | memoir-luna-low / requested low | 2 | `b44dae81524a9ae08ab2a8ee336ec84ea512e38a0da906016f7e047c45eca863` |
| `memoir/shared/bounded-context/policy` | Shared bounded source/privacy policy expanded by locale templates. Source: `apps/api/prompts/shared/bounded-context/policy.md` | memoir-luna-low / requested low | 1 | `d92070acba1a54658b8e2f12a1b35ff12092d57c340475133e23620a189f6f2a` |

Additional host instructions: `lane_contract` constrains source IDs/versions, available event identities and relation targets, forbids invented person IDs, and supplies strict JSON schema. `_lane_context` binds edition vs conversation language, privacy, current source/event fences and snapshot. `_extract` supplies fixed `retry_reason` codes with unchanged evidence for repairs. Summary/profile schemas and fixed repair codes are separate phase contracts. Native app-server currently adds general agent developer/environment/tool instructions outside the governed prompt catalog; captured full outgoing request is the provenance for those additions. Tools are not required by this schema-only extraction. No evaluation/judge prompt is sent: semantic review is by Codex, not a claimed human or independent LLM judge.

## Measurement status

Frozen plan and raw synthetic evidence: ignored `var/optimise-author-timeline-20261024` in the primary local checkout. The current-main live comparison is below. Earlier f190c33 measurements informed the diagnostic cohort but are not substituted for the fresh baseline: the two-lane contract and schema changed since then.

## Selected change

Before: canonical page → fresh native agent/home → provider with three tool definitions → existing validator and SQL commit.

After: canonical page → existing guarded direct Responses transport with no tools → the same validator and SQL commit.

| Change and affected files | Measured cost / gain | Retained contract and dependency | Validation / rollback |
| --- | --- | --- | --- |
| Reuse direct transport in `apps/api/lifetime_memory_lane_engine.py`; extend existing transport/admission tests | First four matched cases: median input 11760 → 5998.5 tokens (49.0% lower), output 773 → 671 tokens. Native cached input was 3712 per call; candidate cached input was zero. Overall passing-subset latency below. | Same published task instructions, model/effort, exact source packet, schema, output bound, single-use guarded HTTP body, policy/owner/source/token checks, and canonical validator/commit. Future questions still require accepted hints; no deferral or reordering. | 205 focused checks; required place replay below. Revert the transport commit to roll back. Quality gate prevents merging this draft. |

Prompt compression and changing periodic profile scheduling were deferred: they alter governed instructions or a different skill. Expanding the SQL stop fast path changes semantic admission. No new cache, scheduler, dependency or provider configuration was introduced. The failed quote-coordinate experiment is absent from the final diff.

## Live before/after comparison

One live sample per scenario and arm. The three affected baseline fixtures were rerun after correcting bounded intake fields, lease renewal and policy-change release. The table uses those completed baseline rows; the original failures remain in the ledger. Both arms use their own saved correction state. Times sum private extraction-start through validated JSON across each scenario’s windows/turns; they exclude controlled Lane A intake. Durable page-save timings, tokens, hashes and all attempts are in [sanitized evidence](evidence/author-timeline-latency-20261024.json). Full synthetic source packets and outputs remain in the ignored local round directory.

| Work scenario | Requests before → after | Validated seconds before → after | Reduction | Quality / saved result |
| --- | ---: | ---: | ---: | --- |
| English childhood testimony | 1 → 1 | 49.57 → 12.31 | 75.2% | PASS — Supported childhood violin event and 1978 retained. |
| Chinese childhood testimony | 1 → 1 | 29.31 → 7.42 | 74.7% | PASS — Chinese source, childhood and 1978 retained. |
| English life period | 1 → 1 | 27.58 → 7.74 | 71.9% | PASS — Bookshop work remains a 1988–1992 period. |
| Chinese life period | 1 → 1 | 29.13 → 7.44 | 74.5% | PASS — Chinese 1988–1992 work period retained. |
| Uncertain year | 1 → 2 | 26.42 → 14.90 | 43.6% | PASS — Approximate 1983 wording and possible later year remain uncertain. |
| Scoped recording veto plus allowed memory | 1 → 1 | 27.44 → 7.17 | 73.9% | PASS — Only permitted pottery memory/place retained; vetoed residence excluded. |
| Long source, two windows, repeated quotations | 4 → 4 | 138.78 → no validated completion (failed) | not a passing latency | FAIL — Before saves both events; candidate saves window one, then rejects ambiguous evidence in window two after all three attempts. Cursor does not falsely advance. |
| Paraphrased stop outside SQL exact list | 1 → 1 | 18.40 → 5.51 | 70.1% | PASS — One model request; empty event result. |
| Saved first turn followed by date correction | 2 → 2 | 50.03 → 18.16 | 63.7% | PASS — Second turn reads its own saved event and saves 1984 on the same canonical identity. |

The **8/9 quality-passing paired subset** has median 28.36s → 7.59s (73.2% lower). This excludes the failed long-source row and cannot establish overall acceptance. Normal short inputs still use one request; total requests in the comparison are 13 → 14. The uncertain-year candidate needed one extra numeric-date repair; the long source exhausted its two ambiguous-span repairs.

All measured native requests carried three tool definitions; the direct candidate carries zero. Model route and receipt both report gpt-5.6-luna with low effort. Task instructions are unchanged. Native general agent/environment/tool framing is removed. Per-case cached-token counts are retained because cache conditions were provider-managed.

Held-out checks: attributed Chinese father memory stays unplaced and explicitly belongs to the father; uncertain Alex kinship stays unresolved without invented person IDs; exact “Please stop.” uses zero provider requests and saves no event/question. All three pass. These are candidate-only confirmation checks, not additional matched latency samples.

## Failed attempts and retained limits

The initial baseline had three fixture failures: a repaired extraction outlasted the unrenewed 60-second lease; controlled long-source intake exceeded acknowledgement/quote limits; the correction saved successfully but the profiler tried to read its obsolete policy token. Those rows were rerun after fixing only the profiler. The production worker already renews leases and releases policy-invalidated tokens.

The first direct candidate passed eight scenarios and failed the second long-source window after three ambiguous-quote attempts. A subsequent source-coordinate repair experiment also failed to establish acceptance: one run was rejected at send-time admission before its third provider dispatch, and a fresh run still exhausted validation repairs. That code was removed; it is not in the PR. These failures are retained and are not counted as successful latency improvements.

Across the round: 39 physical provider requests, one additional admission-rejected attempt without provider dispatch, zero paid policy/judge calls. The original 32-call plan was extended once to a hard 40 before the bounded follow-up; no further expansion. Cleanup receipts verify all owned database roots/processes were removed.

## Decision and acceptance

| Gate | Result |
| --- | --- |
| Faster background extraction on quality-passing cases | PASS, bounded single-sample evidence |
| Same frozen main scenarios all retain accepted output quality | FAIL, long repeated-quote second window unresolved |
| Current corrections, recording boundary, language, uncertainty and held-out attribution/identity | PASS in observed saved results |
| Strict validation / no false success on ambiguous evidence | PASS; failed window remains unfinished |
| User-visible 5-second / 10-second target and browser paint | Unobserved; this skill returns private Lane B JSON |
| Deployment / matched Temporal worker | INCONCLUSIVE; not exercised |
| Merge readiness | FAIL; PR stays draft |

Next work stays on this skill: repair the ambiguous repeated-evidence selection without relaxing exact-span validation, then repeat the long-source case and quality comparison before marking the PR ready. Prompt wording changes require the existing main-review/publication workflow. No prompt artifacts or receipts changed in this PR.


## Verification and delivery

- Focused transport/admission/budget/compatibility checks: **205 passed**, excluding PostgreSQL cases and the unchanged 10,000-packet stress loop. The earlier aggregate completed that stress loop but had one cancellation-fixture setup timeout; a one-second setup bound was raised to five seconds, and the focused checks passed. An initial baseline check also hit its 180-second outer deadline; all logs remain local.
- Required `make test-place-research`: **604 web passed; 486 backend passed**, with one failure when the module's disposable native fixture reached its deadline. The exact failing `broaden_scope` priority case then passed in a fresh fixture (**1 passed, 3 deselected**), covering all **487** backend cases without changing application code. The original make command exited 2 and is not represented as an all-green run.
- The photo-skill stage that make did not reach was run separately: **95 passed**.
- The discarded coordinate experiment had its own 207-test check; that result is not used to claim acceptance of the removed code. The retained runtime's SHA-256 exactly matches the initial measured direct candidate.
- Remote main was rechecked at `613930a263b0ed49ada3ea3b817f78d43fe81af5`. Only the transport, its tests, this report and sanitized metrics are proposed. No prompt publication, merge or deployment. Raw synthetic prompts/outputs and profiler scripts stay local under ignored `var/optimise-author-timeline-20261024`.

The PR is a draft because the long-source quality gate failed. It should remain unmerged until that case passes a renewed comparison.
