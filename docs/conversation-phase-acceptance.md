# Conversation phases: implementation and acceptance record

Issue: #59. Base: cc068523208842e2accde8d623a060a04143e78c.
Status: draft implementation; do not merge or deploy until remaining gates below pass.

## Contract and ownership

`conversation_phase` is an application-owned v1 envelope with phase, automatic/explicit
selection, preferred phase, pause, revision, bounded reason and source turn UUID.
It is stored under the existing owned project. Issue #60 must preserve this complete
validated envelope through later identity and checkpoint work, separately from summaries.
There is no life-stage, entitlement, language or completed-round change in this feature.

Dedicated GET/PATCH `/v1/agent/projects/{project_id}/conversation-phase` uses typed
controls and expected revision. Controls create no narration or completed round.
Current narrator control sentences are parsed independently in Python and SQL; quoted,
reported and negated statements cannot grant model authority. Automatic model proposals
are restricted to comfort/explore. Shape is explicit. Source correction reopens effective
exploration while retaining the explicit preference. Existing authenticated source,
lease, policy and turn guards remain active inside the original save RPC.

The additive migration wraps the latest photo/news/work-plan RPC instead of replacing
its validator. Late proposals fail their phase CAS while retaining accepted narration.
Accepted turns capture an immutable phase revision, so a later control wins even if it arrives before context construction. A retried narration may finish against current state without replaying obsolete control intent. Saved replies replay without regeneration and read back the current preference.
Guest transfer copies phase state with the existing project mapping and preserves newer
target state. DDL rerun is tested; no production migration has been executed.

## Evidence collected

- 41 pure policy checks: reversible modes, durable selection, strict schema, safe bilingual intent.
- 32 real PostgreSQL checks: RLS under `authenticated`, anonymous denial, cross-owner isolation,
  two simultaneous CAS writers, late proposal rejection, reply atomicity/replay, source correction,
  migration replay, legacy project resume, and guest transfer/retry.
- Four of those checks use streamed HTTP → actual collector orchestration/validation → real
  restricted-role PostgreSQL → authorized receipt readback. Only provider/Supabase HTTP transport
  boundaries are controlled. EN and ZH saved replies, original sources and one completed round
  survive retry while newer explicit shape survives replay.
- 104 existing photo, historical-news, work-plan and private-round PostgreSQL regressions passed.
- 148 affected runtime, phase API, streaming, historical-news and project-recovery checks passed.
- Web worker: 360 Node tests passed, including 15 new controls/revision/isolation/pause tests;
  Next production build, ICU catalog validation and syntax checks passed.
- Existing trajectory evaluator ran the 16 bilingual synthetic cases in
  `tests/evaluation/conversation_phase_cases.json`: deterministic gates passed. Two acceptable
  examples per case and a seven-dimension review rubric are provided. This validates fixtures,
  not live model naturalness. Semantic judge is not configured and live quality is not claimed.

Representative commands:

```
../issue53-recovered-venv/bin/python -m pytest -q tests/test_conversation_phase.py tests/test_conversation_phase_runtime.py tests/test_conversation_phase_routes.py
PATH=<existing-postgresql-17-bin>:$PATH MEMOIR_TEST_POSTGRES_BACKEND=native-tcp ../issue53-recovered-venv/bin/python -m pytest -q tests/test_conversation_phase_postgres.py
python scripts/run_langfuse_evaluation.py --cases tests/evaluation/conversation_phase_cases.json --output <local-output.json>
```

Every SQL run allocates and stops its own random loopback port and `/tmp` cluster. It never
uses a configured Supabase URL, existing database, customer data or production credentials.

## Acceptance criteria map

1. Name opening: new bilingual streamed real-persistence tests; gentle examples and aligned prompts.
2. Rich opening: existing short/long full-source extraction and same-collector runtime tests; new
   phase-specific rich-path real-persistence scenario passes in both languages.
3. Soft pacing: policy has no turn/length thresholds. Explicit selection and real streamed three/five/twenty-round phase invariance pass.
4. Return: legacy project initialization, current readback, replay and guest transfer pass;
   real browser reload/sign-in verification pending.
5. Controls: pure/API/SQL/JS scenarios pass; browser pause-during-generation pending.
6. Distress: bilingual control fixtures and reported-speech exclusions pass; examples reviewed,
   live model safety/quality not measured.
7. Early shape: control produces no artifact/round and preserves existing visibility code;
   narration remains gated at twenty while controls remain available (JS/real API checks). Browser rendering gate pending.
8. Correction: source edits and explicit workspace/chat event corrections reopen exploration; delayed chat corrections preserve newer choices. Five existing approved/locked prose regression cases pass.
9. Retry/failure: saved-plan failure/replay tests and real source/reply/round idempotency pass;
   explicit phase disconnect after durable save with stalled enrichment and cached replay passes.
10. Concurrent tabs: actual independent SQL sessions accept exactly one CAS and preserve narration.
11. Authorization: restricted-role RLS and API typing pass; model shape cannot grant explicit intent.
12. Background evidence: 104 existing SQL regressions plus historical-news runtime readiness pass;
   no background writer touches phase. Phase-specific stalled-worker and post-save cancellation pass.
13. Independent concepts: new table/control RPC changes only phase; existing language/round/draft
   gates remain untouched. Full Python aggregate: 3992 passed, 560 skipped.
14. Existing gates: existing private-round PostgreSQL regressions pass; phase controls create no
   round. Explicit phase-at-3/5/20 real streamed assertions pass.
15. Fast path: no new model/classifier or research call. One-collector/stalled-workspace checks pass. A controlled-provider real-runtime run measured first text 176.033ms, validated question 208.786ms and durable save 227.243ms separately; these are synthetic fixture timings, not live model latency.

## Open gates and limitations

Browser suite defines 14 EN-desktop/ZH-phone mocked scenarios but could not execute:
Chromium launch failed with socket EPERM; the supported cloud browser could not reach the
isolated dev server. No browser pass is claimed. Final Python aggregate at the pre-correction-wrapper tree: 3992 passed, 560 skipped; skips are not claimed as passes. The additive correction wrapper has a separate real-PostgreSQL acceptance run. Independent review at that tree passed 97 PostgreSQL, 50 Python and 15 JavaScript checks. Final wrapper review and final-head external checks are tracked on draft PR #61. Browser acceptance remains merge-blocking.

No live paid provider evaluation, production migration, deployment, credential setup,
commercial draft-policy change or historical project consolidation is authorized by this PR.
