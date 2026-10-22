# Parallel privacy review and reply streaming: 22 October 2026

**Activation gate: fail.** The approved concurrent flow is implemented and its
controlled regression checks pass. Six ordinary opening/later/resumed replies
improved from a median **9.03s to 5.61s** for a complete, retained acknowledgement
(38%). The complete cohort still has quality failures and replies over 10 seconds.
`MEMORY_SPARK_PARALLEL_POLICY_REVIEW` remains off by default. No running service,
prompt version or hosted data was changed.

These live measurements apply to candidate `9e73dfe7c981c69c4f6324c0754bb3761f125639`.
The branch subsequently integrated main `1610dc5c820838c5d25f8e8c2f5bab4f924cc445`,
which includes PR #112's shorter privacy and repair prompts. That combined prompt
and concurrency flow needs a fresh live comparison before activation; the timings
below are historical evidence, not measurements of the updated branch.

The combined branch passed 325 regression tests covering API/worker execution,
SQL guards, browser revisions, privacy review, targeted repairs and prompt
composition/publication behavior. These tests use controlled providers and
reviewed local prompt text. Runtime publication is still pending for main's
`policy-review`, `policy-review-opening` and `repair-codes` artifacts: their local
receipts are outdated or absent. No prompt versions were published from this
feature branch.

## What was measured

Baseline: main `9c77d279d06ef2970fddad5b366850bae0f30239`, extracted to a plain
temporary source directory. Candidate: the original `9e73dfe` application source; content
hashes are in [evidence.json](evidence.json). Both use the existing published
prompts, `gpt-5.6-luna-pooled` and requested `low` effort. Effective provider effort
is unverified. PR #112's prompt shortening is not included.

Each arm ran the same [frozen bilingual sequence](live-cases.json): opening,
later narration, privacy exclusion, resumed narration, explicit stop and a
location correction after stop. Stop and correction were held out from tuning.
Each arm consumed its own saved previous replies. A new runtime and UserStorage
were created for every turn, including resumed turns. These are live model calls
through the canonical API/ASGI path, with real disposable PostgreSQL and a local
PostgREST adapter. Model generation ran in process. They are **not deployed-worker
or full browser latency measurements**; Lane B completion was not measured.

There is one observation per case per arm. Baseline ran before candidate, so load,
cache and output variation confound the comparison. Reported cached input tokens
were 2,816 baseline and 2,944 candidate; cache state was not controlled. No p95 or
universal speed/quality claim is supported.

The comparable response milestone is delivery of the **complete acknowledgement
retained in the final saved reply**, using ASGI event times. This milestone was
selected during analysis of captured streams; cases and semantic rubrics were
frozen before dispatch. Raw first tokens, progress and subsequently deleted drafts
do not satisfy it. Failure rows and the baseline's incorrect policy decision are
excluded from passing medians, but remain in the 12-case target denominator.

## Results

Times in seconds. “Done” includes final application save/response; browser paint
is unobserved. A dash means no qualifying final reply.

| Language / case | Baseline retained ack | Candidate first draft text | Candidate retained ack | Baseline done | Candidate done |
| --- | ---: | ---: | ---: | ---: | ---: |
| English opening | 9.41 | 6.09 | 6.27 | 9.72 | 6.63 |
| English later | 8.65 | 5.50 | 5.62 | 9.25 | 6.05 |
| English privacy | 13.54 | 5.79 | 11.51 | 13.86 | 11.96 |
| English resumed | 8.01 | 4.33 | 4.38 | 8.38 | 4.74 |
| English stop | 7.14 | 4.41 | 8.26 | 11.84 | 8.60 |
| English correction | — | 4.89 | — | failed 19.00 | failed 55.35 |
| Chinese opening | 10.14 | 5.22 | 5.35 | 10.69 | 5.75 |
| Chinese later | 16.50 | 5.47 | 5.60 | 16.92 | 5.96 |
| Chinese privacy | 12.28 | 18.42 | 18.54 | 12.77 | 18.96 |
| Chinese resumed | 8.09 | 5.73 | 5.81 | 14.23 | 6.22 |
| Chinese stop | 8.16 | 4.13 | 14.94 | 12.74 | 15.40 |
| Chinese correction | — | 5.63 | — | 84.91, policy incorrect | failed 61.55 |

Both arms passed semantic review for the same 10 of 12 cases. On that matched
subset, median retained acknowledgement improved **9.03s → 6.04s**, 33% (2.99s).
Across the full denominator, quality-passing replies within 5s were **0/12 → 1/12**;
within 10s, **6/12 → 7/12**. Candidate English privacy, Chinese privacy and Chinese
stop exceed 10s; both corrections fail. Earlier text on a rejected revision is
not credited as a successful fast reply.

## Actual responses and quality

All exact requests, provider outputs, partial cancelled streams, visible stream
events, source records, saved results and prior saved snapshots are retained in
[evidence.json](evidence.json)'s referenced per-run JSONL files (one complete call
or turn per line). Completed provider outputs are stored once rather
than duplicating their full SSE wire representation; raw local captures are
hashed there. Opaque encrypted provider continuation blobs are represented by
their byte lengths and hashes; all output text remains intact. Synthetic examples:

| Case | Baseline final response | Candidate final response |
| --- | --- | --- |
| English later | “You first rented a small room near the harbour, feeling both excited and lonely.” / “What do you remember most about living in that room?” | “At first, you rented a small room near the harbour and felt both excited and lonely.” / “What was that room like?” |
| English resumed | “After three weeks, you found work repairing bicycles.” / “What do you remember about your first day repairing bicycles?” | Same factual acknowledgement / “What do you remember about getting that bicycle-repair job?” |
| English privacy | “Understood—I won’t bring up your father again. We’ll focus on your move to Sydney.” / “What stands out most to you about moving to Sydney?” | “Understood—I won’t mention your father again. We’ll focus on your move to Sydney.” / “What do you remember most about arriving and settling into that small room near the harbour?” |
| Chinese later | “起初，您在海港附近租了一个小房间，当时既兴奋又孤单。” / “那间小房间是什么样的？” | “起初，你在海港附近租了一个小房间，既兴奋又孤单。” / “那段时间，你每天的生活是怎样的？” |
| Chinese privacy | “好的，我们聊搬到悉尼的经历。” / “你刚搬到悉尼时，最先遇到的事情是什么？” | “好的，我会尊重这个界限，接下来只聊你搬到悉尼的经历。” / “搬到悉尼后，你最先需要适应的是什么？” |

The coding agent reviewed these outputs against the frozen facts, language,
question usefulness, stop and privacy rubrics; this was not independent human or
blind review. Completed candidate replies retained source facts and mixed
feelings, avoided excluded topics in questions and respected explicit stopping.
All captured earlier saved collectors remained unchanged in both arms. The
browser regression separately verifies that the earlier “XXXXX” bubble's markup
is unchanged when the current draft is erased and replaced.

**Failures remain acceptance failures:**

- English correction after stop exhausted three validation attempts in both
  arms. Candidate attempts alternated between `current_correction` with a null
  question and a pause with an invalid current quote. Final saving stayed closed.
- Chinese baseline correction completed only after three attempts, but privacy
  review incorrectly marked the entire location correction as an excluded topic.
  A completed response is insufficient acceptance for that row.
- Chinese candidate correction failed after a validation rejection and a repair
  whose reported output was 8,426 tokens, exceeding the requested/accounted 8,192.
  Its early correct-looking acknowledgement was discarded, not counted as passing.
- Candidate Chinese privacy had an incomplete replacement generation before the
  successful replacement; Chinese stop needed two validation repairs. These cause
  real regressions in those observed completion/retained-text times.

No prompt or validation rule was tuned to the held-out failures. They identify
the next work for this same skill: reconcile pause/correction contract guidance,
reduce repair loops and investigate policy false positives before activation.

## Calls, prompts and boundaries

Normal policy review still uses 2,753 instruction characters. The serialized
normal reply developer instruction uses 1,985 characters (the source artifact has
a trailing newline). Repair instructions expand reply calls to 5,229–5,393
characters in this cohort. Thus the normal reply instruction fits below 2k;
**all foreground instructions across both calls do not**. This concurrency change
does not shorten any prompt or move privacy to Lane B. Per-request instruction
and schema hashes, full bodies, model and usage are in the evidence.

Baseline dispatched 31 provider calls; candidate dispatched 33, including two
cancelled speculative replies, an incomplete generation and the over-budget
repair. Reported usage was baseline 52,834 input + 23,705 output tokens; candidate
51,597 input + 26,353 output. Candidate has three calls without final usage, so
these totals cannot establish total billed usage or a cost improvement.

There were **68 total calls** including failed harness runs: initial setup failure
used zero; an accounting-capture failure used four; baseline-r3 used 31;
candidate used 33. The hard global request cap was extended from 64 to 80 before
candidate, with its reason retained in the local plan. Per-call timeout was 60s,
per-turn 150s and arm deadline 1,200s. No judge calls were made. Actual requests
asked for at most 3,000 policy or 8,192 reply output tokens, but the gateway
reported exceeding those requested limits in two calls. Provider-enforced token
or spend caps therefore remain unverified. Unknown interrupted usage is not zero.

## Verification and reproduction

Observed checks:

- Focused API/SQL/runtime/transport/browser suite: **273 passed**.
- Integrated Chromium renderer + actual `agentTurn`/stream parser: **6 passed**
  (synthetic API frames, no live model or full authenticated app).
- `make test-place-research`: **600 JS, 429 API/database, 95 standalone passed**.
- `make prompt-check`: **92 existing published pins verified**; no receipt changes.
- A broader configuration run retains **32 existing failures**, with the identical
  failing test names reproduced on frozen main. They reference retired runtime
  helpers such as `_resolve_language`; they were not fixed in this PR.

Exact isolated commands, failures and cleanup receipts are in `evidence.json`.
All disposable database runs report verified cleanup. The task-owned baseline
source directory is removed after evidence export; its source commit remains
available through Git. Raw local captures remain under ignored
`var/issue53-parallel-reply-20261022/`.

The [harness snapshot](profile-harness.py) was captured after the candidate run;
the baseline's exact pre-cap-extension harness hash was not captured. Evaluation
helpers and application/prompt content hashes are included in the dependency
inventory. To repeat deliberately, copy the harness and cases to a **new ignored
`var/<round>/` directory**, use its `live.py SOURCE_ROOT baseline|candidate RUN`
arguments, and supply the existing local `.env` gateway configuration. Preserve
each run file; the harness refuses overwrites. Running it makes paid model calls.
Do not substitute its controlled storage adapter for a deployed-worker acceptance
run or treat an enabled flag as evidence of a deployed matching schema.

| Gate | Outcome |
| --- | --- |
| Concurrent review/generation; review before final save | Pass in controlled direct/worker and live API evidence |
| Current-bubble-only retraction, stale-frame rejection, cache/Unicode/reduced motion | Pass in controlled SQL/API/Chromium tests |
| Bilingual source/stop/privacy quality across all 12 cases | Fail: correction cases remain unresolved |
| Meaningful reply ideally ≤5s, otherwise ≤10s | Fail: 1/12 ≤5s, 7/12 ≤10s; failures retained |
| Live deployed-worker, browser-paint and Lane B completion | Unverified |
| Safe activation | Pending; flag remains disabled |
