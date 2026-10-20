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
context recovery. PR95 originally retained eight language-switch failures. The
continuation from main `8b8b494e087a00641fb56094a4b5dc638cc6878d` extends the
existing leading-command parser for English "from now on" and Chinese temporal
prefixes, clearing those failures without changing narration or model settings.
All 80 deterministic matrix rows now pass. Worker outputs remain synthetic
fixtures, so none of these results establish model
quality. Background extraction/composition is not drained; source durability
does not establish semantic extraction or derived-artifact quality.

New real backend HTTP/NDJSON regressions verify that a command changes the later
reply language, survives a fresh runtime with stale UI language, and preserves
source IDs, original text/version, the saved name and previous replies. Quoted
commands leave the established language unchanged. Prompt bytes, routing,
reasoning settings and the running app are unchanged. Evidence is recorded in
`docs/test-evidence/issue53-language-gate-20261020.json`.

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
Each runs all ten scenario/receipt checks and retains its own plan, results,
comparison and cleanup receipt. Fresh fixed artifact directories avoid pytest's
rotating temporary-directory cleanup; use a new check root for another campaign.
The locale selector is test-only; the default
still exercises the full bilingual manifest. Timeouts bound test execution and
are not response-latency acceptance targets.

The initial independent review of `71dbb93` confirmed 86 focused checks, eight fault
checks and a 24-row native subset (20 mock calls, four replay rows and four
rollback rows). Its combined 102-check run timed out after 600 seconds; that
run did **not** confirm the complete eight-check/80-row matrix. The reviewer
subsequently completed both 40-row cohorts at `7892c9c`, plus 24 saved-plan,
86 focused and eight fault checks, with cleanup verified. The earlier incomplete
review status is superseded. Historical owner and reviewer evidence remain
separately identified. The language-gate continuation also has independent
re-import of both current-source cohorts with real receipt verification.

The language-gate continuation recorded two inherited HTTP replay tests failing
on `trace.question_pool`, also absent on unchanged main `8b8b494`. The subsequent
observability slice reconciles those tests with the existing privacy contract:
the public trace has a completed summary, while the full chosen plan and work
decision are checked in private SQL readback. The previously unreached cold
replay, paused generation, conflicting input, source/reply identity and lease
assertions now run. Private planning is not added to the stream.

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
`text_delta`, `question_validated`, `reply_complete`, and `conversation_saved`
plus independent durable readback. Headers, private model JSON, progress and
generic filler do not satisfy the excerpt observation. The excerpt's semantic
adequacy still requires review. Unemitted applicable milestones remain null.
Browser paint is not measured. Actual prompt metadata in the governed packet is retained separately
from requested descriptors. Provider usage/cache tokens, policy, internal
attempts/retries and load observations remain unknown when unavailable, rather
than being replaced by zero or synthetic worker counts.

## Governed public milestone observations

This slice began stacked on the unchanged PR96 language-gate head
`8315df3e7876374f699ac0ab07b8481659660606`. PR96 subsequently merged into main
at `f185c1c5bba7cbed7030c59944be103ca7a17490`; PR97 is rebased and targets that
main state. Earlier integration checks combined main
`7d12641357b69ef767a49e171cc188e23a039c72`, PR96 and the task source in a
disposable checkout, preserving main's separate place-workspace fix. The
required regression target is also run on the rebased branch. Original
stack receipts and source hashes are retained
in `docs/test-evidence/issue53-stream-milestones-20261020.json`.
The independent contract review of initial PR97 head `29d34eb` found three
introduced defects that the initial matrix missed: malformed native completion
payloads, normal web settlement at truncated EOF, and unbound/premature profiler
completion receipts. The repair and its new red/green evidence are recorded in
`docs/test-evidence/issue53-stream-contract-repair-20261020.json`; the earlier
milestone report remains historical evidence, not proof that those defects were
absent.

After full proposal validation and required persistence, the backend sends a
fenced `question_validated` event containing `has_question:true` and the public
project/client-turn/accepted-source identity when there is a chosen question.
These identifiers already appear in source acceptance. Its received timestamp is a **post-commit validation
attestation**, not the internal validation finish or question-text delivery time.
It reveals no chosen ID, candidate questions, work decision or private plan.
Stopped replies emit no question milestone.

Every generated path sends `reply_complete` after its final public text delta
and before the existing save attestation. The default payload includes the
public `reply` required by native consumers, the same three identity fields,
`cached:false` and `has_question`; the existing two-lane public response envelope
and reply identity are preserved. The native schema remains strict and its
reducer retains the accumulated reply. This marks completed public reply text, not
terminal-result delivery or completed background work. It does not replace the
client's `conversation_saved` readiness check. Clean EOF after completion alone
rejects for recovery; completion data cannot become a successful web result.
JSON response bodies are unchanged.
Both markers use the existing publication fence and are rejected without it.

Saved replay produces no artificial generation or save events. A cached `result`
must match the expected project, client turn, accepted source and saved reply
before supplying its observed reply-completion time; new-text, new-question
and new-save timings are not applicable. Stopped turns also have no applicable
question timing. If the target turn failed to save, its planned replay remains
explicitly unavailable and consumes no generation dispatch; the campaign still
retains every planned row. Comparison derives these exclusions from the frozen planned
row, reports `not_applicable` separately from `unknown`, and leaves their paired
deltas null. Raw observations remain available. A generated completion requires
prior source acceptance, matching identity, strict flags and an exact match to
the public text accumulated so far. Later text revokes a premature completion;
the first qualifying final receipt wins over valid duplicates. Import also binds
that text to the separately validated canonical saved reply and derives the
client-turn identity from the frozen plan. Resealing a sequence capsule cannot
promote a bare early marker or foreign/wrong-text cached result into eligible
timing evidence while leaving native receipts and the runner ledger unchanged.
Historical private-pool progress is read only with completed status and matching
turn/project after source acceptance; server publication is not restored. Older
unbound observations remain historical and cannot supply these strict timings.

Native controlled tests cover normal and cold-resumed generated turns, stop,
saved replay, two-lane and strategy paths. A blocked commit may coexist with an
early acknowledgement but cannot produce a question, completion or save marker.
A failed commit preserves the source for same-turn recovery. Disconnects at the
question delta or completion send cannot fabricate received completion/save;
retry returns the saved reply without another generation. Private plan readback,
source/reply identity and expired leases remain checked. A client stream test
also proves that the new metadata cannot unlock another answer before save or
settle a truncated stream normally. Captured real backend streams are consumed
through the shipped native API client, event schema and domain reducer, including
all 80 bilingual first/later/resumed/stop/replay rows. Mocked model output does
not bypass these consumer contracts. Malformed/foreign/premature marker tests
exercise the standalone observer and resealed current-run receipt imports.
The bilingual matrix and upstream-failure cases remain synthetic contract
evidence, not model-quality or production-latency measurements.

The broader owner run passed 228 checks and retained five failures in unchanged
two-lane background tests. The exact PR96 baseline reproduces all five, involving
strategy-proposal expectations and a stale background page. They remain visible
in the evidence; this slice does not claim the entire aggregate is green.

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

Before release consideration: verify these observations against real provider
execution and verify actual provider policy and complete route/prompt/configuration
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
