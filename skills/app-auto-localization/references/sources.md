# Source ledger

Checked 26 September 2026. Confirm compatibility with the installed repository
version before implementing; these links are not pinned package versions.

## User-provided source

`Pasted text(20260926-094026).txt` — final CopyMe2 localization recommendation.
See `product-baseline.md` for line-level requirements and explicitly added policy.
This is the product basis; online documents only verify integration mechanisms.

## Official/primary technical references

1. OpenAI, **Build skills** — local SKILL.md structure, `.agents/skills` repository
   discovery, explicit `$skill` invocation and optional `agents/openai.yaml`.
   https://developers.openai.com/codex/skills
   This URL redirected to https://learn.chatgpt.com/docs/build-skills when checked.
2. next-intl, **App Router setup** — request configuration, plugin and provider.
   https://next-intl.dev/docs/getting-started/app-router
3. next-intl, **Request configuration** — request-scoped cookies/preferences,
   NextIntlClientProvider and changing locale without locale-based routing.
   https://next-intl.dev/docs/usage/configuration
4. Next.js, **Internationalization** — browser language preferences and negotiation.
   Use its negotiation guidance, NOT its path-prefixed routing example, because
   the user's existing application routes must remain unchanged.
   https://nextjs.org/docs/app/guides/internationalization
5. Next.js, **cookies** — reading cookies, mutation in server functions/handlers,
   and server-dependent effects after Server Action updates.
   https://nextjs.org/docs/app/api-reference/functions/cookies
6. next-intl, **Rendering translations** — ICU messages, interpolation, plural and
   rich-text behaviour. Do not use raw HTML for untrusted translations.
   https://next-intl.dev/docs/usage/translations
7. next-intl, **TypeScript augmentation** — locale and message type support.
   https://next-intl.dev/docs/workflows/typescript
8. FormatJS, **ICU MessageFormat Parser** — AST parsing of ICU messages.
   https://formatjs.github.io/docs/icu-messageformat-parser/
9. franc, **maintainer repository and README** — local language detection,
   francAll ranking interface, ISO 639-3 outputs and small-sample limitations.
   https://github.com/wooorm/franc

## What these references do not establish

They do not verify the user's repository, its completed translations, exact
available app tools, auth schema, detector accuracy, voice-language recognition,
recording safety, deployed UI changes or successful third-party package installation.
The new policy thresholds are implementation defaults, not claims from these docs.
