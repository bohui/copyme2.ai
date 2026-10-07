# Memoir for iOS and Android

Native Expo/React Native client using the existing Memoir FastAPI/Supabase backend. Implementation/beta work, **not release-approved**. See [acceptance ledger](../../docs/mobile/implementation-plan.md) and [backend readiness](../../docs/mobile/backend-readiness.md).

## Install and check

From repository root (Node22.13+):

```sh
npm ci
npm run check:mobile
npm run test:mobile-ui
```

The web app keeps its independent `apps/web/package.json` and lockfile. Do not run a root dependency upgrade to update web.

## Development builds

Copy `.env.example` to `.env.local` and configure `EXPO_PUBLIC_MEMOIR_API_URL` to the **same HTTPS backend used by the website**, ending `/api/v1/memoir`. It must include the additive recovery/source/photo routes from this branch. Supabase URL and public key are discovered from `/agent/config`, or can be pinned using `EXPO_PUBLIC_SUPABASE_URL` and `EXPO_PUBLIC_SUPABASE_PUBLISHABLE_KEY` from that same backend. Pin both for offline startup of an already saved session; otherwise cold startup requires the configuration endpoint. An expired session can still require an online refresh. Once an authenticated local vault is open, local project/composer recovery never depends on the remote project index. Never configure a service-role secret in the app.

```sh
cd apps/mobile
npx expo prebuild
npm run android
# macOS + approved Xcode/signing setup only:
npm run ios
```

SQLCipher/SecureStore require a development build. Expo Go is deliberately unsupported for private persistence. Native imports fail closed if encryption is not available. OAuth requires the deployment's approved redirect allowlist for `memoir://auth/callback` and configured providers; this work does not change account/OAuth permissions. Verified universal links and production app identifiers remain release gates.

## Synthetic phone UI preview

```sh
cd apps/mobile
EXPO_PUBLIC_MEMOIR_FIXTURE=1 npm run web
```

The persistent banner identifies fictional data. No auth, model or backend request is made in this preview; it is not live acceptance. Fixture persistence is in-memory and cannot replace native encrypted-storage tests. Fixture mode is disabled in production native builds.

## Cloud-safe bundle verification

```sh
cd apps/mobile
npx expo export --platform ios --max-workers 1 --output-dir dist/ios
npx expo export --platform android --max-workers 1 --output-dir dist/android
npx expo export --platform web --max-workers 1 --output-dir dist/web
```

These create JavaScript/Hermes bundles. They do not compile a native IPA/APK, exercise a microphone, prove App Links, or establish store readiness. Native binary and physical-device checks are mandatory separately.

## Real acceptance gates

Use two test accounts and synthetic memories in an approved staging environment. Verify web→iPhone→Android history, interrupted anonymous upgrade/existing-account transfer, byte-split/EOF/receipt retry, revoked source suppression, encrypted process restart, denied mic/photo access, foreground audio interruption, source revisions, collection CAS, EN/ZH large text, VoiceOver/TalkBack and supported-device keyboard layouts. Provider smoke calls need their existing authorization/budget and must be labeled separately from fixture checks.

No migrations, production deploy, model smoke calls, paid EAS builds, store publication or signing/account changes are run by setup. Never merge or distribute before the outstanding ticket gates, required checks and independent exact-head review pass.
