# Issue 6: preserve canonical evidence occurrences

This is a narrow follow-up to the integrated progressive persistence work in
[PR 11](https://github.com/bohui/copyme2.ai/pull/11), based on main
`291622826cdfb776e946dcd92b65d2fdaf4923ad`. It does not rebuild canonical storage,
change the queue, or claim complete acceptance of
[Issue 6](https://github.com/bohui/copyme2.ai/issues/6).

## Main integration, 2026-10-07

The preserved five-file artifact (`a15174e2dcfa3c9297b7ed72c2946a888a890bfc`)
was applied in a fresh isolated checkout to verified remote main
`0658dfffee60694824f5ebe36a57a126756320bb`. Application was conflict-free;
upstream had not changed the three existing source/test files since the original
base. The preserved checkout and cancelled publication inputs were left intact.
Only this integration receipt differs from the preserved artifact.

Fresh checks against this main integration:

- Two English/Chinese wrong-occurrence regressions fail on unmodified
  `0658dff`, establishing that the defect remains present on current main
- The integrated branch passes 220 affected Python tests and 62 composer Node
  tests; compilation and diff checks pass
- All four new real-PostgreSQL/private-worker variants collect but skip because
  this cloud runtime lacks native PostgreSQL tools. Mac execution remains a
  separate gated requirement; no skipped check counts as a pass
- PRs 18, 19 and 23 have no changed-file overlap with this patch at the time of
  integration. Independent exact-tree/head review, native validation and required
  CI still apply before merge

The independently reviewed staged tree was
`b29c5d19a96b7feb4379899e0794e30ff790aa3c`. Review reran 220 Python tests,
62 Node tests, recursive invalid-reference probes and an interval-coverage oracle
without finding an actionable defect. Before publication, main advanced to
`fbf1a5183e33545e6f32efb2519d985df4247cee` through PR 23. That change affects
only `tests/test_photo_progress.py`; integration was a conflict-free fast-forward
and retained the reviewed implementation/test bytes. The refreshed affected suite,
including PR 23 photo-progress coverage, passed 223 Python tests; the composer
Node suite passed all 62 tests. Native persistence acceptance remains outstanding; this review does not close Issue 6's live or human gates.

## Demonstrated defect and repair

A canonical evidence reference can include an exact `char_start`/`char_end` span.
That span distinguishes repeated identical words in one original narrator source.
Extraction correctly permits a later occurrence when the earlier occurrence has
an explicit event-recording veto. Composer discarded the saved span and used
`text.find(quote)`, attaching generated prose to the earlier vetoed occurrence.

The projection now retains a valid explicit span. It preserves the existing
quote-search fallback only when both offsets are absent; a partial or mismatched
explicit span is never silently rebound. Previously accepted oversized suffix
ends are bounded to the source length only while preserving the known start and
verifying the exact quote. Canonical database rows are not changed. The `shared-composer-2` configuration
version invalidates prior bundles/checkpoints created with the old projection.
This uses the existing configuration-version mechanism. Configuration changes
also mark the prior chapters as projection-invalidated. A model cannot carry
those chapters forward: application validation sends that attempt through the
existing bounded repair loop before evidence review or rendering. Actual draft
evidence is also checked against the current canonical occurrence ranges, across
inline chapters, storylines, summaries, outlines, titles and proposed replacements.
Copying an old chapter into a replacement cannot bypass the check. An offset-free
reference cites the whole source and is accepted only when canonical evidence
covers that entire range; supported narrower spans remain eligible. A later checkpoint with
unchanged events and the current configuration still reuses the exact bundle.
No existing database rows are modified by this change alone.

## TDD and verification

The deterministic public composition test runs canonical proposal validation,
partition preparation, application composition, the real JavaScript contract
validator and renderer, and returned section dependencies. Its HTTP model
boundary returns controlled literal evidence; checkpoint RPCs are a labelled
in-process stand-in. It does not substitute for the native database test.

- Before the span repair: two bilingual repeated-occurrence cases failed with
  offset 0; two unambiguous quote-only controls passed
- Before the configuration-version repair: both bilingual cases incorrectly
  reused the old wrong-span bundle without recomposition
- Independent review reproduced two additional defects: legacy chapter
  carry-forward bypassed cache invalidation, and accepted oversized end offsets
  failed the JavaScript evidence contract. Expanded regressions went red with
  10 failures and 8 passes before the follow-up fixes
- A further independent review found inline replacement could still reuse stale
  chapter evidence. Twelve new bilingual inline/storyline/offset-omission cases
  failed before validating the actual canonical occurrence ranges
- All 38 composition cases now pass, including bilingual exact/quote-only/legacy
  oversized spans, old-cache invalidation, adversarial carry-forward and inline/
  storyline/offset-omission attempts followed by successful bounded repair,
  refusal of persistent invalid reuse, exact current-cache reuse, source language,
  locale and stable event identity
- The affected Python suite passes 220 tests; the composer Node suite passes
  62 tests with no skips
- Python compilation and `git diff --check` pass
- Four new PostgreSQL/private-worker regressions collect but skip in this cloud
  runtime because `initdb`, `pg_ctl` and `psql` are absent. This is an outstanding
  native verification gate, not passing evidence

An initial broader Python run had 184 passes and two fixture setup failures
because the existing test environment lacked `socksio`. The rerun used a
read-only copy of the already installed dependency in task-local test storage;
no proxy settings, shared environment or repository dependency was changed.

Reproduce the cloud checks with the repository's Python test dependencies and
`httpx[socks]` installed:

```sh
python -m pytest -q tests/test_canonical_composer_provenance.py \
  tests/test_integrated_timeline_contracts.py tests/test_memoir_preview.py \
  tests/test_private_drafts.py tests/test_private_draft_broker.py \
  tests/test_preview_jobs.py tests/test_codex_worker.py tests/test_codex_agent.py \
  tests/test_memoir_migration_contract.py
node --test skills/memoir-composer/tests/*.test.mjs
```

Run native regression and affected canonical persistence on the isolated Mac
fixture, never a shared Supabase/PostgreSQL service:

```sh
MEMOIR_TEST_POSTGRES_BACKEND=apple-container python -m pytest -q \
  tests/test_shared_memory_events_postgres.py
```

The new selector is
`test_saved_draft_keeps_canonical_span_after_a_repeated_vetoed_quote`.
It asserts persisted original evidence, validated canonical span/identity, actual
private-worker composition, authenticated saved-preview readback and durable
section references in both source languages, with exact and previously accepted
oversized suffix spans.

## Acceptance disposition

The full historical 56-story matrix remains in
[the landing disposition](landing-issue-disposition-20261005.md#issue-6-56-user-stories).
Its PASS rows are retained prior evidence, not a claim that this patch reran the
entire native/browser/live acceptance workload.

| Scope | Current evidence | Remaining gate |
| --- | --- | --- |
| Stories 19/43: exact original evidence and shared canonical IDs | Bilingual composition regression passes; native readback regression added | Native run and independent exact-head review |
| Stories 26/46: unchanged content and cached recovery | Current-version bundle reuse is byte-exact; old projection caches invalidate; legacy carry-forward is rejected through bounded repair | Existing full native affected suite |
| Stories 1/2/8/9: live every-turn extraction, acknowledgement/veto, stage/date semantics | Existing deterministic validators and source-veto contracts remain covered | Approved live extraction pilot |
| Story 34: meaningful narrative transitions | Structural composition/renderer tests pass | Reviewed live semantic quality |
| Story 36: bilingual behavior | This deterministic English/Chinese provenance path passes | Full bilingual live workload |
| All other stories | Existing integrated acceptance evidence remains applicable; no new behavior claimed | Required review/CI and previously open operational gates |

No provider/model request, shared database write, Langfuse write, deployment,
security change or merge was performed. The issue remains open while the native,
independent review, CI and separate live/human acceptance gates are outstanding.
