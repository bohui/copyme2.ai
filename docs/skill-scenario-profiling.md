# Skill and work-scenario profiling matrix

As of 24 October 2026: **83 rows across 10 skills**. Updated after each profiling round.

- Before/after are paired within each named round, with its own configuration, not a single shared deployment revision.
- Times are seconds unless marked milliseconds. The work-measured column names the boundary: acknowledgement/reply, whole case, save/readback or photo first/completion.
- A failed baseline duration is time to failure, not successful-response latency.
- Baseline-only, new held-out, unavailable, unwired and pending states stay explicit; missing timing is never zero.
- Cold and warm cache are distinct baseline conditions, not before/after an implementation.
- Most scenarios have one sample per arm. Provider/cache/load drift remains; no production percentile guarantee.
- Latest handoff values use merged main b8d797d and published reply v4, privacy/repair v6; serial policy/reply on isolated low route. Shared service settings unchanged.
- A per-case quality pass is not full skill acceptance. Full source reports retain failures, call budgets, retries, interrupted runs, provenance and cleanup.
- Round10 completed28 prepared cases plus2 diagnostics:26 pass,3 fail,1 inconclusive overall; generic continuation on a stop is not a meaningful stop response. Prior77-row scorecard preserved in the raw evidence archive.

| skill name | work measured | before | after | result |
| --- | --- | --- | --- | --- |
| memoir-interviewer | 22 Oct parallel trial — english opening (retained acknowledgement / final save) | 9.41s ack / 9.72s save | 6.27s ack / 6.63s save | Quality passed this case; historical cohort, latest combined flow unverified |
| memoir-interviewer | 22 Oct parallel trial — english later (retained acknowledgement / final save) | 8.65s ack / 9.25s save | 5.62s ack / 6.05s save | Quality passed this case; historical cohort, latest combined flow unverified |
| memoir-interviewer | 22 Oct parallel trial — english privacy (retained acknowledgement / final save) | 13.54s ack / 13.86s save | 11.51s ack / 11.96s save | Quality passed this case; retained acknowledgement exceeds 10s |
| memoir-interviewer | 22 Oct parallel trial — english resumed (retained acknowledgement / final save) | 8.01s ack / 8.38s save | 4.38s ack / 4.74s save | Quality passed this case; historical cohort, latest combined flow unverified |
| memoir-interviewer | 22 Oct parallel trial — english stop (retained acknowledgement / final save) | 7.14s ack / 11.84s save | 8.26s ack / 8.60s save | Quality passed; retained acknowledgement slower |
| memoir-interviewer | 22 Oct parallel trial — english correction (retained acknowledgement / final save) | failed 19.00 | failed 55.35 | FAIL: correction after stop unresolved; original failures retained |
| memoir-interviewer | 22 Oct parallel trial — chinese opening (retained acknowledgement / final save) | 10.14s ack / 10.69s save | 5.35s ack / 5.75s save | Quality passed this case; historical cohort, latest combined flow unverified |
| memoir-interviewer | 22 Oct parallel trial — chinese later (retained acknowledgement / final save) | 16.50s ack / 16.92s save | 5.60s ack / 5.96s save | Quality passed this case; historical cohort, latest combined flow unverified |
| memoir-interviewer | 22 Oct parallel trial — chinese privacy (retained acknowledgement / final save) | 12.28s ack / 12.77s save | 18.54s ack / 18.96s save | Quality passed this case; retained acknowledgement exceeds 10s |
| memoir-interviewer | 22 Oct parallel trial — chinese resumed (retained acknowledgement / final save) | 8.09s ack / 14.23s save | 5.81s ack / 6.22s save | Quality passed this case; historical cohort, latest combined flow unverified |
| memoir-interviewer | 22 Oct parallel trial — chinese stop (retained acknowledgement / final save) | 8.16s ack / 12.74s save | 14.94s ack / 15.40s save | Quality passed this case; retained acknowledgement exceeds 10s |
| memoir-interviewer | 22 Oct parallel trial — chinese correction (retained acknowledgement / final save) | 84.91, policy incorrect | failed 61.55 | FAIL: correction after stop unresolved; original failures retained |
| memoir-interviewer | Current handoff — English ready-news selection (validated reply) | 6.62s (quality failed) | 9.72s (reply v4) | PASS after one validation repair; ready cited clue selected; prior v3 recovery: 7.09s |
| memoir-interviewer | Current handoff — English conflicting dates (validated reply) | 5.50s | 5.72s (reply v4) | Quality PASS; original sources and earlier reply retained; prior v3 recovery: 5.05s |
| memoir-interviewer | Current handoff — English person identity clarification (validated reply) | 15.28s (quality failed) | 4.02s (reply v4) | Quality PASS; original sources and earlier reply retained; prior v3 recovery: 4.51s |
| memoir-interviewer | Current handoff — English event ordering (validated reply) | 5.12s | 4.73s (reply v4) | Quality PASS; original sources and earlier reply retained; prior v3 recovery: 4.35s |
| memoir-interviewer | Current handoff — English topic/period expansion (validated reply) | Failed; no validated reply | 4.43s (reply v4) | Quality PASS; original sources and earlier reply retained; prior v3 recovery: 4.48s |
| memoir-interviewer | Current handoff — English explicit stop (validated reply) | 4.55s | 5.67s (reply v4) | Quality PASS; original sources and earlier reply retained; prior v3 recovery: 4.86s |
| memoir-interviewer | Current handoff — English explicit topic redirection (validated reply) | 4.75s | 5.75s (reply v4) | Quality PASS; original sources and earlier reply retained; prior v3 recovery: 5.68s |
| memoir-interviewer | Current handoff — English privacy exclusion + topic redirection (validated reply) | 5.35s | 12.02s (reply v4) | Quality PASS;12.02s exceeds10s target; prior v3 recovery: 6.42s |
| memoir-interviewer | Current handoff — Chinese ready-news selection (validated reply) | 12.70s (quality failed) | 11.47s (reply v4) | FAIL: same-period invitation still treated as a topic change; clue skipped after repair; prior v3 recovery: 5.85s |
| memoir-interviewer | Current handoff — Chinese conflicting dates (validated reply) | 8.23s | 4.83s (reply v4) | Quality PASS; original sources and earlier reply retained; prior v3 recovery: 5.02s |
| memoir-interviewer | Current handoff — Chinese person identity clarification (validated reply) | 5.56s | 5.09s (reply v4) | Quality PASS; original sources and earlier reply retained; prior v3 recovery: 5.02s |
| memoir-interviewer | Current handoff — Chinese event ordering (validated reply) | 4.87s | 9.96s (reply v4) | Quality PASS; original sources and earlier reply retained; prior v3 recovery: 5.12s |
| memoir-interviewer | Current handoff — Chinese topic/period expansion (validated reply) | Failed; no validated reply | 6.29s (reply v4) | Quality PASS; original sources and earlier reply retained; prior v3 recovery: 5.17s |
| memoir-interviewer | Current handoff — Chinese explicit stop (validated reply) | 5.26s | 4.86s (reply v4) | Quality PASS; original sources and earlier reply retained; prior v3 recovery: 4.34s |
| memoir-interviewer | Current handoff — Chinese explicit topic redirection (validated reply) | Failed; no validated reply | 5.86s (reply v4) | Quality PASS; original sources and earlier reply retained; prior v3 recovery: 5.40s |
| memoir-interviewer | Current handoff — Chinese privacy exclusion + topic redirection (validated reply) | 7.06s | 8.74s (reply v4) | Quality PASS; original sources and earlier reply retained; prior v3 recovery: Failed: provider HTTP 502 |
| memoir-interviewer | Fresh control then repeat — English person identity clarification (validated reply) | No older matched baseline | 5.00s; repeat 6.13s; v4 6.42s | PASS all three observations; repeated controls, no longer unseen |
| memoir-interviewer | Fresh control then repeat — English explicit topic redirection (validated reply) | No older matched baseline | 4.74s; repeat 4.10s; v4 4.63s | PASS all three observations; repeated controls, no longer unseen |
| memoir-interviewer | Fresh control then repeat — English privacy exclusion + topic redirection (validated reply) | No older matched baseline | 5.36s; repeat 6.24s; v4 7.21s | PASS all three observations; repeated controls, no longer unseen |
| memoir-interviewer | Fresh control then repeat — English explicit stop (validated reply) | No older matched baseline | 4.58s; repeat 4.78s; v4 5.42s | PASS all three observations; repeated controls, no longer unseen |
| memoir-interviewer | Fresh control then repeat — Chinese person identity clarification (validated reply) | No older matched baseline | 4.55s; repeat 5.26s; v4 5.53s | PASS all three observations; repeated controls, no longer unseen |
| memoir-interviewer | Fresh control then repeat — Chinese explicit topic redirection (validated reply) | No older matched baseline | 6.04s; repeat 5.28s; v4 5.73s | PASS all three observations; repeated controls, no longer unseen |
| memoir-interviewer | Fresh control then repeat — Chinese privacy exclusion + topic redirection (validated reply) | No older matched baseline | 5.02s; repeat 6.02s; v4 5.44s | PASS all three observations; repeated controls, no longer unseen |
| memoir-interviewer | Fresh control then repeat — Chinese explicit stop (validated reply) | No older matched baseline | 4.40s; repeat 5.64s; v4 4.50s | PASS all three observations; repeated controls, no longer unseen |
| memoir-interviewer | Invalid completed privacy span → reassessment + reply (English) | Rejected [0,40) for a 39-character quote; no reply | 7.14s | PASS: controlled replay of actual bad output, then two live calls; exact [0,39) accepted |
| memoir-interviewer | Latest general conversation baseline: opening/later/privacy/resume; interrupted stop | Four English turns delivered; fifth interrupted | No matched candidate cohort | INCONCLUSIVE: interrupted baseline is retained, not acceptance |
| memoir-interviewer | PR120 reply v4 — original28-case live confirmation (validated meaningful reply) | v3 recovery:14/16 originals passed;8/8 controls | 28/28 saved;25pass,2fail,1inconclusive;5.67s passing median | FAIL full acceptance:7/25 within5s;24/25 within10s; no latency improvement established |
| memoir-interviewer | Deployed API/worker/proxy; pre-rollout resume, rollback and browser paint | Not established on latest combined version | Not established | PENDING acceptance coverage |
| memoir-author-timeline | English childhood/1978 extraction → SQL save | 17.26s | 22.56s | Quality PASS; application slower by 30.7% |
| memoir-author-timeline | Chinese childhood/1978 extraction → SQL save | 15.82s | 15.80s | Quality PASS; effectively unchanged latency |
| memoir-author-timeline | English 1988–1992 bookshop extraction → SQL save | 59.53s to failure | 17.96s | Baseline FAILED after 3 attempts; candidate saved after 1; not valid-latency comparison |
| memoir-author-timeline | Chinese 1988–1992 bookshop extraction → SQL save | 53.33s | 23.71s | Quality PASS; 55.6% faster; 3→1 attempts; research window retained |
| memoir-author-timeline | English two-source saved-state continuation (whole case) | No matched before measurement | 35.15s | PASS saved-state preservation; two extraction roots completed |
| memoir-author-timeline | Chinese unique-padding/nonzero-window extraction (whole case) | No matched before measurement | 26.73s | Event/span save passes; optional derived-span repair not observed; attribution remains unresolved |
| memoir-author-timeline | Chinese repeated-placeholder attribution: clearer retry feedback (whole case) | 25.31s to failure | 33.35s to failure | FAIL: ambiguous original spans still rejected after 3 attempts; no completion gain |
| memoir-place-journey | Place cues and research date-window extraction inside timeline pass | Shared timeline request; no separate timing | Shared timeline request; no extra call | Embedded contract exercised by timeline cases; no independent skill speedup claimed |
| memoir-memory-context | English opening profile → saved readback | 30.94s | 11.21s | PASS; 63.8% faster; six supported narrator fields |
| memoir-memory-context | Chinese opening profile → saved readback | 16.70s | 7.76s | PASS; 53.5% faster; exact names/date/place preserved |
| memoir-memory-context | English saved-profile correction, five-turn case → readback | 22.84s | 14.79s | PASS; 35.2% faster; saved correction and zero-call neutral turns |
| memoir-memory-context | Chinese protected profile / relative facts → readback | 12.49s | 6.76s | FAIL quality despite faster save: unknown birth-date expression still stored |
| memoir-memory-context | English saved-prior selective summary → readback | 38.95s | 22.59s | PASS final checkpoint; 42.0% faster |
| memoir-memory-context | Chinese correction summary → readback | 31.78s | 23.25s | Final checkpoint PASS, 26.8% faster; intermediate citation weakness remains |
| memoir-memory-context | Chinese nonzero-window profile (whole case) | No matched before measurement | 10.62s | FAIL: required birth-date expression omitted |
| memoir-memory-context | English attributed summary (whole case) | No matched before measurement | 16.16s | PASS: aunt/narrator attribution and uncertain dates kept separate |
| memoir-memory-context | Chinese intermediate correction citation (semantic coverage, untimed) | Blue correction cites only purple original | Same intermediate weakness | FAIL: later correct checkpoint does not clear intermediate citation defect |
| memoir-composer | English round 5: prepare + draft + review → saved chapter | 68.29s | 27.56s | 59.6% faster; PASS this checkpoint |
| memoir-composer | English round 10: prepare + draft + review → saved chapter | 75.65s | 27.61s | 63.5% faster; FAIL: unrelated school paragraph rewritten |
| memoir-composer | Chinese round 5: prepare + draft + review → saved chapter | 65.75s | 25.22s | 61.6% faster; PASS this checkpoint |
| memoir-composer | Chinese round 10: prepare + draft + review → saved chapter | 78.94s | 52.58s | 33.4% faster; PASS after 2 repair calls; unsupported chronology rejected then removed |
| memoir-composer | English protected/attributed continuation (two-checkpoint case) | No matched before measurement | 64.13s to incomplete | INCOMPLETE: budget stopped final review/save; attribution prose unverified |
| memoir-composer | Chinese protected/attributed continuation (two-checkpoint case) | No matched before measurement | 53.55s | Protected SQL bytes PASS; unsupported quantity wording; full quality not passed |
| memoir-composer | English selected outline: 2 leaves + merge → saved readback | 19.88s | Not implemented / not measured | Baseline quality PASS; transport proposal pending |
| memoir-composer | Chinese selected outline: 2 leaves + merge → saved readback | 14.32s | Not implemented / not measured | Baseline quality FAIL: unsupported childhood stage; source-language fixture also needs confirmation |
| memoir-historical-news-research | English Sydney/2000 discovery + source inspection + SQL finish | 36.41s | No optimisation measured | FAIL usefulness: zero verified clues; strict unsafe/unsupported-source rejection holds |
| memoir-historical-news-research | Chinese Sydney/2000 discovery + source inspection + SQL finish | 31.34s | No optimisation measured | FAIL usefulness: zero verified clues; strict unsafe/unsupported-source rejection holds |
| memoir-historical-news-research | Successful evidence-cache hit and actual discovered-clue → later question | No successful discovery/cache witness | Not measured | PENDING: fixture-ready news in interviewer tests is separate from actual discovery |
| memoir-place-photo-research | English Chengde/1980s cold search (first candidate / completion) | 60.335s / 60.337s | No optimisation measured | FAIL: map, contradictory locality, and failure→time-relaxation bug; no 1980s match |
| memoir-place-photo-research | English Chengde/1980s warm cache (first candidate / completion) | 0.011s / 0.011s | No optimisation measured | FAIL: map, contradictory locality, and failure→time-relaxation bug; no 1980s match; cache made zero new calls |
| memoir-place-photo-research | Chinese Sydney/current cold search (first candidate / completion) | 17.471s / 21.932s | No optimisation measured | PARTIAL: 1/10 candidates; semantic/rights verification incomplete |
| memoir-place-photo-research | Chinese Sydney/current warm cache (first candidate / completion) | 0.002s / 0.002s | No optimisation measured | PARTIAL: 1/10 candidates; semantic/rights verification incomplete; cache made zero new calls |
| memoir-place-photo-research | Wrong-owner photo cursor rejection | 1.85ms | No optimisation measured | PASS isolation control: HTTP422; zero provider work |
| memoir-place-photo-research | Shared persistent cache / authenticated deployed worker / browser paint | Not established | Not established | PENDING; in-memory warm reuse is the measured scope |
| memoir-place-groups | Deterministic place grouping on place change | Not profiled | Not profiled | PENDING timing; no LLM call to optimise |
| memoir-family-tree | Relationship-evidence → family tree | Not applicable | Not applicable | UNWIRED in production registry; excluded until integrated |
| memoir-story-game | Explicit game action → adaptation/review/private result | Not profiled in this campaign | Not profiled | PENDING; intentionally last |
| memoir-interviewer | Fresh English same-period invitation with ready news (validated reply) | No matched older baseline | 9.40s | Quality PASS: Selects the ready cited clue and optional invitation without assuming the narrator attended the public fair. |
| memoir-interviewer | Fresh Chinese same-period invitation with ready news (validated reply) | No matched older baseline | 5.35s | Quality PASS: Selects the ready cited clue, invites memories neutrally, and says remembering is optional. |
| memoir-interviewer | Fresh English redirect after prior SQL-ready news (validated reply) | No matched older baseline | 5.05s | INCONCLUSIVE: Actual reply correctly follows Sydney over the remaining school hint, but canonical revalidation removed the prior SQL-ready news clue before reply input. Does not establish the intended ready-news-versus-redirect precedence gate. Failed zero-call original setup and controlled-prior-fixture amendment retained. |
| memoir-interviewer | Fresh Chinese stop with ready news in model input (validated reply) | No matched older baseline | 4.76s | FAIL: No question, no news card, and pause outcome saved, but visible reply says we can continue reminiscing at your pace instead of acknowledging the explicit stop. This generic wording cannot qualify as meaningful stop acknowledgement. The ready-news schema allows only this continuation literal; not a demonstrated PR120 regression. |
| memoir-interviewer | Diagnostic English redirect with ready news in model input (validated reply) | No matched older baseline | 14.68s | Quality PASS: Actual reply input contains the ready news clue and both prepared hints. Follows explicit Sydney-arrival topic instead, no news card or assumption of attendance; prior and source/state witnesses preserved. Meaningful validated reply14.68s exceeds target. |
| memoir-interviewer | Diagnostic English stop with ready news in model input (validated reply) | No matched older baseline | 4.55s | FAIL: Actual reply input has ready news. Model saves pause and no question/card, but its sole visible line says we can keep following your memories at your pace. This fails clear stopping acknowledgement; a generic continuation line is not meaningful stop text. Existing news acknowledgement enum forces this sole English literal. |

Evidence:
- [report.md](test-evidence/issue53-parallel-reply-20261022/report.md)
- [lane-b-handoff-confirmation-20261024.md](lane-b-handoff-confirmation-20261024.md)
- [lane-b-handoff-comparison-20261024.md](lane-b-handoff-comparison-20261024.md)
- [optimise-all-skills.md](optimise-all-skills.md)
- [lane-b-selected-outline-baseline-20261024.md](lane-b-selected-outline-baseline-20261024.md)
- [lane-b-photo-research-20261023.md](lane-b-photo-research-20261023.md)
- [background_skills.py](../apps/api/background_skills.py)
