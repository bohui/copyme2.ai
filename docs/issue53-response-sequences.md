# Issue 53: additive offline conversation profiles

This prerequisite extends the existing profiler with connected synthetic
conversation scenarios and paired result ingestion. It reuses the merged PR92
framework, rather than introducing another dataset publisher, judge, receipt
validator or budget implementation. **It does not establish preserved model
quality or authorize a release.** No production optimization is included.

Base: `bb31f44ac8cb1c31baad8db418157b96dbe0eee0` (PR92 merge).
Reviewed framework code: `0fe69a5b66fc2b17da35398b1f79e192febc188c`, including
current-run receipt fix `a9724f7ed51423b5131c7690ab2e049d5c80b3be`.
The planner rejects changes to the pinned shared evaluator/receipt core until
that dependency is reviewed. No PR92 shared file is changed here.

## Reused interfaces

- `memoir_skill_eval_suite.plan`, `judge_definition`, `quality`, `Budget`,
  `digest` and `unavailable` own existing catalog, rubrics and scoring contracts.
- `memoir_skill_eval_application.verify_witness` validates current-run native
  receipts against the runner's independently retained dispatch ledger. The
  receipt capsule cannot supply its own dispatch authority.
- `controlled_native_state.open_case` / `snapshot_case` clone an initial SQL
  state into separate disposable baseline/candidate branches.
- `canonical_turn` consumes the normal backend streaming HTTP/ASGI reply and
  persistence path. `profile_canonical_controlled.offline_settings` strips
  inherited service authority. Its old hard-coded experimental variants and
  stop-on-first-failure campaign are not used.

The versioned manifest references stable PR92 interviewer IDs and the existing
`conversation_phase_cases.json` rubrics. The latter's mocked replies and obsolete
prompt-description metadata are not baseline model-quality evidence.

## Scenarios and actual witnesses

`tests/evaluation/response_sequences.json` contains six paired scenario families
in `en-AU` and `zh-CN`: 12 connected sequences, 80 planned application rows
across two arms at one sample, including four saved-result replay rows. It covers
name-only and name-plus-story introductions, short birthplace extraction clues,
long emotional narration, corrections, already-answered facts, stop, skip,
language switching, photo-caption versus pixel evidence, public-reference versus
personal testimony, persisted resume, saved replay and future-turn rollback.

Each resumed turn follows two saved turns and an explicit close/reopen action.
The controlled adapter closes storage and replaces the runtime, reads the same
persisted project, checks original source IDs and prior replies, and captures the
actual governed request's current source and prior exchanges. It does not label
a one-turn supplied-history fixture as a resumed execution. Saved replay uses the
same client-turn identity and must preserve both source and reply while consuming
zero generation dispatches.

The full native regression executes all 12 sequences: 80 completed application
rows and 76 mocked worker dispatches, including four saved replays with no
dispatch. It observes real SQL persistence, stream publication and fresh-runtime
context recovery. Eight rows in the existing language-switch scenarios fail
the deterministic gate: the current language parser does not apply the natural
language override forms in those scripts. Their failed gates remain visible;
test success means the limitation is detected, not that those contracts passed.
Worker outputs are synthetic fixtures, so none of these results establish model
quality. Background extraction/composition is not drained; source durability
does not establish semantic extraction or derived-artifact quality.

Rollback requires an explicit test-only `controlled_rollback=True` plan option.
Inside the credential-stripped process and mock transport, the candidate uses
`synthetic-byte-bpe` before rollback and the approved baseline route
`gpt-5.6-luna-pooled` on the next generation. Request, governed packet and saved
session readbacks must agree, while saved testimony and replies remain unchanged.
These process-scoped overrides are restored after each call and change no
configuration files or running app. Without this option, all four future
rollback rows stay unavailable. Non-null provider descriptors remain rejected;
this mock route exercise does not attest effective provider policy.

Eight additional bilingual fault scenarios inject malformed output, upstream
disconnect, timeout or commit failure. Every planned row remains in the result;
the failed turn preserves its accepted original source without a saved reply or
false save milestone. A disconnect may occur before any public text is released,
so private upstream fragments are recorded separately from public observations.
After a skip changes privacy preferences, the current-policy SQL tail may omit
an older assistant reply. The gate checks this eligibility readback separately
from durable saved replies and original narrator sources; an eligible exchange
missing from the governed packet still fails.

## Offline commands

```sh
# Default: no client, account, database, model or hosted writes.
python scripts/profile_first_reply.py > /tmp/issue53-plan.json
python scripts/profile_first_reply.py plan \
  --scenario issue53/resume-replay-rollback/en-AU --samples 1

# Import synthetic application results plus the separate host runner receipts.
# Paths inside receipts resolve within that receipt directory; symlinks and
# escaping paths are rejected. These commands do not dispatch a judge.
python scripts/profile_first_reply.py blind --plan-file /tmp/issue53-plan.json \
  --results /tmp/run/results.json --receipts /tmp/run/receipts.json \
  > /tmp/issue53-blind-packets.json
python scripts/profile_first_reply.py compare --plan-file /tmp/issue53-plan.json \
  --results /tmp/run/results.json --receipts /tmp/run/receipts.json \
  --reviews /tmp/blinded-review.json > /tmp/issue53-comparison.json
```

Comparison intentionally exits 1 and always returns `release_accepted=false`.
A missing result or judge/receipt remains unavailable, never silently removed.
Malformed, duplicate or unplanned inputs fail closed. The legacy explicit
`first-turn` command remains a dispatching diagnostic; it was not run here.
There is no sequence live-execution switch.

The native adapter is an explicit **test-only** callable, not a new live
harness. Run its tests through the existing isolated supervisor, with native
`initdb`, `pg_ctl`, `psql` and the repository test dependencies available:

```sh
issue53_checks=$(mktemp -d /tmp/issue53-checks.XXXXXX)
python scripts/run_isolated_check.py --root "$PWD" \
  --output-dir "$issue53_checks" --name focused --timeout 240 -- \
  python -m pytest -q --basetemp="$issue53_checks/pytest-focused" \
  tests/test_issue53_profile_sequences.py \
  tests/test_issue53_sequence_application.py \
  tests/test_first_reply_profiler.py \
  tests/test_skill_eval_interviewer.py tests/test_skill_eval_receipt_replay.py

python scripts/run_isolated_check.py --root "$PWD" \
  --output-dir "$issue53_checks" --name saved-plan --timeout 240 -- \
  python -m pytest -q --basetemp="$issue53_checks/pytest-saved-plan" \
  tests/test_issue53_saved_plan.py

python scripts/run_isolated_check.py --root "$PWD" \
  --output-dir "$issue53_checks" --name fault-streams --timeout 240 -- \
  python -m pytest -q --basetemp="$issue53_checks/pytest-faults" \
  tests/test_issue53_offline_coverage.py -k negative_streams

# Execute each locale in its own process: six sequences / 40 rows / 38 mock calls.
# Set the selector inside the supervisor's credential-stripped child environment.
for locale in en-AU zh-CN; do
  python scripts/run_isolated_check.py --root "$PWD" \
    --output-dir "$issue53_checks" --name "matrix-$locale" --timeout 360 -- \
    env ISSUE53_TEST_LOCALE="$locale" python -m pytest -q \
    --basetemp="$issue53_checks/pytest-$locale" \
    tests/test_issue53_offline_coverage.py -k 'not negative_streams'
done
```

Run these groups separately so a slow native fixture cannot obscure the status
of focused or fault checks. Both locale runs are needed to cover all 80 rows.
Each runs all eight scenario/receipt checks and retains its own plan, results,
comparison and cleanup receipt. Fresh fixed artifact directories avoid pytest's
rotating temporary-directory cleanup; use a new check root for another campaign.
The locale selector is test-only; the default
still exercises the full bilingual manifest. Timeouts bound test execution and
are not response-latency acceptance targets.

The independent review of `71dbb93` confirmed 86 focused checks, eight fault
checks and a 24-row native subset (20 mock calls, four replay rows and four
rollback rows). Its combined 102-check run timed out after 600 seconds; that
review did **not** independently confirm the complete eight-check/80-row matrix.
Earlier full-matrix results in this document are owner executions. The new
follow-up evidence records separately generated locale cohorts against the
saved-plan fix and identifies each check's source hashes and review limits.

The adapter admits only mocked worker transports, strips service credentials,
blocks external sockets, and allocates/removes its own native PostgreSQL
clusters. All database writes are synthetic and disposable. No configured
application database or running app is used.

## Frozen plan, evidence and comparisons

Plans freeze application source bytes, prompt sources and publication receipts,
configuration source files, dataset/rubric content, profiler/adapter bytes,
PR92 evaluator source and the complete planned judge definition. They record the
Git revision, fresh run ID, separate arm invocation IDs, sample count via the
planned rows, and explicit skill/judge/time/deadline budgets. Inherited runtime
settings are not inspected. Optional allowlisted variant descriptors retain
unknown model/effort/provider policy as null. A requested effort or a route name
is not evidence of effective provider policy.

Runner budget records acquire unique dispatch IDs, row IDs and current context
before awaiting transport; failed calls consume allowance. Comparison validates
the root ledger against the current plan and passes exact independent row slices
to PR92's native verifier. Rewritten receipt files, incomplete/tampered ledgers,
old run IDs and fabricated resumed/replay state cannot pass those checks. The
separate sequence receipt binds before/after readbacks and public-stream clocks.
Each captured governed packet is a checked projection of the exact request
envelope hashed by the independent runner ledger. Rewriting a sequence receipt
cannot invent a different dispatched context or policy-authorized omission.
As with other offline artifact ingestion, a user-authored replacement for the
entire trusted runner ledger is not proof of real provider execution. Imported
artifacts remain advisory and cannot certify release.

Each branch begins from an independently checked identical SQL seed, then
continues its own saved replies. Later histories can diverge. Seed/prestate
hashes and `paired_prestate_equal` / `context_confound` are retained in the
report; a connected candidate history is not claimed as an identical later
prestate. A later authorized study may use the existing snapshot helper for
additional per-turn, identical-prestate comparisons, clearly labelled separately
from connected-sequence results.

Blind A/B packets hide arm, route, effort and timing labels and reuse PR92's
single-output interviewer policy/rubric. They include sequence requirements and
actual saved sources, replies and supplied model context. Session routing fields,
prompt-version metadata and execution timestamps are excluded from semantic
witnesses. The packet hash binds
imported judgments to the frozen evaluator and evidence. Both arms' evaluated
model identities are excluded from independent assessment. PR92's categorical
judgment shape remains unchanged: `status`, `citations`, `rationale`,
`critical_violations`, `response_id`, `model`. A/B citations use existing evidence
keys such as `output`, `task`, `binding`, `witnesses`.

A **separate blinded human preference annotation**, exported as
`human_preference_contract`, is additionally required for paired interpretation.
It is not another model prompt or judge. For each pair, imported reviews have:

```json
{
  "<pair_id>": {
    "packet_sha256": "<exact exported pair hash>",
    "A": "<existing PR92 judgment object>",
    "B": "<existing PR92 judgment object>",
    "comparison": {
      "status": "pass",
      "citations": ["A.output", "B.output", "task"],
      "rationale": "Specific supplied facts and public-response evidence",
      "critical_violations": [],
      "response_id": "<independent review receipt>",
      "model": "human:<reviewer-pseudonym>",
      "reviewer_kind": "human",
      "preferred_side": "tie"
    }
  }
}
```

`preferred_side` is A, B or tie; incomplete evidence requires unavailable.
Critical violations force failure, including unsupported facts, ignored stops
and lost testimony. A malformed or missing preference annotation cannot erase
an already validated critical side judgment. Scores/annotations remain advisory
pending the separate bilingual human-heldout acceptance process. There are no
invented human labels in this change.

Deterministic public validation, source fidelity, language provenance metadata,
ownership, idempotency, save and continuity contracts stay separate from
semantic quality and latency. The seven adapter contract labels describe this
controlled application's observations; they do not certify the linguistic
quality or factual adequacy of its fixture replies.

Reports retain every planned row and failure reason and include overall,
locale, phase and joint locale/phase views. Only complete, witnessed pairs enter
paired timing summaries. Counts, unknown observations, raw samples and
candidate-minus-baseline deltas remain visible. No absolute latency SLA,
acceptable quality loss, small-sample p95 or production percentile is invented.
A faster failed response cannot improve acceptance status.

Public timings distinguish an annotated meaningful excerpt in received
`text_delta`, the validated question-pool event, `reply_complete`, and
`conversation_saved` plus independent durable readback. Headers, private model
JSON, progress and generic filler do not satisfy the excerpt observation. The
excerpt's semantic adequacy still requires review. Unemitted milestones remain
null; a cached replay need not emit a new save event. Browser paint is not
measured. Actual prompt metadata in the governed packet is retained separately
from requested descriptors. Provider usage/cache tokens, policy, internal
attempts/retries and load observations remain unknown when unavailable, rather
than being replaced by zero or synthetic worker counts.

## Remaining acceptance and bounded live work

Current authorized live/provider/hosted budget: **zero**. Nothing here dispatches
live calls, publishes datasets/prompts, enables hosted rules, changes credentials,
changes configured databases, merges or deploys.

A later explicitly authorized pilot can start with the two locale resume
sequences: six baseline/candidate generated-turn pairs (12 foreground generation
attempts total), plus four saved replay requests that must make no generation
attempt. Predeclare a 12-attempt hard foreground ceiling, count retries and
corrective proposals against it, use the existing 120-second per-call/600-second
campaign bounds, and leave any exhausted rows visible. Judge calls need their
own at-most-12-attempt ceiling. These are budget ceilings, not latency objectives
or authorization to run. Background extraction/research/composition fanout needs
its own inspected and approved bound before any live execution; it is not
silently funded by the foreground allowance.

Before release consideration: resolve the detected language-switch baseline
failures; verify actual provider policy and complete route/prompt/configuration
provenance; exercise the full bilingual manifest against real model outputs,
including rollback, failed-save/stop/ownership and derived testimony handling;
perform the blinded comparisons through the existing evaluator; obtain disjoint
native-speaker development and heldout review with agreed calibration criteria;
and review every locale/phase quality or completion/save regression. No quality
loss is authorized by aggregate latency improvements. Hosted publication and
PR92's remaining human/live acceptance are separate gates.

Raw imported provider metrics are retained under `imported_provider_metrics`
with `source=unverified_import`; they are not promoted into observed provider
metrics. The verified controlled runner ledger reports fixture completion
identities separately as `runner_observations`. This slice has no live-provider
policy/usage attestor, so provider metrics remain null even when an imported
JSON claims low effort, token usage or zero retries. Language-switch judge
context uses each turn's requested reply language; report locale identifies the
sequence's initial locale cohort.

## Review follow-up: blinding and partial evidence

Blind export serializes available labels in canonical A/B order, independent of
host baseline/candidate insertion order. Each side now also has its own
`packet_sha256`. A review may supply `side_packet_sha256: {"A": "...", "B": "..."}`
to retain an independently bound side assessment when its mate later becomes
missing, failed, timed out or unavailable. A full pair hash still binds paired
preference. A missing mate or invalid preference cannot erase a valid critical
side judgment. An unavailable/not-applicable human preference has no direction:
a stray `preferred_side` is ignored, while valid critical evidence still blocks.
An already valid pair binding takes precedence over an optional malformed side
binding; null, array, number or string alternates cannot erase its judgment.
Language/work/stop failures retain a failed contract result after all native,
stream and current-run checks. A verified durable after-state can still anchor
the next turn, avoiding a spurious lost-chain diagnosis after a language failure.
Every generated reply also requires a non-null saved plan validated by the
existing application schema, including an explicit work decision. Missing or
malformed plans fail evidence validation; removing one cannot erase a work/stop
failure or restore its pair to latency comparisons.
