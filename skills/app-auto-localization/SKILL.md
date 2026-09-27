---
name: app-auto-localization
description: Implement or audit automatic end-user UI localization in the CopyMe2 Next.js app. Use for detecting a visitor's language, switching the whole interface, next-intl integration, or fixing incomplete localization. Keep interview, source and book languages independent. Not for merely changing the coding assistant's response language or translating a memoir.
---

# App auto-localization

Implement this capability in the current repository using ordinary Codex file,
patch, shell and test tools. Do not stop at an architecture proposal when asked to
implement. Do not assume custom app tools, a backend API, an auth table, or an MCP
server exist: discover actual code and wire it. Installing this skill alone does
not alter a deployed app. Codex installs normal runtime code; production requests
do not invoke a coding agent or an LLM to translate interface strings.

## Read first

Read `references/product-baseline.md`, then `references/detection-policy.md`.
Read `references/integration.md` before editing and `references/acceptance.md`
before declaring completion. The baseline comes from the user's attached final
localization recommendation. The input detector, hysteresis and deferred-switch
state machine are additions, not claims made by that original document.

## Invariants

- Use `next-intl`, reviewed JSON catalogues, initial locales `en-AU` and `zh-CN`.
- Preserve one app, one component tree, `/memoir/*` and `/voice`. Do not add
  `[locale]`, language subdomains, or a second app as part of this task.
- Resolve **explicit device choice > saved account choice > browser > default**.
  The optional new automatic session signal sits between account and browser.
  Never promote an inferred locale to a permanent explicit preference.
- Never infer UI preference from country, IP, ethnicity, name, memoir setting,
  another family member, pasted sources, a photograph caption, or interview text.
- UI locale is independent of conversation locale, source languages, edition
  locale, timezone, processing region and currency. Do not modify those fields.
- Prepared catalogues localize application-owned UI. Never live-translate the
  interface on page load, rewrite original transcripts, or retranslate a book.
- Keep an always-visible `English / 简体中文 / Automatic` control. Explicit user
  changes override inference. Unsupported languages do not become invented packs.
- Apply every locale switch only at a safe boundary. Preserve recorder identity,
  unsaved work, focus, route, query string, session allowance and payment state.
- The skill author's prompt language is not an end user's preference.

## Execute

### 1. Discover, don't guess

Inspect `AGENTS.md`, `git status --short`, package manifests, lockfiles, source
layout, Next.js/React/next-intl versions, current locale code, authentication,
profile persistence, recording state and existing tests. Honour the repository's
package manager and approvals; do not upgrade the whole framework.

Resolve this skill's own directory as `SKILL_DIR` from its installed path. Run:

```bash
python3 "$SKILL_DIR/scripts/inventory.py" .
```

This is a bounded heuristic inventory, not proof that all UI strings were found.
Do not read `.env`, production data, private recordings or unrelated repositories.
Identify actual app-owned surfaces including auth, navigation, dialogs, toasts,
errors, access labels, dates, status labels, emails and account settings. Do not
invent routes or product screens just to match the bundled sample catalogue.

If asked to audit only, make no source edits. Otherwise implement the bounded
change in the existing app, leaving unrelated user changes untouched.

### 2. Install the deterministic runtime

Adapt `assets/runtime/locale-policy.ts` into the app. It is executable reference
code, not a complete framework integration. Add the browser-language parser from
`assets/runtime/browser-languages.ts` after installing/reusing `negotiator` and
its types. Validate actual HTTP quality-order behaviour in the target app.

Read cookies, authenticated viewer preference and `Accept-Language` on the server.
Use explicit message loaders, not untrusted input in import paths. Configure
`getRequestConfig`, `NextIntlClientProvider` and root `html lang/dir` so the initial
server render has the same locale as hydration. Keep timezone explicit and
independent. Merge the next-intl plugin into existing Next configuration.

Add real account persistence using the existing authenticated profile path. Keep
fixed device preference, fixed account preference and automatic session hint
separate. Migrate legacy defaults carefully: a database default of English is
not evidence that someone deliberately chose English. If no auth exists, implement
anonymous behaviour and report account persistence as not applicable; do not add
fake adapters. Never claim cross-device persistence without a working write/read.

### 3. Add safe automatic input detection

Browser detection works immediately without text classification. Add optional
local text identification only on established current-viewer UI-help/onboarding
surfaces, **not interview answers or general memoir content**.

Use `assets/runtime/text-signal.ts` with the real `francAll` export from `franc`
when this path is enabled. Run the ranker over its full language set; do not force
an unsupported language to win English/Chinese by restricting its candidate set.
The bundled policy uses two consistent final input events, a five-minute evidence
window and at most one inferred switch per viewer UI session. These thresholds
are starting product settings, not calibrated confidence guarantees.

The real detector must be tested on suitable English, Simplified Chinese,
Traditional Chinese, Japanese, mixed, short, quoted and code samples. The bundled
offline ranker tests use stubs and do not establish detector accuracy. If the real
detector is unavailable or insufficiently reliable, leave this optional path off,
ship browser/account detection, and state exactly what is disabled.

Route eligible observations through the reducer. Derive actor, origin, revision,
finality and busy state in trusted application code. Do not trust client-provided
or model-provided identity claims. Keep only bounded language-event metadata;
do not create a new raw-message analytics log.

### 4. Implement the actual switch

Create/reuse a validated Server Action or authenticated route handler. Manual
choices set the fixed cookie and the current viewer's account preference. Auto
clears that viewer's fixed preference deliberately. Inferred changes affect only
the viewer's current automatic session and do not update a fixed account setting.

Re-check the current preference/revision before applying. Wait for recordings,
uploads, text composition, dirty forms and payments to finish safely. Do not use
`window.location.reload()`, locale-keyed app/recorder remounts, or navigation to
`/en/...`. Call `commitAutomaticSwitch` only after persistence succeeds. Cancel
obsolete queued switches after a manual change, account change or logout.

Show the localized change notice with Undo. Undo restores the previous locale and
pins it so the same detector cannot immediately switch it back. For multiple tabs,
notify only the same authenticated viewer and defer each busy tab independently.

### 5. Localize the whole app-owned interface

Extract full messages with ICU placeholders into namespaces. The bundled 54-key
catalogues are **draft starter strings**, not all existing CopyMe2 UI and not
human-reviewed copy. Preserve actual existing keys/content where appropriate.
Draft missing English/Chinese translations; flag consent, privacy, pricing,
payment and core Mira introductory wording for human review.

Cover navigation, empty/loading/error/success states, buttons, modals, tooltips,
form validation, aria labels, microphone guidance, family-tree/timeline labels,
notifications, generated system emails, dates/numbers, page titles and relevant
third-party widget locale parameters. Keep source text, user-entered names,
original photo captions and memoir editions separate. Historical/current/undated
photo labels must retain their temporal meaning in both languages.

Map backend status/error codes to translated text with an allowlist and safe
fallback. Do not show raw provider errors. Keep money in its actual currency.
Do not fabricate day/month precision for approximate memoir dates. Do not infer
specific kinship from an ambiguous label.

### 6. Validate, then report measured coverage

Run the bundle self-tests where Node, Python and TypeScript are available:

```bash
bash "$SKILL_DIR/scripts/self_test.sh"
```

Run the target repo's typecheck, tests, lint and build as applicable. Run both
catalogue validators on actual app files; the ICU validator requires the parser
in the target project and fails closed when it is missing:

```bash
python3 "$SKILL_DIR/scripts/check_catalogs.py" PATH/en-AU.json PATH/zh-CN.json
node "$SKILL_DIR/scripts/check_icu.mjs" APP_ROOT PATH/en-AU.json PATH/zh-CN.json
```

Use actual browser tests for first render, saved preference, language switching,
multiple users, recording preservation, errors and cross-tab behaviour. Check
all touched screen states in both languages; inspect responsive layouts and
keyboard/screen-reader labels. Static scans cannot prove whole-app completion.
Do not mark an unrun build, detector benchmark or browser test as passed.

Deliver code changes plus `docs/localization/implementation-report.md` (adapt to
repo conventions) covering changed paths, dependency changes, locale resolution,
auth persistence, migrated surfaces, untranslated/externally controlled surfaces,
human-review blockers, actual test commands/results and remaining limitations.
No automatic commit, push, deployment or production database migration.
