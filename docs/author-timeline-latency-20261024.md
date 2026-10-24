# Author timeline call analysis and optimization

Baseline: `613930a263b0ed49ada3ea3b817f78d43fe81af5`, current remote main at round start. Selected skill: `memoir-author-timeline`. Configured local path: two lanes, `reply-v2`, strategy enabled, background model `memoir-luna-low`, requested effort `low`. Provider receipts report low effort on both measured transports; internal provider policy remains opaque. This is a background completion study; browser delivery and deployed-worker timings are unobserved.

**Final bounded result:** implementation and live testing are finished. The nine matched main scenarios pass with median validated background extraction **29.13s → 6.64s (77.2% lower)** and **13 → 11 provider requests**. Final implementation is `f9fe4916da6a4ecd34a6b29650a234e32a3318fc`. The final held-out cohort passes two of three semantic checks: a father's reported experience still produces an unattributed Chengde map cue. Overall quality acceptance therefore **fails**, and PR #127 stays draft. No user-visible five-second result is claimed.

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
| 8. `lifetime_memory_lane_engine.py:655`, `:706` | Validated page/fence | API-to-worker request under guard; worker checks role, budget, canonical payload and publication authority | Actual provider dispatch with compiled instructions/schema | B; baseline extracts via fresh native app-server; final implementation uses guarded direct Responses |
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

Additional host instructions: `lane_contract` constrains source IDs/versions, available event identities and relation targets, forbids invented person IDs, and supplies strict JSON schema. `_lane_context` binds edition vs conversation language, privacy, current source/event fences and snapshot. `_extract` supplies fixed `retry_reason` codes with unchanged evidence for repairs. `PAGE_AMBIGUOUS` requires explicit integer evidence offsets and adds bounded original positions. `PLACE_HIERARCHY` describes the exact root/leaf format in the host-owned repair schema only; initial and unrelated requests retain their contracts. Summary/profile schemas and fixed repair codes are separate phase contracts. The baseline native app-server adds general agent developer/environment/tool instructions outside the governed prompt catalog; captured full outgoing request is the provenance for those additions. Tools are not required by this schema-only extraction. No evaluation/judge prompt is sent: semantic review is by Codex, not a claimed human or independent LLM judge.

## Measurement status

Frozen plan and raw synthetic evidence: ignored `var/optimise-author-timeline-20261024` in the primary local checkout. The completed before/after comparison is below. Earlier f190c33 measurements informed the diagnostic cohort but are not substituted for the fresh baseline: the two-lane contract and schema changed since then.

## Selected change

Before: canonical page → fresh native agent/home → provider with three tool definitions → existing validator and SQL commit.

After: canonical page → existing guarded direct Responses transport with no tools → the same validator and SQL commit.

| Change and affected files | Measured cost / gain | Retained contract and dependency | Validation / rollback |
| --- | --- | --- | --- |
| Reuse direct transport in `apps/api/lifetime_memory_lane_engine.py`; extend existing transport/admission tests | Final first four matched cases: median input 11760 → 5999.5 tokens (49.0% lower), output 773 → 702 tokens. Native cached input was 3712 per call; candidate cached input was zero. All nine main scenarios are included below. | Same published task instructions, model/effort, exact source packet, schema, output bound, single-use guarded HTTP body, policy/owner/source/token checks, and canonical validator/commit. Future questions still require accepted hints; no deferral or reordering. | 216 focused checks; required place replay below. Revert the transport commit to roll back. The held-out place-attribution issue prevents overall acceptance. |

Prompt compression and changing periodic profile scheduling were deferred: they alter governed instructions or a different skill. Expanding the SQL stop fast path changes semantic admission. No new cache, scheduler, dependency or provider configuration was introduced. The unsuccessful hints-only experiment was removed. The final implementation pairs bounded original coordinates with required repair offsets and rejects malformed event-place hierarchies before SQL.

## Completed before/after comparison

One sample per frozen scenario and arm, same route `memoir-luna-low`, requested and reported effort `low`, reported provider model `gpt-5.6-luna`. Times below sum extraction start through validated JSON across the scenario's windows/turns, including repairs. They measure private Lane B completion and exclude controlled foreground intake and separate profile/summary work. They do not measure chat delivery or browser paint.

The completed baseline uses the original run plus three fixture-recovery rows, as in the historical comparison. The original failed attempts remain in the ledger. Five main scenarios and all three held-out cases ran on final commit `f9fe491`. Four completed main cases from `2586583` are retained: their exact compiled instructions/schema are identical on final code, and replay through final attribution validation succeeds. These are not claimed as additional live samples. Per-row commits, full-record hashes, source-processing witnesses, usage and durable-save timings are in the [sanitized evidence](evidence/author-timeline-latency-20261024.json).

| Scenario | Calls before → after | Before (s) | After (s) | Reduction | Quality |
| --- | ---: | ---: | ---: | ---: | --- |
| English childhood testimony | 1 → 1 | 49.57 | 7.70 | 84.5% | PASS — Violin, childhood and 1978 retained; Hobart association grounded. |
| Chinese childhood testimony | 1 → 1 | 29.31 | 6.69 | 77.2% | PASS — Chinese violin event and 1978 retained; hierarchy ends with the source label 成都. |
| English life period | 1 → 1 | 27.58 | 6.12 | 77.8% | PASS — Bookshop employment remains a supported 1988–1992 period. |
| Chinese life period | 1 → 1 | 29.13 | 6.41 | 78.0% | PASS — Chinese bookshop period and 1988–1992 remain intact. |
| Uncertain year | 1 → 1 | 26.42 | 6.64 | 74.9% | PASS — Approximate 1983 and possible later year remain uncertain. |
| Recording veto plus allowed memory | 1 → 1 | 27.44 | 5.37 | 80.4% | PASS — Only permitted Kunming pottery is saved; vetoed Chengdu residence is excluded. |
| Long source with repeated quotations | 4 → 2 | 138.78 | 17.57 | 87.3% | PASS — Both real events saved: pottery/Hobart/1994 and weaving/Perth/1998; no fictional event. |
| Paraphrased stop | 1 → 1 | 18.40 | 3.15 | 82.9% | PASS — No event or follow-up question; the paraphrase still costs one extraction request. |
| Correction using its own saved first turn | 2 → 2 | 50.03 | 11.02 | 78.0% | PASS — Same canonical event advances from 1983 to 1984 on a later revision. |

Across all nine matched main scenarios, median validated extraction is **29.13s → 6.64s**, median extraction-through-durable-page-save is **30.06s → 6.77s**, and requests are **13 → 11**. The final long source uses two first-pass windows instead of four requests with repairs. All final main source-processing readbacks are `succeeded`. The correction starts from its own saved first event and changes the same identity from 1983 to 1984 on a later revision.

One of nine background scenarios finishes under five seconds. The long-source total (17.57s) and two-turn correction total (11.02s) exceed ten seconds. These are background totals across windows/turns; the agreed meaningful-visible-reply target remains unobserved. One sample cannot establish tail percentiles or isolate provider/cache/load effects. The baseline's first four cases each report 3712 cached input tokens; the corresponding final cases report zero. All direct requests use zero tools; the native baseline carried three.

## Final held-out review

These are candidate-only confirmation cases; there is no matched before latency. Semantic review is by Codex against the original source and saved state, supplemented by structural assertions. No separate paid judge or human review is claimed.

| Scenario | Calls | Validated / durable seconds | Quality and actual result |
| --- | ---: | ---: | --- |
| Father’s reported Chinese memory | 1 | 5.93 / 6.04 | FAIL — No narrator event or childhood placement, and exact Chinese quote survives. However Chengde is emitted as an unassociated place_journey from the father's reported experience; the cue does not retain subject attribution. |
| Uncertain Alex identity/kinship | 1 | 5.51 / 5.64 | PASS — Kite memory retained with unknown timing and unresolved identity/kinship; no person ID or definite family link. |
| Exact “Please stop.” | 0 | 0.04 / 0.14 | PASS — Zero provider submissions; no event or follow-up question. |

The father case saves no narrator event or childhood stage and retains the exact source quote, but emits `place_journeys=[承德]` without its reported subject. Its `event_places` array is empty. This is a semantic limitation in the broader extraction contract, even though schema validation and SQL saving succeed. It prevents full acceptance; the earlier passing held-out attempt is not substituted for this final failure.

## Implemented validation repairs

Repeated evidence previously returned null offsets on every repair because the schema continued to permit them. Only `PAGE_AMBIGUOUS` now narrows `EvidenceRef.char_start/char_end` to integer positions within the transmitted window. It supplies source-ID/version-scoped original sentence/line positions: at most 16 quotes, 32 positions per quote and 8192 UTF-8 bytes, from the existing maximum 2304-character window. Repeated quotes take priority. The host recomputes this helper from original text and rejects forged metadata; it never selects an occurrence or relaxes exact quote validation. Budget accounting and request manifests use the actual outgoing repair schema.

The renewed live run also exposed a Python/SQL mismatch: `place=成都` with hierarchy ending `成都市` passed Python but failed the SQL event-place check. Python now rejects noncanonical root/leaf/normalization shapes before commit, and `_extract` can repair with `PLACE_HIERARCHY`. Only that retry's schema explicitly requires the original place spelling at the hierarchy leaf. It does not silently rewrite geography. The final Chinese cases conformed on their first requests; live causal evidence for that new guidance is therefore unavailable. Controlled regression covers the repair path. The earlier `7e5975a` long-source live run did exercise `PAGE_AMBIGUOUS` and then save both windows; the final long-source sample needed no repair.

No managed prompt Markdown or published receipt changed. These are transport, host validation, bounded source data and runtime schema changes. Publication, merge and deployment remain outside this round.

## Verification

- **216 focused checks passed** on the final file contents committed as `f9fe491`, covering direct transport/admission, timeline job/capacity behavior, repeated evidence and four new place-repair cases.
- **`make test-place-research` passed** on those contents: 604 web, 487 backend and 95 photo-skill checks, including API-to-client replay.
- The preceding span repair passed **6 real disposable-PostgreSQL cases** on `7e5975a`: rejection preserves the first saved window and cursor; a new lease resumes; English/Chinese second-occurrence selection works; wrong integer spans, stale owner/source and withdrawal fail closed. The final place-only repair does not alter those paths.
- Final live extraction/admission/commit uses canonical code plus disposable PostgreSQL and the actual configured gateway. Foreground policy/reply and the HTTP worker seam are controlled fixtures. A deployed worker, Temporal and browser are not exercised.
- Exact final-code contract equality and attribution replay verify the four retained main cases. All owned runtime cleanup receipts report verified removal/stopped processes. Temporary dependency symlinks were removed.

The first final-guidance check launch accidentally selected Homebrew Python 3.14 without installed `pytest`/`httpx`: its focused launch failed and six web planning checks failed. The complete rerun with the installed Python 3.12 passed; both original check receipts are retained. The earlier red regression and fixture failures also remain recorded.

## Retained failures and call budget

The historical phase used 39 forwarded provider attempts and one additional admission-rejected submission. Its initial 32-call plan was extended once to 40; the original transport candidate passed 8/9 and exhausted repeated-quote repairs. Two unsuccessful hints-only experiments were removed from production. The original baseline fixture failures involved a short lease, oversized controlled-intake fields and an obsolete policy token; their corrected recovery rows are explicit.

The user's renewed request authorized a separate frozen **36-submission** segment. It finished with **35 submissions / forwarded provider attempts**, zero paid policy calls and zero paid judges:

| Run | Code | Attempts | Outcome |
| --- | --- | ---: | --- |
| Implemented span repair | `7e5975a` | 14 | 11/12 SQL completions; long source recovered after one repair; Chinese hierarchy reached SQL and failed. |
| Strict Python hierarchy validation | `2586583` | 12 | Chinese hierarchy repeated through two repairs and failed closed. Run stopped during the long-source retry; cancellation and cleanup retained. |
| Final affected cases plus exact stop | `f9fe491` | 7 | All six cases complete; five main cases and exact-stop skip. |
| Final remaining held-outs | `f9fe491` | 2 | Both save; one semantic pass and the father-place cue failure above. |

Across both segments there are **74 forwarded provider attempts** plus the historical rejected admission. The cancelled attempt is counted conservatively and not claimed as a successful response. No failure is scored as a latency improvement. Full synthetic requests, responses and saved-state witnesses remain local under ignored `var/optimise-author-timeline-20261024`; the public JSON exports metrics, hashes and concise synthetic excerpts rather than raw provider packets.

## Decision and remaining gate

| Gate | Result |
| --- | --- |
| Faster background extraction | PASS — 77.2% lower median across nine matched main scenarios, single-sample evidence. |
| Main scenario quality and eventual source processing | PASS — 9/9. |
| Held-out semantic quality | FAIL — 2/3; father’s place cue lacks subject attribution. |
| Strict spans, ownership/policy and durable commit fences | PASS in observed live/offline coverage. |
| Meaningful visible text within five seconds | INCONCLUSIVE — not measured by this Lane B study. |
| Browser/deployed-worker/Temporal acceptance | INCONCLUSIVE — not exercised. |
| Overall acceptance / merge readiness | FAIL — keep PR #127 draft. |

Next work stays on this skill: preserve the subject of reported place cues, then repeat the failed held-out case in a newly bounded live round. Any managed prompt wording change must follow review/merge/publication on `main`. The remaining one submission is not enough to validate another implementation and its repairs under the current plan; no further calls are made.

Remote `main` advanced to `fcd7fb499cbbb8be79bdf936dc04ed885a50258c` with story-game/speech work. The additional commit since the previously observed `23eade7` changes only story-game code/tests and its SQL functions. The measured timeline modules/functions remain unchanged. Tests ran on the dedicated PR branch based on `613930a`; no integration with the newer main is claimed. Root-checkout speech work was preserved.
