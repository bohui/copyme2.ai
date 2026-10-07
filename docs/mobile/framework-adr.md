# ADR: Native Memoir with a shared backend

React Native with Expo development builds and Expo Router. This is a native component app, not a web DOM/WebView wrapper. The existing FastAPI and Supabase service remain authoritative. No mobile-only backend database, model workflow or entitlement store is introduced.

Pinned support matrix checked 7 October 2026: Expo SDK57 (57.0.27), React Native 0.86.3 from Expo's bundledNativeModules.json, React 19.2.3. SQLCipher needs prebuild/development build, not Expo Go. The native app remains separate from the web package's React dependency tree.

Official sources:

- https://docs.expo.dev/versions/v57.0.0/ (SDK57, RN0.86, React19.2.3, Android7+, iOS16.4+, Xcode26.4+)
- https://docs.expo.dev/versions/latest/sdk/sqlite/ (SQLCipher and development-build requirement)
- https://docs.expo.dev/versions/latest/sdk/securestore/ (keychain lifecycle and backup limitations)
- https://docs.expo.dev/versions/v57.0.0/sdk/expo/ (expo/fetch streaming)

The toolchain floor and intended older-storyteller audience need owner acceptance before release. iOS16.4 excludes older devices; no iOS build has been run in Linux. Android and iPhone real-device NDJSON, background/keyboard/audio and auth flows must pass separately.
