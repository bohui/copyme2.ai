# Issue 70: two logical lanes (frozen before implementation)

Base: `83e48e166568fe949eccd6f68ffa13273dcf55af`, 2026-10-16.
Isolated worktree `/workspace/issue70`, branch `agent/issue70-two-lanes`.
All 51 published heads were inspected; every non-main head is an ancestor of
main. GitHub returned no open PRs. The original checkout is clean. No external
agent was contacted. Unpublished work outside this workspace cannot be verified.
No root/API AGENTS.md or repo .agents/skills exists in this environment. Read the
memory-context, author-timeline, place-journey skills and timeline contract.

## Foreground dependency profile

`run_lifetime_turn` holds local and distributed interactive leases through final
ASGI publication. Sequence: authorization/replay → original acceptance (including
literal privacy) → current language/policy → bounded checkpoint + complete tail
+ optional lexical retrieval → one collector → proposal validation → optional
place persistence → required plan/reply/round transaction → conversation_saved
→ workspace event → synchronous outbox drain → result → release lease.
Optional artifact completion is also awaited before proposal validation.
There is no currently admitted transcript resume. The two-lane flag must retain
fresh bounded threads. Engine homes are disposable, not durable logical lanes.
This is a structural critical-path profile; no live model timings are claimed.

## Decision and bounded slice

Server flag `MEMOIR_TWO_LANES`, absent/0 by default. A retains one collector pass,
current input/corrections/policy, chosen-question validation and atomic save.
The existing unique project timeline lane is B: durable accepted originals,
monotonic target source, bounded pages, exact version/offset and lease receipts.
Extend that lane's extraction pass for optional places and prepared questions;
never start a second full foreground model call. Reply-only decisions can finish
as empty processing without a model. Pending accepted input still remains an
extraction obligation after a failed reply. The existing composer remains
cadence/opt-in driven with its own summary_source/summary_offset and round ordinal.

B proposals are hints, never preference, access, delivery or billing authority.
Bind optional output to source version, canonical page/snapshot, policy,
preference, phase and execution generation; compare current dependencies again
inside the atomic page commit. Candidate reads exclude stale dependencies before
A pins its packet. Do not inject updates into A in flight. Existing publication
fences remain mandatory. Workspace polls/read APIs operate independently of
public reply completion; failed/empty updates preserve activated state.

Dialogue coverage_end + all positions K+1..N-1 (including tombstones) remains
separate from composition's character-fragment cursor. Occupancy-triggered
canonical compaction remains fail-closed; no summary may pretend to cover a gap.
Any unimplemented background checkpoint/warm-runtime requirement must be listed
as a gap rather than inferred from existing primitives.

## Frozen checks and matched live protocol

TDD red/green for flag-off compatibility; blocked B barriers vs meaningful A,
chosen question and saved reply; acceptance-vs-reply IDs and save failure;
name-only/rich/short/later/resumed/English/Chinese/language request/question/pause;
worker at 20/current23/tombstones/oversized raw tail; burst coalescing, source
versions, stale CAS, policy/phase/preference/generation changes, lost lease,
cross-scope denial, duplicate/crash/restart/cancellation; existing source,
composer/protected edit/photo/workspace/transport regressions. Preserve inherited
failure identifiers and unavailable checks. Native PostgreSQL only, disposable.

No live dispatch is authorized. Before any later campaign, freeze exact base and
candidate SHAs, pinned harness `0.156.1` and adapter, both using collector alias
`gpt-5.6-luna-memoir-low` and configured effort (record effective settings), same
B alias/budget and same pre-turn database snapshots. Scenarios: name-only, rich
first, short, resumed correction, explicit question, pause, language change,
pending upload, long 23+ turn interview; English and Chinese; B normal/blocked/
failed. Five matched pairs per scenario/language/B condition (270 pairs; 540 A
calls maximum), randomized AB/BA order; 120s turn deadline, 600s B deadline,
90-minute campaign deadline; no automatic campaign retries. Separate bounded B
budget: at most 540 calls, 65,536 input-byte upper bound and 16,384 output-token
headroom per call. Foreground max 65,536 input-byte upper bound / 8,192 output
headroom; invalid-output repair counts against the call ceiling. A funded total
cost ceiling and explicit provider authorization must be supplied before run.

Measure first meaningful public text, full useful validated question, durable
save, first playable audio if supported (otherwise unavailable), B lag, failed
calls, repetitions/inappropriate questions, correction/privacy failures, retries,
provider usage/cost (unknown if not exposed). Review usefulness/grounding against
originals blind to variant. Report paired distributions, failures and sample
limits, including completion/save regressions. Deterministic barriers prove
ordering only. AC9/10 remain release blockers until authorized matched evidence
shows useful-question improvement without safety/correctness/save degradation.
Flag remains OFF; no deploy/migrate/merge or GitHub review comments.

## Adapter authority

Repository pins Codex 0.156.1 in Containerfile/compose defaults. Official current
protocol source inspected 2026-10-16:
https://github.com/openai/codex/blob/main/codex-rs/app-server/README.md
The protocol supports initialize, thread/start/resume and turn/start. Support for
resume does not prove bounded transcripts. Keep existing cold admission and
interruption/partial-stream validation; do not add unsupported warm-pool APIs.
