# Offline semantic fixture review

All events here are invented fixtures, not historical claims. This evaluates the
meaning of fixed visible outputs and controlled collector selections, not a live
model or whether a person actually recalls something. No paid judge is used.

The initial rollout permits two reviewed neutral invitation/bridge pairs. The
English pair asks whether a clue brings any memory of that time to mind, with an
explicit option to skip. The Simplified Chinese pair asks the same and explicitly
accepts not remembering. Public assertions appear in a separately cited card,
with the event year distinct from publication metadata and original source names.
Broader natural variants require additional semantic review before eligibility.

## Positive scenarios (both languages)

| Fixture | Relevance | Memory invitation | Non-leading | Fit | Provenance/sensitivity |
|---|---|---|---|---|---|
| Active park visit with father | Pass: continues accepted visit | Pass: invites own detail | Pass: no added attendance claim | Pass: ordinary question wins | Pass: ready public cue remains deferred |
| More relevant narrator question | Pass: accepted memory wins | Pass: one open question | Pass: no invented detail | Pass: ordinary pool retained | Pass: no external claim presented |
| Natural pause, ready civic fixture | Pass: accepted period/place | Pass: optional recollection | Pass: no residence/awareness/emotion assumption | Pass: short bridge, one question | Pass: inspected source card, ordinary topic |
| Birthplace only | Pass: tentative relevance remains private | Pass: uncertainty allowed | Pass: no claim of later residence | Pass: optional invitation | Pass: public date remains separate |
| No useful news | Pass: narrator question remains | Pass: own memory requested | Pass: no invented historical claim | Pass: no interruption | Pass: no citation is fabricated |

Confirmed moves, duplicates and rejected clues are exclusion fixtures: obsolete
birthplace candidates and duplicate identities cannot become a new selected cue.
They do not receive a positive semantic score merely for plausible wording.

## Negative scenarios (both languages)

- “How did you feel when you witnessed…” / “亲眼见到…是什么感受”:
  fail non-leading (attendance and emotion presupposed); automatically rejected.
- “When you lived in Boston in 1970…” / “1970年住在波士顿时…”:
  fail non-leading and provenance (unsupported residence); rejected.
- “Do you remember celebrating at the fair?”:
  fail non-leading (specific participation supplied by the interviewer); rejected.
- Missing or fabricated source/date, publication date used as event date:
  fail provenance regardless of fluent wording; rejected before selection.
- Sensitive unsolicited category or stale/rejected/cross-project clue:
  fail relevance/provenance; excluded regardless of prominence.

Observable test coverage is in `test_historical_news.py`, provider tests, native
PostgreSQL tests and the browser/module controls smoke. Actual live-model ranking
and human memory-recall usefulness remain unmeasured product-evaluation outcomes.

The early acknowledgement is also part of the reviewed response. When historical
clues are ready, only the two neutral pace-setting acknowledgements are allowed;
the streaming adapter suppresses an unsupported autobiographical acknowledgement
before it becomes visible. Source cards additionally reject obvious English or
Chinese trauma/violence/political language even when the provider incorrectly
labels the event as civic. This conservative denylist complements the provider
contract; it is not a comprehensive semantic classifier or proof of live quality.
