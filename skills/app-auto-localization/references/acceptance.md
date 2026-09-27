# Acceptance and release checklist

The bundle's offline tests verify pure decision rules and helper behaviours.
They do not demonstrate browser behaviour, real detector accuracy, auth correctness,
whole-app translation coverage, full ICU validity or target-app compilation.
Complete the following in the actual repository before claiming those outcomes.

| Case | Required result |
|---|---|
| New visitor, `zh-CN,zh;q=0.9,en;q=0.5` | First HTML and hydrated app use Simplified Chinese |
| New visitor, `en-US,en;q=0.8` | Uses the reviewed Australian English pack |
| `en;q=0`, with supported positive Chinese choice | Excluded English is not selected ahead of Chinese |
| Unsupported first preference, then supported English | Uses next supported preference, not first-token fallback |
| All preferences unsupported, malformed or absent | Product fallback + visible language control; no crash |
| Explicit Traditional Chinese only | Not misrepresented as Simplified Chinese; fallback/choice is explicit |
| Valid explicit device English, account Chinese | Device English wins |
| Account Chinese, browser English, no device choice | Account Chinese wins |
| Refresh/deep-link after manual choice | Same locale, same existing pathname |
| Signup default `en-AU` was never chosen manually | Migration does not falsely lock everyone to English |
| Authenticated manual choice | Cookie + this viewer's account are updated and re-read |
| Automatic inferred change | Does not mutate fixed account preference |
| Automatic explicitly selected | Clears only current viewer's fixed UI preference |
| English-speaking daughter, father speaking Mandarin | Daughter's UI is not changed by interview/ASR |
| Two eligible substantial Simplified Chinese UI-help messages | Optional enabled detector proposes one safe Chinese switch |
| One event delivered twice | Does not count as two consistent signals |
| Short name, 'OK', emoji, number, code, quotation | No inferred switch |
| French/Japanese/mixed-language input | No forced EN/ZH classification |
| Traditional or ambiguous Han-only text | Conservative text adapter abstains |
| Clear request to translate a paragraph | Does not change UI locale |
| Clear supported UI-language command | Existing intent route calls validated preference action |
| Switch while recording or recording is unsaved | Queued; recording/media identity and bytes are preserved |
| Active upload, IME composition, dirty form or payment | Queued until safe; no forced reload |
| Manual choice while automatic request is in flight | Manual choice wins; stale inferred response cannot override |
| Expired pending candidate | Discarded; no delayed surprise switch |
| Write failure or account revision conflict | No false success; safe recovery/re-read |
| Undo after inferred switch | Restores and pins previous UI language |
| Login/logout/account replacement | Session hints reset; no other account's language leaks |
| Two family members sharing a project | Independent UI preferences |
| Same-user multiple tabs, one recording | Idle tab can update; recording tab safely defers |
| Navigation/empty/error/loading states | Translated in both supported locales |
| Form validation/accessibility labels/tooltips | Translated with keyboard/focus preserved |
| Browser/OS permission prompt | App pre-prompt translated; OS limitation not misreported |
| Backend unexpected error | Localized generic fallback, no provider internals |
| UI switch during/after interview | No transcript rewrite, question regeneration or allowance debit |
| UI switch to English while original manuscript is Chinese | Manuscript remains unchanged |
| English UI exports Chinese book edition | Selected edition wins, not operator UI locale |
| Chinese UI shows AUD package | Still AUD, correct amount and purchase policy |
| Approximate year | Approximation retained, no invented January 1 date |
| Photo references current/historical/undated | Correct temporal label in each language |
| Missing message or different ICU parameters | CI reports failure; critical flow does not show raw keys |
| Human review missing for consent/payment wording | Release blocker explicitly recorded |
| Private page cached | No cross-user/cross-locale personalized response reuse |

## Tests to implement in the app

Use the repository's existing unit/integration/browser runner. For browser tests,
set the browser context language or relevant headers, create test viewer accounts,
and inspect both initial server response and hydrated page. Keep a live/mock media
recorder handle stable while switching; assert persisted recording bytes/status,
no duplicate interview consumption, and no unexpected request to regenerate content.
Test rejected/malformed actions and attempted cross-account preference writes.
Use a fixed clock for reducer tests, but request time for production expiry.

Benchmark the real text-language detector with labelled app UI input, not just the
bundle's ranking stubs. Measure false switches and abstentions separately. The
package does not supply a validated accuracy threshold or a representative corpus.
If the detector is not ready, disable input-based mode without removing the
browser/account feature and report that narrower delivered behaviour.

## Release report

Record exact commands, versions, counts, screenshots where available and failures.
Do not equate 54 starter keys with 100% application coverage. Attach a surface/state
inventory with each screen's coverage/review status. Translation review, technical
catalogue validity and actual language-detection accuracy are distinct checks.
