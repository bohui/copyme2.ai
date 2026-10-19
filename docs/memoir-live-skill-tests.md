# Live skill tests

The [ten-skill dataset evaluation CLI](memoir-skill-evaluation.md) adds stable
per-skill datasets and optional independent judges. The isolated runner below
also includes the foreground interviewer; inventory no longer depends only on
the presence of `SKILL.md`.

Run `make memoir-live-skills-test` to test the active skill packages with
real Responses calls through the existing private gateway configuration. Use
`LIVE_SKILL=memoir-composer` to run one package. `make memoir-live-skills-plan`
makes zero calls. `ENV_FILE` selects an existing configuration; credentials are
never passed as command arguments or written to results.
Use `LIVE_SKILL_CASE=photo-reject-unverified-lead` to select a single case.

Each run gets a fresh directory under `~/memoir-test-results/live-skills`, with a
receipt, report, synthetic model outputs, and composition/search evidence. The
suite records actual response IDs, returned model identity when supplied, usage
when supplied, latency, and independent validation. Missing data stays unknown.
Failures consume the dispatch budget; transport requests are not retried. The
default bounds are one concurrent call, 32 HTTP dispatches, 120 seconds per call,
and 30 minutes for the suite. Gateway-internal attempts and monetary cost are
unavailable and are not claimed to be bounded by the client dispatch count.

| Package | Live check |
| --- | --- |
| memoir-interviewer | Eight bilingual foreground scenarios: Comfort, Explore, Shape, pause, redirect, correction, photo-only input and quoted controls; validated by the production collector contract |
| memoir-memory-context | Admitted checkpoint pages in English/Chinese; accumulated earlier originals, manual target exclusion, saved reference, corrections, exact window-relative evidence, and empty/ambiguous patches |
| memoir-author-timeline | Original evidence, childhood stage, and no invented family identities, in both languages |
| memoir-family-tree | Explicit mother and her grounded introduction through the application marker parser |
| memoir-place-journey | Both cities in a move, in order; generic river does not become a place |
| memoir-composer | Both languages at rounds 5 and 10: summarise only five new messages, draft a progressive revision, validate original evidence, review and render; preserve an independent passage exactly; at most three draft attempts per checkpoint |
| memoir-historical-news-research | Reject unverified leads and private search data; native search receipt and independent public-source inspection/validation |
| memoir-place-photo-research | Reject unverified leads and unsupported downloads; native search receipt and independently inspected item capture metadata |
| memoir-place-groups | Actual deterministic city/pin resolver checked against explicit expected counts; no skill model request |
| memoir-story-game | Reject missing completion/adaptation authority; no game generation |

These are isolated skill contract tests using synthetic or public inputs. They do
not create Auth users, save Supabase artifacts, grant entitlements, enable rollout
flags, or certify browser/voice/persistence workflows. Grouping and localization
remain deterministic in production. The game probe checks missing authority;
its passing negative test is not a successful game-generation test. Native research fails
when actual search receipts or inspected source support are absent, even if the
model returns plausible URLs.

Profile probes use `profile_contract`, `profile_packet`, and `validate_profile`
from the application, with an independent exact-window citation check. The host
owns the 1/5/10/20/30 schedule, interval coverage, current manual locks, and commit
fences. These admitted-page probes do not prove those host decisions or a save;
native conversation/worker/profile-readback tests cover that boundary. A stopped
profile or empty target set must skip before the skill contract is loaded.
Retired `app-auto-localization` has no active probe. Historical run results below
retain their original cases and receipts.

The separate `memoir-live-fifty-test` campaign retains its own source receipts,
original inputs, deadlines and accounting. Running this suite neither resumes nor
extends that campaign.

Composer calls use `MEMORY_SPARK_MEMOIR_COMPOSER_MODEL` and
`MEMORY_SPARK_MEMOIR_COMPOSER_REASONING_EFFORT` (default `low`), matching the
configured background worker. Other cases use the existing default model and
`LIVE_SKILL_EFFORT`. The composer runs the actual application orchestration with
isolated checkpoint storage; native PostgreSQL tests exercise admission, commit,
withdrawal and owner-scoped readback separately.

## Progressive rerun, 14 October 2026

Run `6636396d-b666-4798-9cf9-b8d40e1ba3f9` made 25 real gateway
dispatches across all ten packages: 12 of 15 cases passed. Both composer languages
passed at rounds five and ten with exactly prepare, draft and review per checkpoint,
without a draft repair. The independent unchanged paragraph was identical and the
revision retained the new original source reference. The gateway returned the
configured `memoir-luna-low` alias; the requested effort was `low`.

| Locale | Round 5 model phases | Round 10 model phases | Two-checkpoint application total |
| --- | ---: | ---: | ---: |
| en-AU | 17.0 s | 17.3 s | 35.9 s |
| zh-CN | 20.1 s | 20.0 s | 41.2 s |

These are small synthetic cases, not a throughput or production latency promise.
The photo negative-provenance case still failed on repeated JSON documents. Both
native discovery cases received HTTP 400 with `max_tool_calls_rejected`. Those
three failures remain visible in the report and are not counted as search success.

The rerun also exposed a repair admission mismatch: composer validation included
stale-projection errors that worker admission omitted. Both paths now use the same
validation function. Batch instructions distinguish canonical event references
from summary-only acknowledgements, preserving the original evidence boundary.

## Earlier per-quotation run, 14 October 2026

All ten packages received real model responses in isolated tests. Nine packages
have a passing contract case. Photo provenance failed twice because the model
reply contained four concatenated copies of its JSON object; those malformed
replies remain failures. The historical and photo native-discovery requests each
received HTTP 400. A bounded historical diagnostic classified the rejected
parameter as `max_tool_calls`. Discovery therefore remains unverified on the
configured gateway; ordinary model responses do not establish search capability.
The suite requires actual tool receipts and source support, consistent with the
[Responses web-search contract](https://developers.openai.com/api/docs/guides/tools-web-search).

Both language variants of the three-phase composer passed validation, editorial
review and rendering on their first draft at both `max` and `low` effort.

| Locale | Max: total / draft | Low: total / draft |
| --- | ---: | ---: |
| en-AU | 56.2 s / 44.3 s | 44.6 s / 35.8 s |
| zh-CN | 53.3 s / 41.7 s | 41.1 s / 31.3 s |

These are two small synthetic inputs, not a throughput or literary-quality
benchmark. Shared gateway traffic was not controlled. The gateway returned the
configured alias `gpt-5.6-luna-pooled`; its underlying model was not independently
verified. Production effort was not changed.

The retained Harbour checkpoint illustrates the evaluator deadline mismatch:
its completed snapshot has 15 sequential pages and at least 67 registered model
outputs (15 prepare, 33 draft, 19 review), compared with 45 outputs for one clean
three-phase pass per page. From snapshot creation to the final saved compose
checkpoint took 2,491.6 seconds, or 41.5 minutes. The evaluator waits at most
600 seconds and can stop sooner at the original case deadline. It reported an
incomplete checkpoint while the background worker continued to completion.

Output digests deduplicate identical replies, so 67 is a lower bound on model
outputs, not an exact request count. Checkpoint timestamps are overwritten on
save; they locate completed work, not precise phase starts. Two roughly
five-minute gaps are consistent with the lane's maintenance deferral schedule,
but available historical telemetry cannot establish which reason caused them.
The canonical path now logs safe per-page phase timing on success and failure;
the evaluator records extraction/checkpoint wait progress without changing any
deadline or treating partial work as completed.
