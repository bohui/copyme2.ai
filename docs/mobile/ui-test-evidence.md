# Mobile rendered-screen test evidence

Validated on 2026-10-07 against the implementation worktree. These are deterministic React Native component tests, not simulator/device, browser, or accessibility acceptance tests.

## Runner and result

- Actual screen components and shared UI primitives rendered with React Native Testing Library 13.3.3, React Test Renderer 19.2.3 and React Native 0.86.3's official Jest preset
- 45 tests across five suites pass with the iOS module resolver
- The same 45 tests pass with the Android module resolver
- The keyboard-layout test asserts the selected `Platform.OS` to verify that both resolver paths are exercised
- Dedicated test TypeScript check and ESLint pass
- No snapshots are used as a substitute for behavioral assertions

Reproduce from the repository root:

```sh
npm run test:mobile-ui
MEMOIR_TEST_PLATFORM=android npm run test:mobile-ui
npx tsc --noEmit -p tests/mobile-ui/tsconfig.json
npx eslint tests/mobile-ui
```

The default resolver is iOS. `MEMOIR_TEST_PLATFORM=android` selects Android-specific React Native modules; it does **not** launch Android or run native code on a device.

`jest-expo` was considered but its SDK 57 optional React Server Components peer conflicted with the installed Expo-compatible React version. The official `@react-native/jest-preset` supports these native component fixtures without changing the application's React version or overriding that peer dependency.

## Boundaries

The tests import the production screen files. The production `useResource` hook is exercised for draft/source reads and owner/project changes. Shared `Button`, `Field`, `Check`, `Notice`, `Screen` and native `TextInput`, `Pressable`, `FlatList`, `ScrollView` and `KeyboardAvoidingView` components are rendered through the React Native test runtime.

The following are explicitly replaced with deterministic fixtures:

- Memoir context, authentication service and API responses
- Router calls and source-route parameters
- Safe-area insets and icon rendering
- Recorder/hardware availability and error state, plus the spoken-reply audio hook
- Static image loading through the React Native preset asset transformer

The global fetch boundary throws if a screen accidentally attempts live network access. All memories, owners, source references, emails, session strings and password inputs are fictional test values. No real account, credentials, model call, recording, microphone, photo, backend or payment is used.

## Covered behavior

### Talk and onboarding

- English and Simplified Chinese welcome, consent, writing, send, uncertain and saved labels
- AI-processing disclosure and explicit consent before starting a guest story
- Disabled blank send; labelled multiline composer; text-edit and send callbacks
- No fake guest action when the API is unconfigured
- Explicit synthetic-preview label
- Repeated onboarding submissions blocked while the first attempt is pending
- Recording route reachable through its accessible button
- In-flight reply blocks a new send while retaining the visible composer draft
- Provisional/uncertain reply is never labelled saved; an authoritative committed fixture changes the status
- Retry receives the original outbox operation, and unrelated-project queued work is not presented
- Keyboard-avoiding component properties and handled list taps are configured
- Spoken replies require an explicit Listen press, pass the selected language, and expose Stop for the active reply in both locales
- Spoken-playback unavailability keeps the composer usable; user messages and oversized replies do not expose a Listen action

### Story, draft and references

- My story opens `/draft` directly, without a map or places dependency
- Unauthenticated readers cannot open the draft through that action
- A saved draft and source link are readable in both locales
- Previously saved prose remains visible alongside generation-failure feedback
- Empty draft returns to the conversation
- Paragraph source navigation preserves the exact ID and decimal source version, including values beyond JavaScript's safe integer range
- An unavailable versioned source shows explicit missing-reference text and does not substitute collection content
- A late response from an old owner/project cannot replace the newer owner's displayed draft

### Places request ordering and pagination

- Selecting A then B keeps B's photographs and cursor even if A responds last
- Selecting A, then B, then A again fences the first A request by generation rather than only comparing place names
- New place selection immediately clears the previous photographs and pagination cursor
- A late page from the previous place cannot append to the current gallery, replace its cursor, or prematurely clear its loading state
- Two More presses in the same React batch admit only one request and append its page once
- A superseded request error cannot overwrite the current place's successful gallery with an error notice

The Places request fence also includes account, project and API identity and invalidates requests on unmount. These are injected-response rendering tests; they do not claim real image downloading or image-rights validation.

### Interrupted authentication and recording

- Cancelled OAuth leaves the guest context and unsent draft untouched by screen callbacks
- Repeated/competing OAuth presses are disabled while the first request is pending
- Email and secure-password inputs are labelled; failed password sign-in preserves the entered email
- Successful OAuth without a guest transfer refreshes the account and returns from sign-in
- Explicit Cancel leaves sign-in without clearing a guest draft
- Guest transfer waits for explicit confirmation; duplicate transfer and competing Cancel actions are disabled until completion
- Recorder-unavailable state leaves recording disabled and provides a working Cancel in both locales
- Microphone-denial copy remains visible alongside Cancel

These verify screen interactions with injected state. For example, the cancelled-login tests do not prove real OAuth credential or vault behavior; those need separate auth/domain and device verification.

### Privacy and unavailable capabilities

- AI-processing disclosure, deletion-unavailable notice and notification-unavailable notice are visible in both locales
- No destructive account-delete action is presented
- Export navigates to the source-selection screen
- Commerce shows its explicit unavailable notice without opening checkout
- Account language buttons and guest sign-in entry invoke the intended actions

## Red-to-green findings

The following screen regressions were observed failing in the rendered runner before the production fixes, then passed on rerun:

1. Successful OAuth with no pending guest transfer did not refresh or return to the story
2. Guest-transfer confirmation remained enabled while the transfer promise was pending, allowing repeated submission
3. Guest onboarding remained enabled while the anonymous sign-in promise was pending
4. Independent review of `f580017` reproduced a Places race: an older A response appeared below the newer B heading. The promoted `places.test.tsx` suite observed six failures covering selection, cursor, pagination, loading and error ordering, then all six passed after adding scoped request-generation fencing and synchronous pagination admission

Two additional issues were identified by source inspection and fixed before their first rendered run: competing OAuth buttons were initially enabled while busy, and recording Cancel did not navigate when no recorder controller existed. Their regression tests pass, but no earlier failing rendered run is claimed for those two issues.

## Still required for native acceptance

This evidence does not establish pixel layout, typography, clipping, image quality, OS keyboard behavior, safe-area correctness, real touch target dimensions, VoiceOver/TalkBack order, Dynamic Type/font scaling, contrast acceptance, native navigation history, a real OAuth browser handoff, process-death recovery, physical microphone permissions, audible playback, background/navigation audio cleanup or native media storage/security. Router assertions verify destinations, not a running navigation stack. Spoken-reply tests verify the screen action and labels against an injected audio hook, not hardware playback.

Run the documented device/manual acceptance checks on supported iOS and Android development builds, including large-font layouts in both languages and interrupted/back/dismiss flows. No screenshots were generated by this suite. Separate browser capture was blocked in this environment; it was not bypassed, and browser visual acceptance is not claimed.
