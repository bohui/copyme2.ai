# Issue 53: quality-first follow-up — 11 October 2026 (Sydney)

## Result

The reproducible implementation gaps from the [PR 54 review](issue53-pr54-verification-20261011.md)
are addressed locally, with additional safe preparation and recovery fixes.
**Issue 53 is not ready to close or enable an optimized default.**
Neither exploratory live comparison establishes faster usable replies across the workload.
The normal model, maximum effort, full legacy prompt, shared key policy and service settings
were not changed. No customer memoirs, GitHub issue state or deployments were modified.

The implementation and deterministic checks apply to future collector generations,
including populated resumed conversations. They do not regenerate saved exchanges.
This is a local uncommitted implementation, not a deployed improvement or CI result.

## Source and experiment pins

Checkout: `20dbeb40143409ca7882756dcf7281309c9b94ab`.
The checkout advanced from `24e1edf` while working because PR 56 was merged elsewhere;
its frontend/account changes were preserved.

| Pilot | Loaded comparison | Source SHA-256 | Dispatch / save / fail |
| --- | --- | --- | --- |
| Prompt only | Same pooled model, max, legacy vs compact-v1 | `7462ed45b9241c7dea912ddad1206ef9902a7818464045fdab9dfbebcff107c8` | 7 / 6 / 1 |
| Routing only | Same underlying model, legacy prompt, pooled/max vs dedicated/low | `5bb8521e39c93842401ccf62a63847a6d96996bb73a04c14e99ad5403eac35c0` | 24 / 24 / 0 |

Each stage froze 24 planned foreground generations, at most 48 application
app-server turns (including bounded correction), 120 seconds per generation and
1,200 seconds for the campaign. Each stops at its first failed generation.
These are **application dispatch budgets, not proven upstream request budgets**:
provider retries can happen inside one app-server turn. Actual foreground dispatches
across both stages were 31. The combined low/compact candidate was not dispatched
after the separate stages failed to establish acceptance.

Raw safe records:
[prompt-only pilot](issue53-quality-first-pilot-20261011.json),
[routing-only pilot](issue53-routing-only-pilot-20261011.json),
[read-only provider receipts](issue53-provider-receipts-20261011.json).
Only synthetic public replies are included for review; no private plans, reasoning
text or credentials were printed.

The prompt-only process had already imported its source before the later parallel-read
and artifact recovery fixes. The routing-only pilot includes those fixes, but precedes
the subsequent leading-language-directive and final requested-model wire fixes.
Future freezes also include `conversation_locale.py`; these pilots are not live proof
of the final locale patch.

## What changed and why

- Invalid collector policy now has a distinct configuration exception. JSON public
  turn/greeting and private-worker requests return a sanitized structured 503 with
  `COLLECTOR_CONFIGURATION_INVALID`; streams retain controlled failure.
  Validation remains before provider dispatch/private-worker home writes.
- Root/worker trajectories and forwarded provider metadata use the resolved execution
  model. The original experiment label is retained as `requested_model` when supplied
  and different. Absent model correlation does not acquire unexpected fields.
- Populated pre-rollout resume regressions now exercise 18 saved rounds, prior planning,
  answered-candidate retirement, useful unasked-candidate continuity and exact current
  testimony through local/private-worker streams. Controlled proposals prove plumbing
  and persistence, not the model's semantic judgment.
- A negative artifact-link test reproduced a pre-existing failure: optional workspace
  uploads could lose their retry job after a link write failed. Claimed jobs now checkpoint
  uploaded paths under their valid lease, retain failed jobs and recover the original
  memory link on a later ordinary turn without re-uploading the checkpointed artifacts.
  The saved conversation remains successful and independent.
  This does not prove every partial-upload/crash failure window is recoverable.
- Session, memories and profile reads now overlap after source acceptance and policy
  checks, before dependent locale/profile writes. Error/cancellation settles all
  outstanding read threads before storage-client cleanup or lease release.
  Writes, quota/ownership checks and conversation serialization remain fenced.
- The live pilot exposed an existing mixed-message locale gap: a leading language-only
  directive followed by testimony changed the model's visible reply language but did not
  persist the preference. The narrow host parser now recognizes that first directive
  sentence, including “请接下来用中文”, without removing any narration.
  Quoted instructions, recollections and “English class” remain non-directives.
  Backend-stream tests verify the choice survives the next ordinary turn.
- The existing profiler has a bounded conversation mode with separately labelled
  baseline/candidate settings, exact pre-turn source/plan/history copies, alternating
  dispatch order, safe records, failure gates and temporary-home/process-setting cleanup.
  Other role defaults remain unchanged; optional workspace model calls are controlled.

The read overlap does **not** justify a seconds-scale speed claim. An earlier receipt put
source acceptance and context completion about 275ms apart, a phase containing more than
these three reads. No new deployed SQL preparation distribution has been measured.
No prompt, testimony or reasoning-effort reduction is required by this safe preparation fix.

## Measurements and quality observations

Primary measurement seam: current `CodexRuntime` → private-worker HTTP/NDJSON adapter →
`CodexWorker` → real app-server/gateway. The campaign uses isolated worker homes and
controlled in-memory external storage, not customer projects or real SQL persistence.
Only optional workspace provider responses are synthetic.

Candidate histories are copied **before** the baseline's turn; both receive the same
accepted source, recent exchanges and saved plan. This matches application context, not
necessarily provider tokenization, cache state or hidden resumed execution context.

### Prompt-only pilot

All dispatched calls requested max on the same pooled route.

| Chinese case | Legacy first text / save | Compact first text / save |
| --- | ---: | ---: |
| First/name | 9.399s / 11.495s | 12.596s / 14.158s |
| Later story | 30.714s / 34.717s | 30.410s / 34.606s |
| Resumed correction | 28.717s / 33.003s | 14.254s / 19.261s |
| Photo | Not reached | 110.459s acknowledgement; failed at 120s, no save |

Six saved visible replies preserved the name, river story, corrected mother/sister
attribution and useful continuation. The photo acknowledgement was grounded but
never reached a usable saved reply. English, switch and pause comparisons were not reached.
One successful pair per case cannot prove quality equivalence.
The optional controlled-workspace JSON adapter was corrected after this pilot; two story
tails had synthetic optional-workspace fallback errors after their measured save boundary.

The contemporaneous gateway photo receipt reports first token at 109.032s and successful
provider completion at 119.853s, with zero bridge/gate wait. The whole worker deadline
expired before validation/save completed. This supports generation-dominated waiting;
it does not establish that compact-v1 caused the timeout.

### Routing-only pilot

Gateway `/model/info` confirms both aliases use `openai/gpt-5.6-luna`:
`gpt-5.6-luna-pooled` enforces max and `memoir-luna-low` enforces low.
No shared key policy was changed. Contemporaneous request receipts also contain both
actual efforts; the application itself still reports effective effort unavailable.

| Case | Legacy first text | Low first text | Legacy validated/save | Low validated/save |
| --- | ---: | ---: | ---: | ---: |
| zh-CN / first | 5.473s | 3.398s | 5.930s | 5.158s |
| zh-CN / later | 4.552s | 6.689s | 5.532s | 10.748s |
| zh-CN / resumed_correction | 9.145s | 4.999s | 9.403s | 9.273s |
| zh-CN / photo | 3.015s | 13.973s | 4.408s | 20.624s |
| zh-CN / language_change | 24.116s | 4.370s | 25.183s | 8.711s |
| zh-CN / pause | 10.723s | 5.989s | 10.996s | 6.980s |
| en-AU / first | 4.747s | 3.288s | 5.852s | 5.232s |
| en-AU / later | 4.628s | 7.216s | 5.760s | 11.146s |
| en-AU / resumed_correction | 8.416s | 3.966s | 9.339s | 7.866s |
| en-AU / photo | 3.660s | 14.780s | 4.984s | 20.815s |
| en-AU / language_change | 14.689s | 5.694s | 15.074s | 9.881s |
| en-AU / pause | 2.681s | 4.843s | 2.980s | 5.645s |

These are backend public-event receipt times. Validated reply and save rounded to the
same values because the external storage adapter is in-memory. They are **not** browser
paint or real SQL durable-save latency. Raw records retain the separate events.

| Exploratory aggregate (12 calls per variant) | Legacy | Low |
| --- | ---: | ---: |
| Median first meaningful text | 5.110s | 5.347s |
| Median validated/save receipt | 5.891s | 8.992s |
| Application failed generations | 0 | 0 |

Low first text improved in 7/12 pairs and regressed in 5/12. Both later-story and photo
pairs regressed. Median save time increased about 53%. Mixing different cases into this
small-sample median is descriptive, not a production distribution or causal estimate.
No production p95 or guaranteed improvement is claimed.

Visible review found no obvious candidate loss of the tested preferred names, corrected
actor, unknown photo year, explicit response language or pauses. Introductions chose
reply-only, rich/correction/photo turns chose extraction, non-stop replies exposed one
follow-up, and pauses exposed none. These are sampled visible/contract observations,
not comprehensive semantic equivalence or live extraction/composition quality.
Family, long/emotional testimony, public-reference attribution and deployed rollback
have not received representative live acceptance here.

Both variants' mixed language-switch messages produced the requested visible language
but left the original profile preference in this pilot. That is the pre-existing host
parser gap fixed afterwards; the pilot is not evidence of persistent switching.

### Provider retries, cache and load limitations

The read-only gateway window associated by time/order/timing with the routing stage contains
24 successful rows plus three `server_error` rows during the Chinese baseline pause window,
although every saved foreground reply reported only one app-server turn.
This is strong evidence that one app-server turn must not be treated as one upstream
request. Exact per-application-turn provider counts remain unavailable because the
gateway IDs are not correlated to the application's diagnostic UUIDs.

Provider input/cache differences are material confounds. For example, contemporaneous
opening rows report 9,453/1,792 input/cached tokens for pooled/max versus 14,124/3,328
for dedicated/low, despite matched application input. Later rows grow substantially;
candidate photo receipt sizes also differ. All routing-stage bridge/gate waits in the
selected receipts are zero. Full provider load and causal retry attribution are unavailable.
The evidence does not support a claim that low effort alone made every reply faster.

## Verification

Counts overlap; do not add them as a unique-test total.

| Check | Observed result |
| --- | --- |
| Final default backend configuration/preparation/profiler/language/routes/stream/worker/app-server/queue/lease/trajectory/runtime-readback set | 274 passed, 10 opt-in SQL cases skipped, 12.48s |
| Final dedicated-low/compact-enabled controlled interview/photo/workspace/family/language set | 188 passed, 15.93s |
| Final disposable PostgreSQL runtime readback, queue/lease/preparation | 43 passed, 7.84s |
| Earlier broad compact/max controlled regression | 366 passed, 4 opt-in live cases skipped, 65.02s |
| Earlier real-PostgreSQL configuration/preparation/profiler/runtime/queue/lease run | 85 passed, 11.94s |
| Desktop + phone rendering/save-gating/reload smoke | 6 passed, 10 unrelated cases deselected, 22.95s |
| Existing five JavaScript streaming/language/photo/history/project-restore files | 53 passed, 0.127s |
| Whitespace check | Passed |

No full repository suite or CI result is claimed. Earlier host PostgreSQL shared-memory
limitations were avoided using the existing disposable Apple-container backend.
Controlled tests dispatch no live LLM. The browser smoke uses real frontend rendering
but replaces auth/API/media/chat transport with synthetic fixtures: it is not a real-proxy
or live-provider latency check. Node 24/Webpack was used after Node 20/dependency and
Turbopack route setup failures; declared dependencies were installed without source or
lockfile changes. The owned temporary frontend server was stopped.

## Remaining issue 53 acceptance

The historical review's findings 1 and 3 (attribution and JSON misconfiguration) are
resolved by tests. Finding 2's failed artifact-link gap is reproduced and addressed;
finding 4's populated resume plumbing is covered, with limited live continuation samples.

| Requirement group | Current position |
| --- | --- |
| Configuration, explicit bounded errors, resume/rollback plumbing, other-role isolation, safe diagnostics | Deterministic coverage; no default rollout |
| Complete narration, names, question/plan validation, quota/lease/cancellation, replay/save boundaries | Relevant controlled regressions pass |
| Independent context reads / optional workspace failure recovery | Implemented with negative settlement/recovery tests; no deployed latency claim |
| Stream rendering and next-answer readiness | Desktop/phone synthetic smoke passes; real-proxy smoke remains |
| First/later/resumed speed in both languages | Measured, but candidate comparison fails acceptance |
| Grounding, useful continuations, language, photos, pauses | Sampled live observations + regressions; not comprehensive semantic-quality acceptance |
| Quality-preserving optimized default and rollout/rollback proof | Not satisfied; keep legacy/max default and issue open |

Before closure: find a candidate that improves first-text and usable-save performance
across representative conversations without semantic regressions; freeze a sufficient
matched evaluation, cover remaining long/Family/reference/rollback scenarios, obtain
correlated provider retry/token/cache receipts and a real-proxy smoke, then apply and
verify the chosen configuration through the operator rollout process.

Do not turn this negative exploratory result into an opening-only optimization,
an automatic downgrade, a timeout increase, fake acknowledgement or a quality claim.
