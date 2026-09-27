## Problem Statement

CopyMe2 Memoir has locale values in its domain and speech flows, but the browser experience is still predominantly hard-coded in English. A storyteller or family member cannot choose a Chinese interface, keep that choice after a refresh, or use a different interface language from another family member without changing the meaning of the memoir journey.

This creates a more serious boundary problem than untranslated buttons. The interface and Mira's response language can currently drift apart, while UI language, source language, book-edition language, time zone, and hosting region risk being treated as one setting. Aligning the active conversation with the configured UI locale must not translate or rewrite original memories, change an edition, alter AUD pricing, or move private data between regions.

## Solution

Add reviewed localization to the Next.js Memoir frontend with `next-intl` and Git-managed JSON message catalogues. V1 supports `en-AU` and `zh-CN`, keeps the existing `/memoir/*` and `/voice` URLs unchanged, and uses one component tree for both languages. The active Memoir conversation uses the same resolved locale as the interface, so Mira's opening, follow-up responses, trace labels, read-aloud, transcription, and generated question audio stay aligned with the visible language.

Resolve the UI locale in this order:

1. An explicit device choice.
2. The signed-in account's UI preference when no device choice exists.
3. A locale match from the browser language preference.
4. The application default, `en-AU`.

Store the device choice in the locale cookie. When an authenticated user changes language, persist the same UI preference to that account as well. The resolved UI locale is the active Memoir conversation locale, while source language, edition language, time zone, and hosting region remain independent. Prepared translations are used for product copy; Mira's personalized questions follow the active locale through the runtime language contract, and memoir translation remains a separate language-aware workflow.

## User Stories

1. As a storyteller, I want to choose English or Simplified Chinese for the Memoir interface, so that I can understand controls and guidance comfortably.
2. As a storyteller, I want the default interface to remain English when no preference is available, so that first use is predictable.
3. As a storyteller, I want my explicit language choice to survive a page refresh, so that I do not have to reselect it for every visit.
4. As a signed-in storyteller, I want my UI language preference associated with my account, so that it follows me to another device when no device-specific choice exists.
5. As a family member, I want my interface language choice to be independent from another family member's choice, so that shared memoir access does not force one language on everyone.
6. As a visitor, I want the first interface language to respect my browser language when it matches a supported locale, so that the initial experience is relevant without guessing at personal identity.
7. As a visitor whose browser language is unsupported, I want a safe English fallback, so that the interface is always usable.
8. As a storyteller, I want language changes to keep the current `/memoir/*` URL, so that bookmarks, invitations, and browser history continue to work.
9. As a storyteller, I want the first server-rendered view to use the resolved language, so that I do not see a flash of English before Chinese appears.
10. As a storyteller, I want the same Memoir components and interactions in both languages, so that localization changes words rather than product behavior.
11. As a storyteller recording a memory, I want a language change to wait until the current recording is safely saved, so that changing UI language cannot discard audio or transcript state.
12. As a storyteller, I want Mira's responses, opening message, and voice controls to use the same language as the configured interface, so that the conversation never unexpectedly switches back to English.
13. As a storyteller, I want the original transcript and source wording to remain unchanged when I change the interface language, so that the source of my memoir remains authoritative.
14. As a family member reviewing a book, I want the selected book edition language to remain independent from my current UI language, so that viewing Chinese controls does not switch an English edition.
15. As a customer, I want prices and payment messages localized in wording and number formatting while the currency remains AUD, so that language choice never changes what I am charged.
16. As a storyteller, I want dates and times formatted for my locale while retaining uncertain expressions such as “around 1976”, so that formatting does not invent precision.
17. As a storyteller, I want processing statuses such as transcript processing and book rendering localized, so that I understand progress without exposing internal identifiers.
18. As a storyteller, I want API errors mapped from stable codes to reviewed messages, so that provider details, stack traces, and raw English errors never leak into a localized interface.
19. As a storyteller using voice controls, I want microphone instructions, recorder labels, read-aloud controls, and fallback messages localized, so that accessible capture remains understandable.
20. As a storyteller using the workspace, I want labels for memories, people, the life timeline, family context, photos, public references, and place journeys localized, so that the whole workspace is usable rather than only the landing page.
21. As a storyteller viewing a public reference, I want the interface to continue clearly labeling it as a public reference rather than personal evidence, so that translation does not blur the boundary between a prompt and my life.
22. As a storyteller, I want longer translated labels to wrap or grow without clipping or changing the meaning of actions, so that Chinese text remains usable on small screens.
23. As a storyteller, I want accessibility names, live-region announcements, upload guidance, privacy notices, and consent copy translated, so that assistive technology receives the same language as the visible interface.
24. As a storyteller, I want unknown or missing translations to use a deliberate safe fallback, so that raw message keys never appear in critical flows.
25. As a product maintainer, I want English and Chinese catalogues checked for missing keys, mismatched placeholders, and invalid ICU syntax, so that releases do not silently regress one language.
26. As a reviewer, I want consent, payment, privacy, and Mira's introductory messages marked for human translation review, so that sensitive wording is not accepted solely because it passed an automated check.
27. As a maintainer, I want locale behavior covered through the rendered browser surface, so that tests prove what a storyteller sees and can do rather than coupling to translation module internals.

## Implementation Decisions

- The Next.js App Router is the frontend boundary. The existing product route contract remains unchanged; locale-prefixed routes and subdomains are not introduced for the application workspace.
- `next-intl` is the localization runtime. Messages are stored as reviewed JSON catalogues for `en-AU` and `zh-CN`, organized by stable product namespaces such as common controls, platform navigation, Memoir workspace, Voice, errors, statuses, consent, and payments.
- Locale values are an explicit allowlist. Unsupported cookie, account, or browser values resolve to the default locale and are never used as arbitrary message import paths.
- The locale cookie is request-readable and has a long-lived path-wide lifetime. A server-side request configuration resolves it before the initial render. The language switcher updates the cookie without changing the pathname.
- Browser negotiation uses a locale matcher over the ordered browser language preferences. It does not use substring checks or infer a person's identity, residence, or hosting region from a language tag.
- The language switcher is available from the shared shell and uses translated accessible labels. It offers English and Simplified Chinese by their human-readable names and keeps the current route after applying a choice.
- UI messages use complete ICU messages with named placeholders and plural rules. Translated fragments are not assembled by concatenating separately translated words.
- Date, time, number, and currency formatting uses locale-aware `Intl`/`next-intl` formatting. Currency remains `AUD`; uncertain memoir date expressions remain expressions rather than being converted into fabricated exact dates.
- Backend responses used by the localized UI expose stable error/status codes and safe parameters. The frontend maps known codes to reviewed messages and uses a generic localized fallback for unknown codes.
- UI locale state remains separate from storyteller profile language, source/transcript language, requested edition locale, time zone, and hosting region. It is also the active Memoir conversation locale: each project creation and agent turn carries the allowlisted locale, and the runtime injects an explicit response-language contract into both new and resumed Codex turns. A locale change does not translate source material, consume an interview allowance, alter an approved manuscript, or move storage.
- The language contract is implemented at the conversation boundary rather than by rewriting the model-provider configuration. The provider/model stays stable while the current locale is supplied on every turn, which makes an in-progress conversation safe to continue after a UI-language change.
- The localization boundary remains compatible with the existing API namespace adapter and Supabase session flows. Account preference persistence updates only the authenticated user's UI preference and never mutates shared memoir content.
- Existing browser-only recording, speech, place journey, family context, and timeline behavior remains available through the Next.js client boundary while visible copy is moved behind the shared message interface. A locale change during active recording is deferred until safe persistence is complete.
- Translation catalogues are reviewed in Git. Automated catalogue checks run before screen tests; native-speaker review is required for consent, payment, privacy, and Mira's core introduction.

## Testing Decisions

- Tests verify external behavior at the highest existing seam: a real Playwright browser loading the Next.js frontend against the test API. They assert what a storyteller can see, select, refresh, and preserve, not how message lookup or React components are implemented.
- The primary contract covers choosing Simplified Chinese, seeing translated shell copy, retaining the choice after reload, and preserving the current `/memoir/*` URL.
- The same browser contract checks that interview/source language and story state remain unchanged after a UI-language change, and that an AUD price remains AUD with locale-aware formatting.
- Additional browser scenarios cover browser-language fallback, localized accessibility labels, safe unknown-error handling, and no raw message-key leakage in critical flows.
- Existing browser smoke and full journey tests are prior art: they exercise the rendered shell, direct Memoir routes, reload behavior, voice controls, public references, the Places workspace, and API-backed state through Playwright.
- API contract tests remain focused on stable locale/error/status envelopes and authorization boundaries; they do not replace the browser test for rendered localization.
- Agent contract tests verify that the selected locale reaches the runtime and worker payload, that unsupported locales are rejected, and that the Codex system prompt and safe loop trace use the requested language.
- The retired API-served browser shell is not a supported frontend seam. The Next.js shell owns product routes and the old `/app` static client mount is removed.
- The implementation follows vertical TDD slices: one failing browser behavior, the smallest implementation that makes it pass, then the next behavior. Tests do not mock the localization runtime or internal collaborators.

## Out of Scope

- Locale-prefixed public marketing URLs, public search indexing strategy, subdomains, or a separate URL for every translation variant.
- Adding languages beyond `en-AU` and `zh-CN` in this release.
- Automatically translating the UI with an LLM on page load.
- Translating or rewriting existing original recordings, transcripts, memories, source documents, approved chapters, or book editions as a side effect of changing UI language.
- Building the separate workflow for translating a memoir into a new versioned book edition.
- Adding an independent interview-language selector, changing TTS voice selection, time zone, hosting region, payment currency, entitlement rules, or session allowances as part of UI localization.
- Guessing kinship terms, names, places, or biography from a locale or language preference.

## Further Notes

Chinese copy should be adapted for the experience and reviewed by a native speaker rather than mechanically translated. Public references, place cues, place journeys, and family context must retain their existing evidence and privacy boundaries in every language. The UI catalogues are product copy; personalized Mira conversation follows the active allowlisted locale through a per-turn runtime instruction, while source-linked memoir content remains separate language-aware data.
