# Issue #7: capture evidence and final-snapshot verification

Follow-up to [Issue #4](https://github.com/bohui/copyme2.ai/issues/4) and
[Issue #7](https://github.com/bohui/copyme2.ai/issues/7), based on merged main
`8e61b19b0a223578450684500263e3c7e7a1c010`.

## TDD evidence

No repository `/TDD` skill was available. Behavioral tests were written and run
before each implementation change. Only external HTTP and DNS are faked.

- Capture-field conflicts: 8 failed / 34 deselected, then 42 passed
- Independent metadata and publication provenance: 4 failed / 86 passed, then 90 passed
- Caption-only source basis: 4 failed / 12 passed / 83 deselected, then 99 passed
- Month precision: 6 failed / 2 passed / 99 deselected, then 107 passed

The month regressions prevent contradictory month-only ISO values from being
silently widened to a year. Each independent field is reconciled as an interval;
disjoint intervals reject the photograph, consistent assertions retain their
narrowest intersection, and labeled field evidence remains inspectable.

## Independent review fix loop

The independent review reproduced all initial suite results but found additional
capture-classification and source-isolation defects. Its 18 new public-interface
assertions first failed, then passed after the repair. They cover uncertain and
unknown capture dates, question marks, non-zero-padded conflicting exact dates,
digitization dates, mixed publication/capture clauses, malformed `@graph: null`
and duplicate records with conflicting dates for the same image URL.

Additional red/green cycles broadened these behaviors: 8 failed / 42 passed,
then 157 total public cases passed; 8 unknown-date alias cases failed, then
165 total public cases passed. The pre-final full suite passed 595 with 37
skipped. Exact final clean-head receipts remain in the PR, rather than treating
these earlier runs as final-head verification.

Capture uncertainty is checked in its own clause, and publication, upload,
scanning and digitization clauses remain original provenance. Explicit numeric
precision is normalized or rejected instead of degrading to year precision.
Unsupported named-month or ambiguous numeric formats remain unverified.
Records for the same source image are reconciled together before deduplication.
Malformed graph values cannot erase healthy sibling-source results.

## Complete Issue #4 acceptance matrix

PASS means verified offline behavior plus source inspection, not live-provider
certification. Test names below refer to `tests/test_llm_place_photos.py` or
`tests/test_photo_capture_assertions.py` unless otherwise stated. The final PR records the exact clean commit and suite counts.

| AC | Requirement | Result and evidence |
|---|---|---|
| 1 | Named-place photographs | PASS: `test_skill_discovers_a_source_verified_historical_photo`, album wrong-place exclusion |
| 2 | Requested years constrain discovery | PASS: historical query/window assertions and conflicting-period exclusions |
| 3 | Omitted period is present-day | PASS: `test_omitted_period_finds_recent_photos_without_inheriting_history`, both surfaces |
| 4 | Uncertain capture dates excluded | PASS: `test_all_image_fields_reconcile_exact_capture_dates`, `test_image_metadata_conflicts_or_uncertainty_are_not_verified`, month conflicts and review uncertainty/precision cases, both surfaces |
| 5 | Source links beside references | PASS: original source URLs and labeled source excerpts survive CLI evidence and app results |
| 6 | Real search-call receipts | PASS: malformed/plain prose receipt rejection and native-citation regression |
| 7 | Completed calls and safe returned URLs | PASS: adapter validates completed receipts and safe URLs before fetching; helper URL/DNS/redirect tests cover transport independently |
| 8 | Original source inspection | PASS: real JSON-LD/figure parser and candidate validation; model prose and snippets never date photos |
| 9 | Distinct album images retained | PASS: `test_skill_dates_album_photos_from_each_caption`; undated/wrong-place items excluded |
| 10 | Cross-provider deduplication | PASS: `test_public_app_deduplicates_llm_and_catalogue_images`; canonical variants/hash tests in `test_place_photo_pages.py` |
| 11 | Run-local discovery cache | PASS: repeat-discovery cache hit and one gateway call; scoped successful normalized receipts inspected |
| 12 | Failed/unsupported differs from empty | PASS: source outage and malformed receipt tests; valid search with conflicting images returns successful zero |
| 13 | Catalogue results survive LLM failure | PASS: HTTP400/BadStatusLine and source IncompleteRead preserve catalogue results; unavailable/malformed source preserves sibling source photos |
| 14 | Default off, existing credentials | PASS: opt-in test makes no LLM request; unchanged Compose API/worker settings default to `0` |
| 15 | Bounded requests and budgets | PASS: limit validation and page-budget regression; adapter time/byte/source/tool/token bounds inspected |
| 16 | No auth/raw responses in artifacts | PASS: echoed-key rejection and cache artifact checks; only normalized receipts persisted |
| 17 | Public place/period only | PASS: query construction inspected, historical prompt assertion; no memoir context/subject/period-note is sent |
| 18 | Unresolved rights remain unresolved | PASS: skill/app unknown rights and disabled download/print/publish assertions; unchanged download gates |
| 19 | Documented standalone helper | PASS: `references/llm-web-search.md`; public `init`/`discover` exercised |
| 20 | Shared app capability | PASS: same parser through `search_place_photos`; capture conflicts/consistent metadata/month precision exercised |
| 21 | Public-interface behavior tests | PASS: 165 expanded cases; real adapter, source parsing, candidate validation/reporting/provider orchestration |
| 22 | Linked issue/PR and observed results | PASS only with exact clean-snapshot receipts in the implementation PR; commands below make that verification reproducible |

## Reproduce and interpret verification

Use an isolated Python environment with repository-declared dependencies:

```sh
python -m pip install -e '.[test,evaluation]'
python -m pip install -r skills/place-photo-research/requirements.txt
# Needed by this cloud's configured SOCKS proxy, without changing proxy settings:
python -m pip install 'httpx[socks]>=0.28.1,<1'
git status --porcelain
git rev-parse HEAD
python -m pytest -q tests/test_llm_place_photos.py tests/test_photo_capture_assertions.py
python -m pytest -q tests/test_llm_place_photos.py tests/test_photo_capture_assertions.py tests/test_place_photo_browser.py tests/test_place_photo_pages.py tests/test_photo_progress.py tests/test_photo_worker.py skills/place-photo-research/tests
python -m pytest -q
python -m unittest discover -s skills/place-photo-research/tests -v
(cd skills/place-photo-research && sha256sum -c SHA256SUMS)
git diff --check
git status --porcelain
```

An initial full-suite attempt exposed a missing `socksio` optional dependency
(4 failures, 20 setup errors). Installing the official HTTPX SOCKS extra resolved
all 24; the unchanged proxy configuration was preserved. The subsequent
pre-final full suite passed 520 tests with 37 skipped before the last 17 new
regression cases were added. That earlier run is not the final-head receipt.

The 37 skips are explicit prerequisites: 16 disposable-local-PostgreSQL cases,
17 browser cases requiring a selected local test frontend, and 4 opt-in live
model cases. They are not passes. No database/production services, live gateway,
provider credentials, browser deployment or paid service is used for this work.
Apple Container/Mocker Compose validation and live skill installation are not
available in this Linux cloud and are not claimed. Offline skill validation and
all package checksums are verified separately. A passing offline suite does not
establish live gateway search capability; that prerequisite remains separate and
search remains disabled by default.
