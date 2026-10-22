# Privacy review and targeted repair optimization

The proposed change reduces normal privacy instructions from **2,753 to 993
characters**, and repair guidance from **3,215 to 431–823** characters. The
optional acknowledgement call composes the same privacy rules with its original
style guidance: **1,998 characters**. Normal reply instructions stay at 1,986.
The normal two-call foreground total is **2,979**, so the whole Lane A flow is
still above 2,000 before schema and narrator data.

The model-stage pilot improved ordinary-policy median time by 7.4% and repair
median by 25.5%. The four reserved privacy cases had a **28.5% slower median**.
These mixed results do not establish a universal speed gain or the browser's
5-second target. Publication, deployed-worker validation and full #53 acceptance
remain pending. This is a reviewable candidate, not a rollout recommendation.

## Execution and retained contracts

| Step | Actual work and dependency | Change |
| --- | --- | --- |
| `lifetime_memory_runtime.py`, pending policy admission | Accept current narrator source under the existing source/policy fence. Private context stays unavailable until review completes. | None |
| `policy_review.py` | One source-only structured model call, exact Unicode-span/duplicate validation, then fenced durable policy receipt. Errors leave review pending. | Select the core prompt normally and a composed opening template only when the existing early-ack flag requests it |
| `prompt_composition.py` | Render pinned sources and shared components | Opening template references the core rules; the original acknowledgement guidance is retained verbatim |
| Governed context assembly and normal reply | Authorized saved dialogue and current narration; one reply proposal | Same 1,986 static characters, model, schemas and effort settings |
| `lifetime_memory_engine.py`, rejected output | Retry from the same evidence within three validation attempts plus one incomplete-document replacement; freeze displayed acknowledgement | Select one reported repair rule plus common constraints; retain all thirty descriptions in the managed catalog and retain its full provenance hash |
| Validation, delivery and save | Strict proposal/source validation, actual-send admission and final delivery/save fences | None |
| Lane B | Existing extraction, continuity and strategy proposals | None; privacy must precede private-context access and repair must precede validated delivery |

The repair common rules explicitly clear question evidence for no-question
outcomes and prohibit unstated time/place links. Error-code messages are unchanged.
Unknown/schema-field codes use a bounded schema fallback. Error-code JSON,
frozen acknowledgement text, schema and testimony are additional to the static
sizes above. No validator, source evidence, lock, retry ceiling or host authority
was removed.

## Prompt inventory

| Prompt source | Purpose / when used | Publication |
| --- | --- | --- |
| `policy-review.md` | Source-only privacy core: intent/scope/negation/attribution, conditional controls, exact spans, complete overflow handling and unresolved-reference failure | Changed source; old v3 receipt retained until main publication |
| `policy-review-opening.md` | Optional early acknowledgement; references the core once and preserves the original natural-language guidance | New unpublished composed template |
| `governed-repair/codes.md` | Published rule catalog, stored as JSON; common constraints plus matching error only are transmitted | Changed source; old v4 receipt retained until main publication |
| Repair prefix/suffix/acknowledgement | Existing error framing and exact displayed acknowledgement | Unchanged v1 artifacts |
| `reply.md`, `governed-turn.md` | Normal foreground generation | Unchanged v1 artifacts |
| Other interviewer prompts | Supported alternate modes, greetings and Lane B strategy; all remain at root | Unchanged |

The catalog has one owner per prompt source. Adding the conditional opening
artifact makes 24 interviewer catalog entries; it does not add a model call.
All existing schema and source metadata remain authoritative. `AGENTS.md` and
`README.md#versioned-prompt-artifacts` require source review/merge before creating
versions; no feature-branch version or fabricated receipt was created.

## Live comparison

Existing `gpt-5.6-luna-pooled` route and low requested effort, unchanged credentials,
concurrency one, one sample per case/arm. Source-only policy uses its actual
request/schema shape. Repair uses the real Responses serializer/SSE reader and
production reply validator with a controlled publication fixture. It does not
read or write hosted user state. Synthetic prior exchanges do not constitute
saved-resume acceptance. Model/request settings in returned receipts are retained;
independent enforcement of gateway effort policy was not verified.

| Group | Samples per arm | Baseline median | Candidate median | Observation |
| --- | ---: | ---: | ---: | --- |
| Ordinary policy, main cohort | 14 | 3.69s | 3.41s | 7.4% faster median; under-5s count fell from 14 to 11 |
| Optional acknowledgement, main cohort | 2 | 4.38s | 3.83s | 12.7% faster median |
| Repairs | 6 | 6.98s | 5.20s | 25.5% faster median; the slowest candidate took 9.07s |
| Reserved privacy cases | 4 | 4.52s | 5.80s | 28.5% slower median; under-5s count fell from 2 to 1 |

All 26 final outputs passed the frozen privacy or production reply contracts and
agent semantic review of source fidelity, scope and natural wording. This is not
independent human acceptance. Baseline had one ambiguous-topic failure. Exact
input/output, per-case timing, usage, request/prompt/schema hashes, model receipts
and every rejected intermediate generation are in
[the evidence](test-evidence/issue53-policy-repair-20261022.json).

Earlier candidates exposed partial overflow handling, stale question evidence on
a stop, an unsupported chronology/place link and weak optional Chinese phrasing.
They were rejected and retained. The conditional template preserves the original
acknowledgement guidance while normal requests omit it. Four reserved cases were
not used to tune the final template; earlier r3 outputs for those cases were not
inspected until after the final template was locked. Budget increases and reasons
are recorded: **124 actual generations**, finite cap 128, no automatic provider
retries. One rejected intermediate exceeded 10 seconds; none of the final 26 did.
The main and candidate phases were sequential and can reflect provider/load drift.
No tail percentile is estimated from these small samples.

The [official OpenAI latency guide](https://developers.openai.com/api/docs/guides/latency-optimization)
identifies input size, generated output and sequential requests as separate
factors. This comparison measures timing and makes no speed promise from prompt
length alone. The normal privacy stage remains on the critical path.

## Verification and publication

- 300 focused prompt/publication/composition, engine, continuity, reply/transport,
  privacy database and HTTP regressions passed on the final source snapshot.
- A request-level test failed on the original all-code glossary and passed after
  selection. It checks normal/continuity/JSON/incomplete/schema/unknown errors,
  source-catalog provenance and the common evidence constraints.
- Conditional-template tests check normal-request omission, one shared core,
  under-2k compiled opening instructions and the actual early-ack routing.
- Disposable database/process allocations were reconciled. Candidate code and
  prompt hashes match the tested snapshot and the final live experimental texts.

PR #111 merged during profiling. Its merged tree `9c77d279` is identical to the
profile baseline `b41926cc`; prompt/model behavior did not change underneath the
comparison. The new optimization is based on that current main.

After source review and merge, the normal main-only publisher must publish the
two changed sources and new composed template, then generate genuine receipts.
Verify pins and matching API/private-worker code before live end-to-end testing.
Keep model/effort, early-ack flag and Lane B settings fixed for the matched run.
No publication, service restart, rollout or production configuration change is
part of this PR. The local checkout returns to the published main baseline after
preparing it, since running services mount the repository's prompt files.
