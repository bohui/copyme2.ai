# Issue 53: current acceptance after source-policy review

The target remains meaningful public text preferably within five seconds and
otherwise within ten, without a response-quality regression. Issue 53 is not
accepted. The historical 20 October cohort predates the mandatory source-policy
review introduced by PR105 and does not establish current latency or quality.

The original coding task is
[the optimization chat](codex://threads/01a1567e-46d6-7e40-afc7-ccd9620731c9).
The reviewable continuation is [PR106](https://github.com/bohui/copyme2.ai/pull/106).

## Current observations

Two bounded synthetic worker campaigns used real canonical SQL/ASGI delivery and
task-owned private workers, without customer data or background/judge dispatch.
The first stopped after two failed rows: a worker omitted unrelated evaluation
prompt files and the decoder rejected a valid completed response with a padded
ID. PR106 fixes both boundaries while preserving explicit required-prompt checks,
completed-response validation and bounded IDs. Main later added trace naming and
an overlapping optional-prompt fix; those changes are retained in the latest-main integration.

At `751ed4e`, the second campaign stopped after 14 of 80 planned rows: seven
baseline saves, six candidate saves, one candidate failure and 66 unexecuted rows.
The saved candidate first-public-text median was 14.267 seconds, maximum 25.846;
the baseline saved-row median was 15.742 seconds, maximum 28.841. These partial
arm summaries are not a completed matched comparison or semantic acceptance.
The failed candidate emitted partial text at 9.540 seconds, then failed a
question-evidence span check; both fresh-home corrective attempts ended with
`max_output_tokens`. That row remains a failure and is excluded from saved-row
latency summaries. Ten native reconnect notifications remain recorded; exact
provider-internal request counts are unavailable.

The campaign used 16 native generation invocations and 14 direct source-policy
requests against a frozen ceiling of 100 native plus 80 policy requests and
1,800 seconds. Both campaign workers stopped successfully and their temporary
homes were removed. Read-only live gateway verification confirms that the exact
pooled route enforces maximum reasoning and the dedicated Memoir route enforces
low reasoning for the same underlying model. No shared key policy was changed.

## Prepared optimization

The existing source-policy request can also produce a brief grounded statement
about the current message. This reuses the mandatory request and removes the
need to wait for the collector's second model round trip before displaying text.
`MEMORY_SPARK_EARLY_POLICY_ACK` defaults to `0`; the candidate remains disabled.
With the flag enabled, the policy prompt receives only the exact current source
and the selected reply language, and returns an optional acknowledgement beside
its complete restrictive controls. Incomplete or invalid controls still block
private-context admission and produce no acknowledgement.

The acknowledgement becomes eligible only after that exact source/version's
review commits. Normal context preparation and the publication fence still run
before the public delta. The collector is bound to the same acknowledgement;
normal proposal validation, bounded repair and required persistence still govern
the follow-up, completion and save events. Receipt reuse is scoped to the current
source/version and language. Saved replies replay unchanged; failed turns can
retry without another policy request. Historical-reference constraints can
withhold the early statement and keep the existing collector behavior.

Real HTTP/SQL tests cover both languages, an explicit English-to-Chinese switch,
provider failure, save failure, exact retry and saved replay. A controlled barrier
proves text is received while the collector is blocked; failed turns expose no
question, completion or save marker. The repair prompt also directs models to
use null offsets for a unique exact quote rather than guess coordinates; invalid
explicit offsets remain rejected.

## Evaluation review fixes

Both privacy-exclusion steps now declare fixed exact controls in the versioned
synthetic manifest. The offline transport submits those controls through the real
policy publication guard and SQL transaction. Comparison requires the current
source's committed restriction, the active pinned control, and omission of prior
assistant replies from governed input. Resealing a capture with an empty policy
review fails contracts and excludes its latency pair. Self-consistent retained
private assistant history also fails in English and Chinese. These are evaluation
contracts, not a claim of observed production leakage or live semantic quality.

The policy helper is included in both the sequence planner's reviewed dependency
inventory and the shared evaluator's execution content hash. Changing its bytes
blocks planning until dependency review; its execution-hash regression goes from
red to green. No semantic or human acceptance gate has been relaxed.

## Remaining acceptance

New prompt sources require review and merge to main, followed by normal main-only
publication and receipt verification before live use. No feature-branch prompt
versions have been published. After publication, repeat the bounded bilingual
matched workload on the deployed worker path, review the actual public replies,
retain failures alongside latency, and repeat existing-session/rollback and the
small browser-proxy smoke before enabling the candidate. The current early-text
optimization has no live latency or bilingual semantic acceptance yet.

## Verification record

The [sanitized evidence](test-evidence/issue53-current-acceptance-20261021.json)
retains both live campaigns and the red/green evaluator checks. Current integrated
boundary, streaming and SQL checks pass all 64 tests, including surrounding
whitespace normalization so the public acknowledgement matches saved rendering. The required place/photo
target passes 591 JavaScript, 429 API/database and 95 standalone checks in its
serial rerun. Its first run had one database serialization-conflict failure;
the isolated six-case background rerun passes. The first concurrent shared-suite
run exhausted the macOS system file limit; serial evaluator/pin checks pass 48.

The expanded English offline matrix retained two failed rows (38 completed):
one exchange was durably saved and publicly completed before a readback assertion,
and one failed before worker dispatch. They are not successful acceptance rows.
The serial English rerun passes all 40 rows and ten checks with no SQL resource
error observed. The Chinese matrix and negative-stream checks are still in
progress. The diagnostic observer records command failures without changing
their outcomes. No task-owned containers remain from the earlier live
campaigns. Other local virtual machines hold most of the host's file handles;
no unrelated services have been stopped or reconfigured.
