# First-reply profiling — 11 October 2026 (Sydney)

## Result

One fresh, name-only first turn through the actual web proxy produced visible
text at **7.804 seconds** and reached `conversation_saved` at **10.366 seconds**.
There is no 15-second poll in this path. The main delay is upstream generation,
not HTTP streaming or worker startup.

The current upstream key **enforces max reasoning**. Asking for low effort on
that route does not change the effective effort. The existing same-model
`memoir-luna-low` route genuinely enforces low and was more consistent on a
story-rich first turn. This is a promising tuning option, not a statistically
established production speedup or comprehensive quality evaluation.

## Live first-turn boundary

Synthetic input: the name-only introduction used by the opening regression
tests, `我叫韩凤江`. A new anonymous identity/project was created; no existing
memoir or account was changed.

| HTTP event received | Seconds after POST |
| --- | ---: |
| Response headers / `started` | 0.224 |
| `source_accepted` | 1.020 |
| Context preparation completed | 1.295 |
| Reply generation started | 1.414 |
| First visible `text_delta` | 7.804 |
| Reply generation/plan persistence completed | 10.098 |
| `conversation_saved` / `reply_complete` | 10.366 |

Context/acceptance took approximately 1.4 seconds, then another 6.4 seconds
elapsed before the acknowledgement. The remaining generation/validation/plan
save took approximately 2.3 seconds, and final persistence/publication took
approximately 0.27 seconds. These are HTTP receipt times, not browser paint
measurements. The optional workspace tail is outside the saved-reply boundary.

Synthetic project retained for inspection: `project_877d34aef2fa`, anonymous
principal `ce2ed665-a882-4076-a6a6-d1526d923559`. It contains one synthetic turn.
Tokens were kept only in process memory and were not printed or saved.

## Isolated collector measurements

Each trial used a fresh disposable app-server home/thread, the application's
real collector instructions/schema, and the same synthetic context within a
case. Calls were serial, not concurrent. Timings include app-server startup.
The introduction prompt contained 27,451 characters; the story prompt contained
27,538. The story describes a childhood home, parents, sister and river memory.

| Case | Requested effort | Route | Effective effort | First visible acknowledgement (s) | Validated reply (s) |
| --- | --- | --- | --- | ---: | ---: |
| Introduction | max | Current collector | max | 3.278 | 3.779 |
| Introduction | low | Current collector | max | 2.766 | 3.247 |
| Introduction | low | Current collector | max | 9.450 | 11.494 |
| Introduction | max | Current collector | max | 3.556 | 3.895 |
| Introduction | low | `memoir-luna-low` | low | 3.408 | 5.306 |
| Introduction | low | `memoir-luna-low` | low | 2.996 | 4.869 |
| Story | max | Current collector | max | 13.080 | 27.168 |
| Story | low | Current collector | max | 45.431 | 51.579 |
| Story | low | Current collector | max | 9.429 | 9.955 |
| Story | max | Current collector | max | 7.122 | 8.479 |
| Story | low | `memoir-luna-low` | low | 5.949 | 8.520 |
| Story | low | `memoir-luna-low` | low | 5.444 | 9.467 |

All twelve collector trials passed application validation with one app-server
turn (no application-level proposal correction). Introduction trials preserved
the exact name, chose `reply_only`, and produced one candidate. Story trials
chose `extract`, with four candidates on the current route and three on the
low route. Both are within the normal 2–5 candidate contract.

One current-route story trial encountered an upstream error followed by a
successful provider retry; one app-server turn can contain multiple upstream
attempts. The app-server count must not be read as a provider request count.

Worker initialization/thread creation was approximately 0.10–0.26 seconds.
For introductions the complete-acknowledgement safety buffer usually added
0–0.13 seconds after the first raw JSON delta; stories added 0–1.18 seconds.
Do not remove the validation boundary to expose unvalidated JSON/questions.

## Verified provider policy and timings

Read-only gateway `/model/info` confirmed both routes use underlying
`openai/gpt-5.6-luna`, with max and low reasoning respectively. Read-only
codex-lb policy/request records confirmed the effective efforts:

- The shared key serving the current collector route enforces `max`.
- The existing `memoir-background-luna-low` key enforces `low`.
- Both keys have foreground traffic class and no enforced service tier.
- In the slowest measured story request, the first upstream event arrived
  after 684 ms, but the first token arrived after 44,125 ms. Recorded local
  bridge queue and response-create gate waits were zero; generic queue timing
  was unavailable. This points to upstream/model work, not the local queue.
- That request recorded 2,364 reasoning tokens despite 7,936 cached input
  tokens. The genuine low-route story requests recorded 91 and 124 reasoning
  tokens. Caching alone did not prevent the max-effort long tail.

The provider recorded different total input-token counts for the two aliases
(approximately 9.1k versus 13.8k for stories), despite identical application
instructions. Alias/app-server context and caching therefore remain confounds;
this is a route comparison, not a perfectly controlled effort-only benchmark.

## Recommended next changes, in order

1. Give the latency-sensitive collector a dedicated low-effort same-model route,
   using the existing low route for a larger quality/latency evaluation first.
   Keep other roles independently configurable. Changing only the Memoir
   effort environment variable will not override the current upstream key.
   Do not change the shared max-key policy: other applications use that key.
2. Reduce collector-only prompt overhead while preserving evidence, consent,
   source/work classification and one-question guarantees. Even an introduction
   currently receives approximately 27k characters of application instructions.
   Any benefit still needs a measured prompt A/B and richer regression cases.
3. Optimize the smaller preparation cost: avoid the duplicate entitlement read
   and consider batching independent context reads while preserving lease and
   cancellation settlement. Its total measured envelope was approximately
   1.4 seconds, so it cannot explain a 45-second wait.
4. Retain HTTP/NDJSON streaming. Switching to SSE or WebSocket does not remove
   model reasoning, retries, or required persistence/validation work.

No app code, service settings, key policies, deployments or running services
were changed. A repeatable profiler and its boundary tests were added.

## Reproduce

The first command creates a new synthetic anonymous account/project and saves
one turn each time. The collector commands create only disposable runtime
directories and perform bounded model calls; they do not save narrator sources.

```sh
python3 scripts/profile_first_reply.py first-turn
mocker compose exec -f compose.yml -i -T codex-worker python - collector --efforts max low low max < scripts/profile_first_reply.py
mocker compose exec -f compose.yml -i -T codex-worker python - collector --case story --efforts max low low max < scripts/profile_first_reply.py
mocker compose exec -f compose.yml -i -T codex-worker python - collector --model memoir-luna-low --efforts low low < scripts/profile_first_reply.py
mocker compose exec -f compose.yml -i -T codex-worker python - collector --case story --model memoir-luna-low --efforts low low < scripts/profile_first_reply.py
python3 -m pytest -q tests/test_first_reply_profiler.py tests/test_name_only_opening.py tests/test_turn_stream.py --disable-warnings
```

Verification: **39 tests passed**. Sample limitations: one live HTTP turn, two
genuine low-route trials per case, uncontrolled provider/account load, no
browser paint timing, and no full long-conversation or semantic-quality study.
