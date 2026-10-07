# Cloud verification and open acceptance

## Review sequence

The first implementation commit was f5800172c4518451e673b595696d08c1b9758abc. Independent cloud review rejected it for six integration/lifecycle findings. The fix pass adds real provider integration tests (not just mocked-context screen tests), request-generation fences, retryable private-data cleanup and native configuration introspection. No release claim was made from that first commit.

The following fixes are covered by deterministic regressions:

- Logout erases captured owner resources after session revocation, and failures remain retryable without granting a new identity access
- Local project/composer state restores before remote project discovery and cannot be overwritten by a previous owner's delayed responses
- Existing-account sign-in blocks unsent composer, admitted turns and sealed local media; same-owner signup retains that work
- Stop/background/account-change fences awaited native audio setup; route unmount seals a valid active clip while explicit Cancel discards
- Place selection and pagination ignore superseded responses
- Android microphone permission survives plugin composition; foreground-only audio has no background services, iOS arbitrary-loads is disabled, and biometrics are not requested

A second exact-head review of 80344bd found three deeper cases: destructive logout overlooked other-project local drafts; cancelled prepared transfers skipped later preflight/snapshot refresh; and delayed initial discovery could override newer navigation or an admitted turn. The next fix enumerates account-wide local composers, protects sealed media, refreshes the same valid capability before each guest replacement, and fences startup auto-selection by an interaction generation. Local-only drafts remain reachable in the project picker. Expired prepared capabilities stay blocked and retain the guest identity; this conservative recovery policy is tested and does not silently create another capability.

## Repeatable commands

From repository root with installed Node and Python test dependencies:

```sh
npm ci
npm run check:mobile
MEMOIR_TEST_PLATFORM=android npm run test:mobile-ui
MEMOIR_TEST_PLATFORM=android npm run test:mobile-integration
python -m pytest -q
```

`check:mobile` covers portable/runtime/vault/controller tests, both TypeScript projects plus provider-test types, lint, rendered native-screen tests, actual-provider integration fixtures, OpenAPI drift and native config introspection. The Python environment must include the project's test dependencies; a proxy-enabled environment may additionally require httpx's optional SOCKS dependency. This executor used a separate socksio 1.0.0 test-only installation, leaving repository dependencies and proxy routing unchanged.

Before integrating newer main, the full Python regression result was 1,342 passed, 195 skipped and one failure. The sole failing existing test is `tests/test_photo_progress.py::test_first_photos_stream_before_completion_and_shared_search_keeps_cursors_owned`. It also fails on untouched baseline 662f356: it expects an early photo batch without map coordinates, whereas photo fallback policy v8 waits for search completion. This branch does not change that test or policy. Skipped PostgreSQL and browser cases are not passes.

Serial iOS/Android Hermes and web bundle exports pass using one Metro worker; these are JavaScript bundles, not native IPA/APK compilation or device execution. Full cloud browser capture is blocked by the environment's Chromium socket restriction and managed-browser local-URL restriction. Those restrictions were not bypassed.

## Still required before release

- Independent review of the final exact fix head, plus required remote checks
- iPhone and Android native binary builds and real-device encryption, session, linking, recorder/interruptions, offline/key-loss and cross-device acceptance
- Phone visual review, VoiceOver/TalkBack, maximum dynamic text and bilingual human copy review
- Real PostgreSQL/RLS/restart and cost-bounded provider smoke tests using approved staging accounts/data
- Release decisions and durable backend work in the 22-ticket ledger, including resumable uploads, full deletion, store commerce/restore, print fulfilment and operational ownership
- Dependency advisory disposition in dependency-security.md; the dependency audit is not clean

No store publishing, production migration, paid build service, signing credential change, provider smoke charge, deployment or merge to main has been performed.

## Latest-main consolidation

The user subsequently requested all Memoir branches be integrated with latest main for local testing. The mobile branch cleanly integrates `6e907c64a093c0aaf76cbb9dc6380e23c16205df`, including PR23's photo-progress contract correction and PR18's score-replay work. The original reviewed mobile commit `00e60333d82249ebd18e129f59f6a67eb67fb59c` is preserved locally on a dedicated review branch.

On that intermediate integrated source, the full Python suite reported **1,391 passed, 195 skipped, 0 failed**. The previously documented baseline photo-progress failure is resolved by the inherited upstream correction. The mobile aggregate remains green: 80 portable tests, 55 rendered screen/audio tests, 21 provider integration cases, TypeScript, lint, the 36-operation OpenAPI snapshot and native permission introspection. Android resolver variants also pass. Skipped PostgreSQL/browser cases remain unverified, not passing.

No native binary, real-device, live provider, store, paid build, production migration or deployment claim is added by this consolidation. Independent exact-head delta review and remote publication verification still precede any readiness claim.

The next consolidation also integrates `0cbd3bd342eeb1ffd4f0152d98ca56411d89a183`, including PR19 localization safeguards and PR24 canonical span provenance. The merge is clean, with no mobile-source or shared API-contract conflict. That full Python regression passed with **1,434 passed, 217 skipped, 0 failed**. The mobile aggregate and both Android test variants remain green (80 portable, 55 screen/audio and 21 provider tests, plus types, lint, API snapshot and native config). The additional inherited PostgreSQL/browser/HTTP skips require their named environments and are not passes. The source-only compatibility review found no actionable P1/P2 issue; exact-head publication clearance remains separately required.

The final known integration includes PR25 at main `604ecc71cd080e67c6139502c024dec7bdc621a9`. Its 34 canary/runtime paths merge cleanly without altering the mobile implementation or API contracts. The full Python suite now passes with **1,636 passed, 218 skipped, 0 failed**; mobile aggregate checks and both Android test variants also pass. The additional controlled native canary case is skipped because local PostgreSQL prerequisites are unavailable. Independent compatibility review passes 243 targeted worker, Temporal, telemetry, canary guard/auth and mobile API tests. This is source/fixture evidence only: no native device, live canary or provider acceptance is implied.

## Dependency hardening verification

The final dependency review adds a scoped xcode 3.0.1 → UUID 11.1.1 override and two committed security regressions. The UUID test failed against 7.0.3 before the fix. A fresh `npm ci --ignore-scripts --no-audit` reproduces the patched tree, and the aggregate now passes **82 portable tests**, 55 rendered screen/audio tests and 21 provider integration tests, plus TypeScript, lint, the API snapshot and native config introspection. Both Android test variants pass. The backend source is unchanged from the 1,636-pass Python run above. The remaining four advisory roots and source-only integration controls are documented in dependency-security.md; the dependency audit is still non-clean.
