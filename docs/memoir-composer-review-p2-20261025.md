# Composer review: two independent-review repairs

This follows independent review of `d8b370f5b661fcca18d2e169fe70c7eff8d0898f`
on [draft PR #132](https://github.com/bohui/copyme2.ai/pull/132). These are
**offline application/controlled-provider/real disposable PostgreSQL checks**.
There are no new model submissions or live latency results. The original failed
[live comparison](memoir-composer-latency-20261025.md), full transcripts and raw
baseline/candidate receipts are unchanged. Semantic acceptance remains pending.

Tested source commit: `499237b08a0a33311baab99d2dbf4f8c4dafa531`.
The following report/evidence commit changes documentation only.

## Repairs

1. A represented contribution could use an exact matching space as its prose
   witness while omitting the original's location. Python now rejects an excerpt
   whose `str.strip()` is empty. SQL uses the same explicit Unicode whitespace
   set, independent of database locale. Neither check normalizes or rewrites
   stored text. Tests cover 11 whitespace families, including all 29 Python
   whitespace code points, at the canonical composition and real SQL commit/read
   boundaries. A partially represented original may instead be truthfully
   deferred with a reason; its prose remains byte-for-byte unchanged.

   A nonblank matching excerpt still does **not** prove semantic entailment or
   that the whole contribution was expressed. The separate evidence-to-prose
   reviewer and live semantic quality gate remain necessary.

2. An unchanged completed legacy bundle previously generated another draft just
   to obtain a version-2 review. It now seeds the existing durable draft path
   from the **complete saved manuscript**, including when the last model draft
   was only a carry-forward delta. The normal path rebases current host snapshot,
   fingerprint, manuscript/chapter revisions and counters, validates, renders
   and reviews that same writing. Exact blocks, references, event dispositions
   and prior checkpoint values remain intact. A negative review uses the normal
   bounded repair path; a privacy failure retains the saved draft for retry.

   Reuse requires matching current originals (including status/author role),
   source/event manifests, project, policy epoch, content configuration and
   edition preferences. Source/role/policy changes cannot reuse an old ready
   review; withdrawal returns insufficient context without a model call. No
   admission, SQL proof, generation pause or publication fence is bypassed.

## Validation

The reported defects were reproduced before the corresponding product edits.
Red, intermediate and final check receipts are retained under
`var/composer-response-optimization/20261025-review-p2/checks/`; final commands,
source/log hashes and cleanup receipts are in the accompanying
[evidence](memoir-composer-review-p2-20261025.evidence.json).

Final applicable results: **430 Python regressions passed, 11 explicitly
deselected baseline failures; 15 composer evaluation tests, 31 prompt-governance
tests and 62 Node tests passed.** Targeted green checks separately passed all
44 whitespace/partial-deferral cases and all 10 completed-bundle refresh cases.
The same 11 independently confirmed pre-existing workspace/consent/policy cases
remain explicitly deselected; their assertions and earlier failing receipts
are unchanged. Full-suite green is not claimed.

The first broad invocation omitted the configured PostgreSQL backend settings.
It finished with 231 passed and 199 fixture setup errors: native `initdb` could
not allocate a shared-memory segment on this host. Its cleanup is verified and
its failed receipt is retained. The corrected invocation explicitly selects
`MEMOIR_TEST_POSTGRES_BACKEND=apple-container` and
`MEMOIR_TEST_PUBLICATION_TCP=1`; it changes no global database/service settings.
The role-change fixture was corrected from the invalid `family_contributor`
enum to the schema's actual `family` value. The Unicode reader fixture parses
the complete JSON response rather than splitting legal string content at
U+0085/U+2028. Product assertions were not weakened.

All supervised checks have finished and their allocation/process cleanup is
verified. A read-only container inventory found no running disposable
`memoir-issue6-pg-*` fixture containers. The two old unique-content worktrees
remain untouched, and no global shared-memory/service setting was changed.

## Activation and remaining permission boundaries

These two repairs add no managed prompt edits, review-version bump, receipt
changes, table or column changes. The two **already unpublished** version-2
prompt edits remain:

| Managed prompt | Source | Existing pin |
| --- | --- | --- |
| `memoir/skills/memoir-composer/review` | `skills/memoir-composer/prompts/review.md` | v3 |
| `memoir/skills/memoir-composer/shared/editorial-review` | `skills/memoir-composer/references/editorial-review.prompt.md` | v1 |

[AGENTS.md](../AGENTS.md) requires: “Review prompt Markdown in Git and merge it
to `main` before publishing. Do not create Langfuse versions from feature
branches.” The publisher also requires clean local main matching live
origin/main. No supported live unpublished-source staging bypass was found;
offline source replay remains the supported preview. This branch's existing
receipts intentionally do not certify its edited prompt content.

The safe sequence is:

1. Independently review this exact offline head and resolve any findings. Keep
   the combined PR draft and the failed live evidence pinned.
2. Separately authorize and review a **prompt-only main publication** from a
   nonserving checkout; obtain genuine generated receipts and verify pins. Do
   not merge the combined code/SQL PR merely to make testing possible.
3. Use those genuine pins with the reviewed code in an isolated candidate and a
   fresh disposable database. The existing test authorization covers loading
   the single fresh-install baseline there. Before any existing serving database
   is changed, separately approve the coordinated API/worker/pin/function upgrade.
4. Authorize the renewed live budget/deadline, then rerun the same six frozen
   bilingual checkpoints, saved-draft restart and withdrawal/empty controls.
   Review successful durable output and actual source meaning. No additional
   baseline calls are permitted; censored Chinese-15 stays censored.

An existing database would need the reviewed `memoir_review_ready(jsonb)` and
`memoir_review_covers(jsonb,jsonb)` helpers and replacement bodies for
`commit_lifetime_memoir_lane_page_before_rework(uuid,uuid,bigint,jsonb,text)` and
`commit_lifetime_memoir_lane_page_before_summary_windows(uuid,uuid,bigint,jsonb,text)`.
Only the fresh-install baseline was edited here. No existing database was
migrated. Old readers retain their response shape; old writers or mismatched
workers fail closed against version-2 gates. Existing ready roots are not
retroactively certified. Preserve checkpoints/queued work and pause composition
if activation fails; a rollback that weakens the gate would restore the known
quality defect and needs an explicit decision.

Accounting remains **baseline 24/24, candidate 14/24, zero paid judges**. All ten
unused candidate submissions remain unused. The prior proposal is still
**unapproved**: 16 future submissions (12 nominal draft/review calls plus four
repair calls), requiring six beyond the original ten and a renewed 30-minute
deadline, for cumulative candidate cap 30. No prompt publication, merge,
deployment, production operation or renewed live call happened in this repair.
