# Lane B selected-original outline: measured baseline and next proposal

This is the remaining selected-outline path in `memoir-composer`, separate from
the already approved prepare/draft/review transport change in PR117. No outline
implementation, prompt, model or runtime setting has changed. Game remains last.
The baseline does not pass semantic acceptance.

## What the three original calls do

For a two-original selected collection, two leaf calls organise individual source
windows. A merge call combines their derived section summaries. The tree is
durably checkpointed; resuming after the first leaf reuses it. These are three
outline calls, not the prepare/draft/review phases of periodic prose composition.
The final outline stays a private proposal and never rewrites original sources.

| Step and source | Trigger/input | Work/output | Delivery dependency |
| --- | --- | --- | --- |
| `lifetime_memory_collection_jobs.py:58`, `submit_selected_job` | Explicit selection and eligible paid/confirmed project | Owner RPC admits a source/version snapshot and job | B; no current Mira reply waits |
| `CollectionJobWorker`, same file:135 | Claimed durable job, bounded page limit | Read current leaf/merge page and generation fence | B; repeat/resume must retain saved work |
| `lifetime_memory_job_engine.py:181` | Host-owned source window or derived children | Validate packet, reference sets and token budget | B; rejects extra/foreign/unbounded inputs |
| `send_bounded_job_request`, same file:292 | Exact `BoundedJobInput`, authenticated worker | Recheck publication admission, send bounded HTTP request | B; live baseline uses a declared controlled HTTP adapter |
| `run_bounded_job`, same file:327 | Revalidated fence and `job_contract` | New governed native Codex home/thread, schema-bound model turn | B; measured model path |
| `validate_job_result`, same file:199 | Proposed title/sections | Require exactly-once original/child ancestry, no fabricated references or over-budget metadata | B; schema validity does not prove title meaning |
| Worker commit and fresh readback | Same source/policy/selection/lease versions | SQL commits one page, then root; private result | B; failed/stale work cannot publish |

The live harness actually runs the worker and native job engine with real
disposable SQL. Policy/selection/payment fixtures and the HTTP-to-worker adapter
are controlled boundaries. It limits the first execution to one page, then uses
a fresh worker for the remaining leaf and merge. A completed-job replay makes no
new model call. This is not deployed private-worker/Temporal or browser evidence.

## Prompt inventory

| Source under `skills/memoir-composer/prompts/outline/` | Purpose | Genuine pin |
| --- | --- | --- |
| `shared/prefix.md` | Bounded selected-collection role, evidence/privacy/locale rules, concise titles and exact reference coverage | v1, `c73e56cbc14f…` |
| `shared/suffix.md` | Shared exactly-once, size/section limits and original-preservation rules | v1, `754884920290…` |
| `leaf/en-AU.md` | Compose shared rules around `memory_ids`; Australian English titles | v2, `a32e8ad5e538…` |
| `leaf/zh-CN.md` | Same original-reference leaf contract; Chinese edition titles | v2, `a3108ba8705f…` |
| `merge/en-AU.md` | Compose shared rules around `section_ids`; merge derived children in English | v2, `b1af3ebef854…` |
| `merge/zh-CN.md` | Same child-reference merge contract; Chinese edition titles | v2, `80fdf1243c33…` |
| `job_contract` output JSON schema | Restrict reference IDs, title/section shape and size | Runtime schema, retained hash/request |
| Native app-server framework context | Session/tool-facing wrapper; 1,731 input tokens per observed request | Runtime-owned, not a managed application prompt |

Rendered instructions are 1,110 characters for each observed leaf and 1,111 for
merge. There is no additional outline repair/judge call in the observed cohort.
The application instruction itself is already under 2k; native overhead is the
measured removable candidate. No prompt-size target justifies dropping ancestry,
source/policy fences, page checkpoints or publication approval.

The organiser uses global `gpt-5.6-luna-pooled`, not the composer-specific low
override. Actual responses identify `gpt-5.6-luna` at **max** effort. All six
requests are uncached: 3,572–3,722 input tokens each, including 1,731 framework
tokens, with no actual tool invocation. Requested versus effective effort and
the separate composer route must not be conflated.

## Live results retained

| Original synthetic case | Actual calls | Provider seconds | Worker through saved readback | Source/title review |
| --- | ---: | --- | ---: | --- |
| English, two sources; real saved-job resume | leaf, leaf, merge | 6.71, 3.56, 7.89 | 19.88s | Pass for these originals; no age order or unknown month invented |
| Chinese, two sources; real saved-job resume | leaf, leaf, merge | 3.18, 4.55, 5.40 | 14.32s | Fail: school attendance becomes `童年` in leaf and root titles |

The English originals mention walking to school with sister May in 1983, without
knowing her age order; then moving to Sydney and repairing bicycles in 1991,
without knowing the month. Saved titles preserve the stated facts. The Chinese
originals mention school with older sister Amei in 1983, then Sydney/bicycle work
in 1991 with an unknown month. `童年上学路` and `从童年上学到悉尼生活起点`
introduce childhood, an age stage not established by school attendance alone.
The merge promotes the leaf's derived stage into another derived title.

The Chinese fixture's original source-language field defaults to `en-AU`, while
its actual text and edition locale are Chinese. This retained mismatch requires
a matching Chinese-source-language baseline confirmation before claiming a
candidate comparison. It does not turn the invented age stage into an original
fact. The controlled selection helper's childhood categorisation is likewise not
narrator testimony and is absent from the model packet.

Structural checks pass in both cases: exact source IDs/text/versions remain,
every original occurs once in ancestry, page resume and completed replay avoid
duplicate work, and publication approval remains false. Semantic review is the
assistant's direct comparison with originals, not independent human/model review.
Long windows, cross-child regrouping, protected/attributed material, policy
revocation and deployed-worker behavior remain unmeasured here.

The original finite ceiling is eight calls; six were used. An initial launch
failed before any model call because an unrelated prompt draft did not match its
genuine receipt. Its zero-call failure is retained alongside the successful
baseline. Both native SQL/process cleanup receipts are verified. No failed row
is removed and no speedup has been established by this baseline alone.

## Concrete proposal, still unimplemented

1. Reuse the existing direct structured Responses transport for leaf and merge,
   retaining the same exact packet/schema/model/effort, `JobRequestBody`,
   `JobPublication`, admission and strict result/SQL validation. Keep all three
   calls and checkpoints for this two-source tree. This targets 1,731 unused
   framework tokens per call; it does not imply an equal latency percentage.
2. Clarify shared source-grounding guidance: school or work does not establish a
   life stage; child titles are derived and cannot establish it either. Preserve
   uncertainty in final titles. This is a managed prompt change requiring review
   and publication through main.
3. Correct and declare the Chinese fixture's source-language field in a separate
   matching baseline, without editing the earlier evidence. Repeat the original
   exact texts, resume boundary and source/selection gates, then reserved long
   window/cross-child/attribution held-outs. Freeze a finite call/deadline plan
   before new dispatch; hold global routing constant.

Expected benefit is reduced input/session overhead; no wall-time reduction is
promised before a matched live run. Rollback restores native leaf/merge dispatch
and the previous genuine shared guidance. No source, hierarchy, schema, tool
discovery, model route, owner, privacy or approval contract should change.

The exact original requests, responses, schemas, instructions, outputs, SQL
witnesses, source/helper hashes and failed launches are retained in [the evidence archive](evidence/lane-b-selected-outline-baseline-20261024.json.gz) with [its index](evidence/lane-b-selected-outline-baseline-20261024.json). This draft adds analysis
only; it grants no implementation or publication approval.
