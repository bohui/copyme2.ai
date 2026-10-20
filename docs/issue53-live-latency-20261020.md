# Issue 53: measured collector latency and remaining release checks

The preferred target is meaningful text within **5 seconds**, with **10 seconds**
as the fallback. PR [101](https://github.com/bohui/copyme2.ai/pull/101) remains a
draft. The candidate is not enabled in the shared app, and issue 53 is not yet
accepted.

## What the measurements establish

The shared pooled collector route enforces maximum reasoning effort despite the
app requesting low effort. Read-only key-policy verification matched the exact
configured keys: `gpt-5.6-luna-memoir-low` enforces low effort for the same
underlying `gpt-5.6-luna` model. No key policy, shared model route or other role
was changed.

The last completed real-model cohort used source
`a864bc50c06f6b03c2336919b95b436c8f0ef73c`. It exercised isolated PostgreSQL,
the canonical backend HTTP/NDJSON path and the real Linux private worker with
synthetic narrators. All 80 application rows saved, including four cached
replays. There were 76 native turn invocations and no corrective invocations or
application failures. A test-database cleanup command timed out after the rows
finished; a separate completion audit verified the rows, removed worker homes
and confirmed no task database containers remained. The original aborted
supervisor receipt is retained.

The matched latency comparison excludes the four future rollback generations
from both arms: 36 generated turns per arm, spanning both languages and opening,
later, rich-story, correction, skip, language-switch, photo and resumed turns.

| Observed milestone | Pooled/max median | Dedicated/low median | Dedicated/low maximum |
| --- | ---: | ---: | ---: |
| First public text | 19.044 s | 4.528 s | 7.035 s |
| Validated question (34 turns per arm) | 22.859 s | 5.923 s | 9.130 s |
| Complete public reply | 21.144 s | 5.952 s | 9.483 s |
| Durable conversation save | 21.154 s | 5.994 s | 9.499 s |

First public text improved by about 76%; 24 of 36 candidate turns reached it
within five seconds, and all 36 within ten. Some acknowledgements are generic,
so this milestone alone does not prove time to meaningful text. Complete replies
provide a conservative time bound: all 36 finished within ten seconds, seven
within five. These are small-sample observations, not production percentiles or
a latency guarantee.

The [public evidence](test-evidence/issue53-every-turn-followup-20261020.json)
retains the synthetic public exchanges, per-turn timings, frozen plan identity,
read-only route policy, failures and limitations. Private planning, raw reasoning
and credentials are excluded. Connected histories diverge after the first reply;
shared gateway load and provider-internal attempts were not controlled or fully
observable.

## Quality fixes and unsuccessful follow-ups

Review found an unpunctuated Chinese question in an acknowledgement, an assumed
school morning absent from testimony, and a distress follow-up that needed a
clearer pacing choice. Source
`743546c138c2672be1c71b7aed22f1987849b369` added pre-stream rejection for the
observed extra-question form and schema guidance for grounding and gentle
pacing. It also clarifies the existing exact `text == quote` continuity contract
to prevent unnecessary repair attempts. Existing validation and bounded repair
remain in place. Those quality fixes did not change managed prompt Markdown or receipts. The
main integration below reuses an already-published receipt for merged content.

Four work-mode expectations in the sequence manifest were inconsistent with the
published collector contract for privacy and language/profile actions. They now
require extraction. The original frozen plans and failures remain retained; this
correction applies to the next comparison.

The current source has not completed its live acceptance run. Follow-up D stopped
after ten rows with upstream WebSocket/HTTP 502 errors and a timeout affecting
both routes. Probe E used normal native retry defaults and file-based diagnostic
capture; both first turns timed out before public text. A valid direct generation
probe also returned HTTP 502. These failures are retained and are not counted as
successful latency observations. Health and model-list endpoints returning 200
do not establish generation availability. Read-only gateway logs corroborate
upstream `stream_incomplete` / WebSocket failures; their mixed traffic cannot
supply Memoir-only request counts. One subsequent bounded availability request
returned HTTP 200 but ended after 9.204 seconds without an observed output
delta or terminal completion event. It did not establish healthy generation at that time.

## Latest main integration and checks

Latest main `4c1a53af9ba878e1991297f6b81521e474b6720a` merged cleanly at
`89c9d2f1e39126dd5948718186e488342a583d48`, bringing delivered-question
tracking and the toddler-stage removal. Review found two compatibility updates:
the continuity fixture needed the new required nullable question-evidence field,
and the changed timeline instructions needed their generated version 2 receipt.
The latter was copied from the primary main checkout and verified against
Langfuse; its staged work was left untouched. No feature-branch publication ran.

At `4d52604`, all **421** combined collector, continuity, strategy,
question-identity, real-SQL HTTP and two-lane regression checks passed, with
cleanup verified. Required `make test-place-research` passed **588 web, 432
Python and 95 skill tests**. `make prompt-check` verified all **81** published
pins. Before these fixes, the checks retained 13 combined and ten place Python
failures; a clean latest-main checkout independently reproduced a background
failure. This does not claim every repository test is green.

The earlier 80-row canonical matrix and mobile replay passed at source
`743546c1`; the updated-main workload still needs its own full comparison.

## Recovered generation and remaining gates

After the user confirmed gateway recovery, comparison F at `c4611030` executed
30 planned turns with 30 native invocations and no background dispatch. All
produced durable public replies, but the pure-stop candidate incorrectly chose
`extract` rather than `reply_only`. Its public reply correctly stopped without
a question. The frozen failure condition stopped the campaign, retaining 29
passing rows, that contract failure, and 50 unrun rows. Worker homes were removed.
Generation availability is no longer the blocker; work-decision correctness and
verification on the updated main remain open.

Before acceptance, the latest source needs the pure-stop work fix, its full
bilingual contract matrix, a bounded matched live run and
review of every public reply, genuine pre-rollout session continuation and
rollback, long-source retention and independent extraction readback, and the
small real web-proxy/browser smoke. Provider failures must remain in the final
report. Controlled activation follows successful acceptance; the shared app
continues using its existing configuration meanwhile.

The reviewed activation values, once those gates pass, are
`MEMORY_SPARK_COLLECTOR_MODEL=gpt-5.6-luna-memoir-low` and
`MEMORY_SPARK_COLLECTOR_REASONING_EFFORT=low`, applied consistently to API,
private worker and background worker configuration. Other role overrides and
published prompt pins stay as configured. Record the previous collector values
before activation so rollback restores them for future turns. Activation is
pending, not evidence of a completed rollout.
