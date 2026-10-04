# Memoir UI audit and regression receipt

Date: 2026-10-03 UTC  
Scope: isolated synthetic Memoir projects only; no customer conversation or production database was used.

## Tested paths

The browser checks used the existing local web bundle on `localhost:3010` and a
source-aligned isolated host API/web pair on `127.0.0.1:8011`/`127.0.0.1:3011`.
The test data was synthetic and disposable. Desktop checks used a wide viewport;
mobile checks used a narrow viewport. Evidence is retained under
`var/memoir-five-case-evaluation/ui-audit-20261003/`.

Observed passes:

- desktop header, conversation history, fixed composer, send/response rendering,
  loading state, and retryable error surface;
- mobile layout, fixed composer, voice-input and voice-conversation controls,
  and responsive workspace cards;
- manual scrollback in the nested `#chat-scroll` history followed by continued
  conversation without losing the scroll container;
- reload persistence for a synthetic project and workspace state;
- page-locale switching independently from saved conversation language;
- synthetic map/place journey, photo references, and timeline workspace visibility.

Screenshots:

- [desktop conversation](../var/memoir-five-case-evaluation/ui-audit-20261003/04-desktop-response.png)
- [mobile conversation](../var/memoir-five-case-evaluation/ui-audit-20261003/05-mobile-chat.png)
- [mobile manual scroll](../var/memoir-five-case-evaluation/ui-audit-20261003/11-mobile-manual-scroll-bottom.png)
- [locale and workspace](../var/memoir-five-case-evaluation/ui-audit-20261003/08-locale-zh-response-workspace.png)
- [policy retry after patch](../var/memoir-five-case-evaluation/ui-audit-20261003/12-policy-retry-patched.png)

## Bug found and fixed

An isolated browser journey intentionally changed the project policy epoch
between the initial answer request and the normal agent turn. The old client
surfaced the `POLICY_EPOCH_CONFLICT` instead of resuming the session and
retrying the same answer. The API now resynchronizes a stale session epoch on
`resume_session`; the client catches that one bounded conflict, resumes once,
and retries the original answer options. Other errors still propagate.

The patched source path produced one intentional first `409`, one `resume`
`200`, one retried `answers` `200`, and a completed agent turn. The browser
receipt shows the user turn and assistant reply. The regression is covered by
`test_policy_epoch_can_be_resynced_before_a_session_answer` in
`tests/test_spec_invariants.py`.

## Limits and remaining UI risks

- The dedicated `memory-spark-web-1` container on port 3010 is an old image
  without a source mount. It was not restarted or rebuilt because that would
  touch a shared service. The source-aligned check therefore used the isolated
  host pair; rollout still requires an explicitly authorized normal web deploy.
- Browser microphone permission and an actual microphone stream were not
  exercised. Voice controls were verified as visible and labeled only.
- Family-tree, private-draft, and full-book composition panels were not claimed
  as UI passes where the synthetic account lacked the relevant entitlement or
  composition stage. The E2E worker traces cover their service-side contracts.
- The expected invalid synthetic placeholder route `404` and the deliberately
  injected first policy-conflict `409` remain in console logs; neither is a
  residual retry failure.

