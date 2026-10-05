# Integrated PR8/PR9/PR10 Mac acceptance

The authorized native/offline phase is complete. Code head
`c1f5e296d6f2dd921c5474dc7c613abc1968b8fc`, tree
`4e1afdc3552c4c6b8e45c2644ae12b8e85e6eee6`, passed **1,194** Python cases,
with **4 live-only skips, zero failures and zero errors**. All 29 standalone
browser journeys passed; additional evidence and its limits appear below. Branch:
`bohui/copyme2.ai:codex/mac-pr9-pr10-validation-20261004`.

[Machine-readable evidence](test-evidence/pr8-pr9-pr10-mac.json) records all
commands, exact heads, log/JUnit hashes, source trees, focused results, earlier
failed attempts, preservation and cleanup. Detailed logs, XML and screenshots
remain in the isolated worktree's ignored `output/mac-validation/resume`.
A later documentation commit must retain the tested `apps`, `supabase`,
`skills`, `tests` and `scripts` trees recorded there.

The approved [local Langfuse repair and synthetic canary](langfuse-mac-timestamp-repair-20261005.md)
subsequently passed fresh API/database readback, with 176 gateway checks and
zero model/judge/photo calls. That follow-up changes local gateway configuration
and records documentation here; Memoir's tested source trees are unchanged.
Its browser confirmation and the full five-case live acceptance remain pending.

The deliberate PR8 integration is merge
`0c1571677ffe331c37493c8c78be4e5e6646ef89`, ordered parents
`9359d4baa549a71458eec079ff2415f6bad7366f` and verified PR8 main merge
`a4d8abf810eefa1ec36cc219710f8ac954bb52e9`.
[Integration evidence](pr8-pr9-pr10-mac-integration.md) describes the combined
photo helper and metadata conflicts. The original cloud PR9/PR10 merge remains
`d11a25389edabfd5e0f5d0e92a74174b0bf7badb`; its reviewed parents and tree are
recorded in the JSON. SQL is unchanged from that merge. Canonical MemoryEvents,
original accepted narrator sources, attributed/timing event vetoes, null-claim
rejection, cN validation and metadata stripping remain covered.

| Check | Observed result |
|---|---|
| Complete native Python suite | 1,198 collected: 1,194 passed, 4 skipped, 0 failures, 0 errors; 275.43 seconds |
| Native Temporal | All 6 cases passed, included above; real Temporal/PostgreSQL with controlled provider |
| Pytest browser UI | All 48 passed, included above; 16 use actual PostgreSQL/router/private-worker paths |
| Standalone browsers | 29 passed, 0 failed, 0 unconfirmed; both locales, blocked-photo and map/gallery variants |
| JavaScript, including composer | 173 passed, 0 failed, 0 skipped |
| Production build/API rewrites | Build passed at `ec7f4487`; identical final `apps` tree; both compiled destinations select task API port 56888; retained proxy check reports test auth |
| Additional renderer invocations | Two command receipts passed; selected real/fallback modes were not retained and are unverified; cached assets match all three retained hashes |
| Native redirect canaries | 18 passed; zero unapproved sink requests |
| Offline URL policy | 20 passed: 9 accepted, 11 rejected |
| Localization/ICU | 541 messages across en-AU and zh-CN; ICU passed |
| Route audit | All 63 required routes represented among 124 app routes |
| Python compilation | Passed |
| Photo package | 17 checksums verified; initial combined-tree run passed 395 cases plus 7 subtests; 90 unittest cases overlap |

Component counts overlap the full run and must not be summed. The 42
`test_place_photo_browser` cases are API eligibility tests, not more UI cases.
The four skips are configured-provider current/earlier-context follow-up
evaluations in two locales. One upstream Starlette/httpx warning remains.
Optional Crawl4AI is mocked offline; no live search/download was performed.
The redirect frame probe did not observe an OOPIF target. Worker/service-worker
redirects and detached sessions remain unverified; these receipts establish
the exercised fixture paths, not complete egress containment.

The renderer commands are identical and their empty logs do not record
`MEMOIR_RENDERER_FIXTURES` or `MEMOIR_RENDERER_EXPECT_FALLBACK`. Their names do
not establish mode selection. The JSON now records this gap and all three
recomputed cached bundle hashes; possession of the assets does not establish
their use. To establish both modes, rerun only those two checks with explicit
mode/asset receipts and fresh task services. No rerun was performed for this
documentation correction.

The retained `resume/production-proxy-verification.json` records both API
rewrite rules, the task API/Next origins and test auth. The retained compiled
`routes-manifest.json` matches those destinations and hashes to
`f2d658d236d69511a71a5caef29bed544e8db3efb34e23c1bd11c5d09d155bd5`.
Individual request paths, HTTP statuses and response bodies were not retained
in that proxy receipt, so it does not establish an independent auth response
for each rewrite. The JSON preserves the observation at that resolution.

Five defects were fixed through the agreed command/runtime/browser seams:

1. Post-child Git failure could discard a completed browser result. Identity
   is now captured before launch, receipts are atomic, and missing identity
   blocks execution with an explicit non-success receipt.
2. Cloud review reproduced a timeout leaving a SIGTERM-resistant grandchild
   after its leader exited. Cleanup now checks the exact group created by the
   runner, escalates within it and records whether it disappeared.
3. Cloud review reproduced supervisor SIGTERM leaving the child alive and
   receipt `running`. Signal handlers record intent; ordinary control flow
   cleans the owned group and records `terminated`, signal 15, wrapper exit 143
   and the actual child outcome. Both reproductions failed before repair; all
   six runner cases pass at the final head. Blocked group verification is
   recorded explicitly without losing the primary outcome.
4. The preview fixture changed HTTP phases before observing a pending poll
   after a clock jump. It now holds/completes that response and observes error
   and recovery responses before changing phases. All original UI and
   minimum-three-poll assertions remain. Both variants and all seven recall
   cases pass. See Playwright's [clock semantics](https://playwright.dev/python/docs/clock).
5. The Temporal recovery fixture used a timeline-only provider for an
   unrelated composer preparation. Diagnostics showed two timeline calls
   then a composer call, all logged as timeline by the fake provider. Packets
   contained 5, 15 and 1 sources; the last was outside the recovered range.
   The controlled endpoint now isolates its selected role. The exact two-call,
   5/15-source recovery, covered-round-20, stale-token and no-new-narrator-turn
   assertions remain. Production worker behavior was unchanged by this fix.

The red broad attempts are retained: `ec7f4487` had 1,191 passes, one preview
fixture failure, four skips and zero errors; `5b543390` had 1,193 passes, one
Temporal fixture failure, four skips and zero errors. Earlier PR9/PR10 failures
remain in the [previous report](pr9-pr10-mac-validation.md). They were not
relabeled as passes or all assigned to ENFILE: three earlier retry assertions
did not establish their underlying child-failure cause. Those cases passed in
the final whole-suite run with assertions intact.

Passive final-run file-table samples ranged from 108,562 to 122,678 of 122,880
slots. Host PostgreSQL's SysV constraint was avoided with supported disposable
UUID AppleContainer `postgres:18.3` fixtures: no shared mounts/published ports,
TCP disabled, `container exec psql`, exact cleanup. No host limits/settings,
unknown IPC or unrelated processes were changed. Task API PID 33360 and Next
PID 33398 were stopped after checking session/port ownership; both ports closed
and zero task PostgreSQL containers remain. Original dirty checkout and older
Issue2/Issue6 HEAD, NUL-delimited status and tracked-diff fingerprints match.
Caches/evidence remain. One overly broad read-only inventory emitted shared
container configuration into local tool output; no values from it were added
to this branch/handoff, and subsequent inventories emit task IDs/status only.

The parent coordinates cloud rereview and landing. Current PR3, PR9, PR10 heads
and exact PR8 main are verified ancestors of this candidate. Review/land the
combined candidate against verified current main, retaining the conflict
resolutions and Mac fixes. Coordinate handling of incorporated PRs after the
approved candidate lands. No PR was merged or retargeted, no deployment or
production migration was made, and no credentials or paid commitments were
created.

No new live pilot or five separate 50-round run was made. Baseline `d67f390`
remains 205 pass / 8 fail / 37 unavailable of 250; affected `28acda14` remains
152 pass / 5 fail / 43 unavailable of 200. Diagnostic pilots are not acceptance.
Read-only Mac diagnosis on 2026-10-05 found zero trace/event rows, 3,750 API
scores with year-9999 timestamps, and zero configured evaluator/job records in
the requested Langfuse project. ClickHouse 26.9.8.3 interprets Langfuse's numeric
millisecond/microsecond timestamps as seconds; historical inserts failed with
DateTime64 overflow. A query-local compatibility setting correctly decoded
both units. Persistent repair, telemetry canary and durable API/browser
readback remain pending approval. See the [live acceptance plan](pr8-pr9-pr10-mac-live-plan.md)
and its sanitized [database evidence](test-evidence/langfuse-mac-readonly-20261005.json).
Cloud review, approved provider/judge setup and budget, and durable readback
precede the live phase; missing judge configuration must not be invented.
The [cloud setup handoff](pr9-pr10-cloud-test-setup.md)
contains reproducible commands and credential names without secret values.
