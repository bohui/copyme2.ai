# Provider recovery integration evidence

Verified 2026-10-07 in the Linux cloud executor with Jest 29, the official
`@react-native/jest-preset`, React 19.2.3 and React Native Testing Library.

## Scope and boundaries

`tests/mobile-integration/provider.test.tsx` mounts the real `MemoirProvider`.
It also executes the real `createAuthClient`, `createAuthService`, chunked secure
session adapter, API client and response schemas, `TurnController`, and production
fixture-vault implementation. The context hook and API methods are not mocked.
This suite has a separate config and does **not** load the screen suite's context
mock.

The harness replaces native/runtime and transport boundaries: Expo environment,
fetch, native secure-store driver, linking, locale, crypto, browser-auth cancellation,
media temporary-file cleanup, and Supabase's `AuthPort`. Vault construction selects
the actual in-memory fixture backend instead of SQLCipher. A narrowly scoped vault
spy injects cleanup failure or defers one outbox read. Deferred promises control
response ordering, so race coverage does not depend on arbitrary sleeps. All
identities, credentials, content and public build-config values are synthetic.
Global live fetch fails closed, and unexpected transport routes reject. Synthetic
random values are deterministic but distinct for each request, so accidental
transfer-capability regeneration cannot satisfy the same-token assertion.

This is JavaScript provider-integration evidence. It is not device, Keychain,
SQLCipher, physical-media, OAuth-provider, or live-backend acceptance evidence.

## Verified cases

1. Logout removes the owner view immediately, then erases the captured vault after
   delayed auth logout, even though the turn controller has already been disposed
2. Interrupted local erasure remains retryable; another account cannot sign in
   until cleanup succeeds
3. Saved active-project and composer text restore and remain editable when project
   discovery is offline
4. Build-pinned `EXPO_PUBLIC_SUPABASE_URL` and
   `EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY` restore the synthetic session and local
   composer without fetching `/agent/config`, while the API is offline
5. An unsent guest composer blocks existing-account authentication before transfer
   preparation or identity replacement
6. A late old-owner story response cannot replace the new owner's story state
7. A late old-owner refresh cannot replace the new owner's project list or state
8. A sealed guest recording blocks existing-account transfer and remains locally
   available
9. Same-owner guest signup still succeeds and preserves the composer and media
10. Send admission blocks transfer even before the outbox row exists and after the
    visible composer has been cleared
11. Existing-account login and transfer preparation still succeed once local guest
    work is resolved
12. Local project and composer restore before still-pending project discovery
    resolves, and remain selected after it completes

13. An unsent composer in another project blocks destructive logout
14. An unsent composer in another project blocks guest replacement by an existing
    account, even when the visible composer is empty
15. Cancelling an already-prepared OAuth flow does not bypass local-work preflight
    after the guest writes a new draft
16. A repeated valid preparation keeps the exact capability, sends the fresh
    project/profile snapshot while still authenticated as the guest, and does not
    prepare again after identity replacement
17. Delayed initial project discovery cannot replace a newer explicit project
    selection
18. Delayed initial discovery cannot replace the project of a durably admitted
    turn after its composer has cleared
19. Expired prepared transfers remain blocked without generating a new capability
20. Empty and whitespace-only composers in other projects do not block logout

## Red-to-green result

The initial 12-case suite was run against a temporary archive of production files at
`f5800172c4518451e673b595696d08c1b9758abc`, without replacing the active working tree.
Baseline result: **10 failed, 2 passed**. Both legitimate authentication paths
(same-owner signup and resolved-work transfer) passed. The failing assertions
observed real regressions: cleanup rejection on both attempts, missing local
project/session restoration, unsafe guest switches, and old-owner state/project
replacement. These were behavioral assertion failures, not mock/module setup
failures.

The first fix passed all 12 cases. A second independent review of
`80344bd86565014b55f5120f1c9440246c2068a0` added the cross-project, prepared-transfer,
and startup-discovery races above. The expanded suite reproduced **6 failed,
14 passed (20 total)** both before the fixes and against an isolated archive of
that commit. Failures were the two destructive cross-project paths, skipped
re-preparation after OAuth cancellation, missing fresh same-capability preparation,
and both delayed-discovery races. The prior 12 tests and the expiry/empty-composer
positive guards passed.

Final updated-tree verification: **20 passed, 0 failed**.

Commands run from the repository root:

```sh
npx jest --config apps/mobile/jest.integration.config.cjs --runInBand
npx tsc --noEmit -p tests/mobile-integration/tsconfig.json
npx eslint tests/mobile-integration apps/mobile/jest.integration.config.cjs
npx prettier --check tests/mobile-integration apps/mobile/jest.integration.config.cjs
```

The dedicated TypeScript, ESLint and formatting checks pass. These results are
scoped to this integration suite; the complete mobile aggregate and native/device
acceptance are separate checks.

To repeat the second baseline comparison without modifying the working tree:

```sh
repo="$PWD"
baseline="$(mktemp -d)"
git archive 80344bd86565014b55f5120f1c9440246c2068a0 apps/mobile packages |
  tar -x -C "$baseline"
ln -s "$repo/node_modules" "$baseline/node_modules"
mkdir -p "$baseline/tests"
cp -R tests/mobile-integration "$baseline/tests/"
cp apps/mobile/jest.integration.config.cjs "$baseline/apps/mobile/"
node_modules/.bin/jest \
  --config "$baseline/apps/mobile/jest.integration.config.cjs" --runInBand
```

The parent added one final provider guard for destructive logout with a sealed local recording. Current total:21 provider cases. Both other-project composer tests also assert that the preserved local project is exposed in the picker.
