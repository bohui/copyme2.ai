# Issue #1 acceptance audit — 6 October 2026

## Scope and baseline

Audited [issue #1](https://github.com/bohui/copyme2.ai/issues/1) against main
`291622826cdfb776e946dcd92b65d2fdaf4923ad`. The issue has no follow-up comments.
This is a bounded repair of the existing localization, not a replacement design.
The accepted first-reply onboarding bridge and durable conversation-language
behavior in `docs/memoir-first-reply-locale.md` are preserved.

## Reproduced and repaired

1. A malformed `Accept-Language` item such as `en_US` or `invalid_locale` reached
   the real FormatJS matcher and caused a Next.js HTTP 500. This also discarded
   a valid following preference such as `zh-CN;q=0.9`.
2. Invalid HTTP quality values such as `q=2` could outrank valid preferences.
3. The sensitive-copy manifest covered 10 messages and omitted newer upload
   rights, guest-account transfer, payment status, package and privacy claims.

`apps/web/i18n/config.js` now canonicalizes each language tag independently and
rejects malformed tags, invalid/duplicate quality parameters and zero-quality
choices before calling the existing matcher. Supported choices retain quality
order; a valid explicit device cookie still wins. No dependency, route,
authentication, conversation-language, source, edition or billing change is made.

The manifest now lists 77 existing messages, all still explicitly
`requires-human-review`. No translated wording has been changed, and no native
speaker or other human sign-off is asserted.

## Acceptance trace

“Existing” below means the relevant implementation and tests were inspected; it
is not a claim that every browser scenario was rerun in this audit.

| Issue story | Current evidence and remaining gate |
| --- | --- |
| 1. Select English/Chinese | Existing landing `LanguageSwitcher` and two allowlisted catalogues; existing browser contract |
| 2. English default | Real matcher regression and Next HTTP test pass for absent/unsupported/malformed preferences |
| 3. Refresh persistence | Existing long-lived path-wide cookie and reload browser assertions; browser rerun pending |
| 4. Cross-device account preference | Existing authenticated `auth.updateUser({ui_locale})`; see unresolved account-resolution behavior below |
| 5. Family members independent | Account writes target the current auth user, but account-derived cookies are not viewer-scoped; needs reconciliation/test |
| 6. Browser preference | New real-matcher and Next HTTP cases verify weighted supported choices, including a supported choice after French |
| 7. Unsupported fallback | New cases verify malformed-only and wildcard-only headers render English instead of an exception |
| 8. Preserve URL | Request tests use `/memoir?locale-contract=1`; browser assertions preserve that route and query; existing switch contract pending rerun |
| 9. First server render | New HTTP tests assert `<html lang>` before hydration for browser/cookie resolution; account-only SSR remains unresolved |
| 10. One component tree | Existing Next catch-all route, shared shell and catalogue switching; production build passes |
| 11. Recording safety | Existing bridge refuses a change while a recorder is active and shows `finishRecordingFirst`; it does not queue an automatic deferred switch |
| 12. Interview independence | Accepted bounded first-reply/profile bridge remains unchanged; explicit UI-selector/profile write ambiguity is recorded below |
| 13. Source independence | No source/transcript path changed; existing conversation-language lifecycle and API tests remain in regression suite |
| 14. Edition independence | No edition selection or generation code changed; a rendered edition-switch acceptance assertion was not rerun |
| 15. AUD pricing | Existing `formatAudMinor` uses the UI locale and `currency: 'AUD'`; current payment/package copy is now flagged for review; rendered checkout rerun pending |
| 16. Dates/uncertainty | Existing date formatter and JavaScript uncertain-date tests pass |
| 17. Processing statuses | Existing catalogues include workspace/collection processing states; catalogue consistency passes; browser state sweep pending |
| 18. Safe errors | Existing stable-code/generic error mapping and localization browser unknown-provider case; browser rerun pending |
| 19. Voice controls | Existing translated recorder/read-aloud copy and voice/browser cases; browser rerun pending |
| 20. Workspace labels | Existing shared catalogues cover memories, people, timeline, family, photos, public references and places; full rendered sweep pending |
| 21. Public-reference boundary | Existing reference labels retained; public-context and family-reference messages included in pending human review |
| 22. Longer labels/small screens | Existing responsive CSS and browser workspace tests; narrow-screen visual verification pending |
| 23. Accessibility/consent/privacy | Existing translated labels/live regions; missing sensitive review entries added; keyboard/screen-reader browser validation pending |
| 24. Missing-key fallback | Existing client fallback avoids raw keys; JavaScript fallback test passes; critical-flow browser check pending |
| 25. Catalogue validation | 541 messages pass key/placeholder/ICU validation; real matcher tests replace the previous inaccurate first-token stub |
| 26. Human review | 77 sensitive messages explicitly pending; five manifest regression tests pass; actual bilingual/native-speaker approval remains a release blocker |
| 27. Rendered browser contract | Eight new browser cases added; cloud Chromium cannot launch because Unix sockets are denied; no browser success is claimed |

## Product reconciliation still required

The original issue and later accepted behavior are not identical:

- The original issue asks for a language switcher in the shared shell. The
  accepted implementation report removes it from the active profile menu and
  retains it on the pre-conversation landing page.
- The original issue requires UI/interview separation. The later first-reply
  document makes explicit profile/language-selector actions authoritative.
  `installUiLocaleBridge` currently PATCHes `preferred_language` when a
  persisted UI selection is made for an authenticated project. That behavior is
  preserved pending an explicit decision about the selector's scope.
- `i18n/request.js` resolves cookie/browser locale. Account `ui_locale` is read
  only after client authentication. `syncSupabaseSession` writes that value as
  a fixed device cookie and reloads when there was no cookie. It does not
  provide account-only first-request SSR, distinguish an account-derived
  cookie from a deliberate device choice, or scope that derived choice to the
  current viewer. Cross-account and fresh-device browser evidence is needed
  before stories 4, 5 and the account portion of 9 can be called complete.
- The recorder guard refuses a change instead of queuing it until persistence
  completes. The accepted interface also removes the normal selector during
  an active conversation. Clarify whether the original deferred-switch wording
  still requires a queued transition for the remaining profile action.

These are not silently accepted or reverted by this patch. They require an
agreed current acceptance contract and subsequent focused tests if changes are
wanted.

## Verification

- TDD RED, real Next HTTP boundary: 4 failed / 6 passed before the parser repair.
  Three failures were HTTP 500; the fourth incorrectly selected Chinese for
  `zh-CN;q=2,en-AU;q=0.8`.
- TDD GREEN, same real Next HTTP boundary: 10 passed after the repair; the same
  10 cases also pass against the optimized production build.
- Sensitive manifest RED: all five new cases failed against the old manifest.
- Sensitive manifest GREEN: all five cases pass with 77 pending review keys.
- `node --test tests/js/*.test.mjs`: 114 passed.
- `python3 scripts/check_localization_catalog.py`: 541 messages valid, including
  real ICU parsing and both locale catalogues.
- `npm run build` in `apps/web`: passed on locked Next 16.3.6 dependencies.
- Full Python baseline: 1,068 passed, 191 skipped. Skips include environment-bound
  PostgreSQL and browser scenarios; this is not a full all-environment pass.
- Final full Python regression: 1,073 passed, 201 skipped, one warning. The ten
  added HTTP cases are skipped without `MEMOIR_BROWSER_URL` in that aggregate
  run and were separately executed successfully against both Next builds.
- `git diff --check`: passed.
- Browser launch attempted with system Chromium and again through an approved
  escalation: both blocked at Chromium startup by denied Unix-socket creation.
  The separately attempted Playwright browser download returned an invalid
  archive. No browser assertion ran. The new browser file supports
  `PLAYWRIGHT_CHROMIUM_EXECUTABLE` for a known installed browser.

Run the new HTTP/browser cases against an isolated source frontend by setting
`MEMOIR_BROWSER_URL`; they test the real locale config/matcher. The browser test
stubs only API/auth responses and blocks external HTTPS resources. Existing
localization, first-reply, conversation-language and responsive browser suites
still need a runnable browser environment. No live model call, production data,
production migration, payment or deployment was used.

## Completion status

The bounded parser/review-manifest repair is ready for independent technical
review. Issue #1 as a whole remains open:
browser verification, the explicit product decisions above, and actual sensitive
copy human review are not complete.
