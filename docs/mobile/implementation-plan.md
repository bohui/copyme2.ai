# Memoir native implementation ledger

## Frozen source

- Base: `662f3563824e8c6d0a7ef5a41fa84c1e07886c7c`
- Tree: `4b2f054efe00283bd69e49c22fce3040ffa03c38`
- Branch: `glace/memoir-native-mobile`
- Main is not continuously rebased during this implementation
- No existing web UI or photo research policy is replaced

## Phone-first adaptation

Retain the web's paper (#f7f2e9), dark ink (#25302d), green (#315f55), portrait assets and calm storytelling language. Four native tabs: Talk, My story, Library, Account. One primary action per screen, 50-point controls, scalable native text, screen-reader labels, safe areas, keyboard avoidance, private draft as a full screen independent of map state. English and Simplified Chinese have matched catalog keys. Source and rights remain distinct from testimony.

The original web welcome/conversation fixture could not be visually captured in this cloud environment: Chromium process singleton socket was denied (EPERM); the supported managed cloud browser rejected the local fixture URL (ERR_BLOCKED_BY_CLIENT). These restrictions were not bypassed. Source inspection is design grounding, not a completed visual audit. Cloud UI screenshots, native accessibility and phone visual QA remain unverified.

## Ticket disposition

| Ticket  | Implemented scope                                           | Remaining acceptance gate                                     |
| ------- | ----------------------------------------------------------- | ------------------------------------------------------------- |
| MOB-001 | Canonical backend readiness register                        | Live two-account/RLS and restart checks                       |
| MOB-002 | Expo SDK57 development-build project, native adapters       | iPhone/Android hardware and native binary proof               |
| MOB-003 | Commerce and launch boundaries recorded                     | Product/market/privacy/release owner decisions                |
| MOB-010 | Typed runtime contracts, NDJSON, portable domain and i18n   | Web adoption remains incremental; generated OpenAPI drift job |
| MOB-011 | Existing durable project index/history exposed              | Empty-project metadata/editorial mutation migration           |
| MOB-012 | Secure sessions, guest prepare/attach, PKCE browser adapter | Native configured OAuth/Apple and cancellation proof          |
| MOB-013 | SQLCipher vault, immutable outbox, account isolation        | Physical kill/key-loss/backup and policy-epoch invalidation   |
| MOB-020 | Native Talk, streaming and explicit receipt retry           | Full server payload-hash/generation-admission guarantee       |
| MOB-021 | Foreground record/review/transcribe, sealed original        | Kill during active unsealed recording, device interruptions   |
| MOB-022 | Bounded media adapter                                       | Binary resumable upload/finalize service                      |
| MOB-023 | Native labels, large targets, two catalogs                  | VoiceOver/TalkBack/max-scale and human bilingual sign-off     |
| MOB-030 | Place list and canonical historical photo endpoint          | Source-backed native visual/fallback/pagination QA            |
| MOB-031 | People list and timeline correction CAS                     | Portrait mutations and device conflict review                 |
| MOB-032 | Independent draft reader, all seven collection stages       | Real shared-worker 5/10/15/20 milestone acceptance            |
| MOB-033 | Read-only draft/source view                                 | Durable protected manuscript editing and artefact delivery    |
| MOB-040 | Existing server entitlement consumption                     | Store products/receipt/restore integration and approvals      |
| MOB-041 | No print order mutation                                     | Approved supplier/quote/proof/payment implementation          |
| MOB-042 | Privacy/AI disclosure and explicit deletion blocker         | Complete server erasure/reporting/export lifecycle            |
| MOB-043 | No notification prompt, core does not require push          | Approved token registration and provider integration          |
| MOB-050 | Deterministic transport/API/vault failure harness           | Native/web/live-provider cross-device matrix                  |
| MOB-051 | Development configuration and release gates                 | Signing, privacy filings, support/ops, store review           |
| MOB-052 | No distribution or deployment                               | All gates, invited beta and rollout approval                  |

The app is an implementation branch, not a release-ready store submission. A capability's route or fixture is not live acceptance. No paid EAS build, provider call, production migration, deployment, signing key, app-store publishing or merge is performed by this work.
