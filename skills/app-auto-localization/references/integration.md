# Implementing this in the actual repository

This is a Codex coding recipe, not evidence that the target app has been modified.
Use actual discovered paths and APIs. No fictional profile adapter or mutation
handler may be left as working-looking code in the completed app.

## 1. Inventory and versions

Inspect repository instructions and current diffs before patching. Locate the
actual web package; `apps/web` is a prior proposal, not a confirmed path. Inspect
package manager, lockfile, installed framework version and tests. Reuse existing
next-intl infrastructure instead of creating parallel providers or catalogues.
Check current official docs against the installed version. Do not rename a
middleware file or add locale routing merely because a newer example does so.

Core dependency: `next-intl`. The reference browser adapter uses `negotiator` and
`@types/negotiator`. The optional input adapter uses `franc`. Full catalogue CI uses
`@formatjs/icu-messageformat-parser`. Install through the repo's package manager,
record resolved versions in its lockfile, and retain normal approval/network
restrictions. Browser-based auto localization needs no translation SaaS or LLM.

## 2. Request-scoped resolution

Use `getRequestConfig` with async `cookies()`/`headers()` as appropriate for the
installed Next version. Authenticate once per request through the existing auth
layer. Read the viewer's preference, not the project owner's preference. Resolve
with `resolveUiLocale`. Check provenance, expiry and viewer binding of any automatic
session hint before passing it into the pure function.

Load messages using an explicit map:

```ts
const messageLoaders = {
  'en-AU': () => import('../../messages/en-AU.json'),
  'zh-CN': () => import('../../messages/zh-CN.json')
};
```

Adapt relative paths to the real repo. Arbitrary cookie text must never become
an import path. Set locale, messages and an independently resolved timezone in
request configuration. Keep personalized HTML/RSC out of shared caches keyed only
by path. Use request-scoped memoization, not global mutable locale variables.
`Vary: Accept-Language` alone does not protect account/cookie-private content.

Merge the next-intl plugin into the existing Next config without discarding
images, headers, security, bundler, deployment or other plugin settings. Preserve
existing root auth/theme/error providers when adding `NextIntlClientProvider`.
Render `<html lang={locale} dir="ltr">` for the initial two languages; do not
claim RTL support without actual RTL catalogues/layout work. First server render
and hydration must agree; do not use an English-first client-only locale effect.

## 3. Preference writes and actor isolation

The source cookie name is `copyme2_ui_locale`. Reserve it for fixed device choice.
Use a separate viewer-bound session hint or `copyme2_ui_auto` for automatic data;
validate/expire it through the existing session mechanism. Do not use a browser
cookie as authorization to update arbitrary accounts. Mark preference cookies
HttpOnly, SameSite=Lax, Path=/ and Secure in production; scope correctly per host.
Do not broaden cookie domain across unrelated products.

Use a Server Action or the repo's authenticated mutation route. Validate supported
locale and intent. Derive current user ID on the server. Preserve same-origin/CSRF
controls, request size limits, auth and rate limits. Use expected preference
revision/idempotency where appropriate. Manual authenticated changes update the
account and fixed cookie; inference does not update fixed account preferences.
Do not write cookies during Server Component rendering.

A DB update and browser cookie delivery are not one atomic transaction. Handle
partial failures explicitly, make retries idempotent, return actual persistence
status and do not claim success before the action acknowledges it. Refresh/re-read
actual account preference when resolving a conflict. Use safe translated errors.

When Auto is selected, deliberately clear fixed device choice and set only this
account's mode to automatic. The auto action is a user choice, not an inference.
On logout/account change, clear account-derived cookies and inferred hints, reset
client state and ignore stale in-flight locale events. On login without an explicit
device preference, initialise from the account. A project's owner changing UI
language must not affect other family members' accounts or their active sessions.

If there is no auth/profile layer, implement and report anonymous browser/cookie
behaviour. Do not fabricate persistence. Generate migrations only when needed,
review them and test locally; never apply a production migration by default.

## 4. Switch coordinator and recording safety

Wire the app's real recorder/upload/form/payment state to `BusyState`. Do not
hard-code IDLE in the recording screen to make a sample work. Manage the language
coordinator above route panels, but preserve the existing recorder/media service
identity. Stable component keys; no `key={locale}` around the app or recorder.
IME composition counts as busy; locale changes should not steal input focus.

A reducer apply result requests a mutation. Re-check preference revision and
current user before persisting. Commit only after successful acknowledgement.
If persistence fails, remain on the original locale and allow retry. If a manual
choice occurs while an inferred request is outstanding, the manual choice wins.
Do not let a stale automatic cookie response overwrite a newer fixed preference.

After the safe mutation, use Next's normal Server Action UI update or a guarded
router refresh. Preserve route, search parameters, recorder state, playback,
unsaved draft, expanded family-tree nodes and scroll/focus where possible.
Updating cookies can re-run server-data-dependent effects even without an app
unmount; inspect these effects and add regression tests, rather than assuming
framework behaviour alone protects a recording.

Expose a persistent selector with native names `English`, `简体中文` and Auto.
An inferred switch shows a localized status notification and Undo. Implement Undo
as an explicit previous-locale preference so the detector cannot immediately flip
back. Avoid a blocking confirmation for normal eligible automatic switches.

Same-viewer cross-tab notifications may carry locale/revision only. Each tab must
check its own recording/dirty state before updating visible UI. Do not globally
force reloads, use another viewer's event, or interrupt third-party payment state.

## 5. Input detector wiring

The text adapter takes an ordinary function dependency:

```ts
import {francAll} from 'franc';
import {detectDirectUiText} from './text-signal';
const signal = detectDirectUiText(currentViewerUiInput, francAll);
```

Only call this on application-identified UI input after its normal submission.
Do not send typing/keystroke streams or all memoir messages to the detector. Derive
event ID, origin, finality, actor and revision from the actual application state.
Do not trust a supplied `actor: 'current-viewer'` field as authentication. Passing
this same function across actor/project contexts without scope checks is unsafe.

Do not perform a second transcription or AI request only to detect the interface
language. Existing explicit UI voice commands can reuse already-authorized ASR
metadata; uncertain or unsupported outputs abstain. An inference output must not
execute arbitrary tools, read secrets or edit the application source at runtime.

Enable the module only after real detector fixtures pass in the target repo. The
bundle tests test the adapter with fake rankings, not the franc implementation.
If text mode stays disabled, describe the delivered feature as browser/account
automatic UI localization, not conversational language detection.

## 6. Complete app-owned localization

Create a surface inventory with columns `surface`, `state`, `catalogue namespace`,
`localization method`, `test`, `review status`. Check existing routes, not imagined
ones. Include empty, loading, success, error, offline, permission and validation
states. Search JSX text, string props, toasts, schemas, accessibility text, status
mapping and server-generated content. A regex scan is only a lead generator.

Use `useTranslations` for supported client components and `getTranslations` for
appropriate server code. Don't concatenate fragments. Localize system-owned text
including notifications and emails with the recipient's preference, not an admin's
locale or a job worker's global default. Preserve original user text and quoted
historical captions; label any separate translation. Preserve Mira's standard
interview script in conversationLocale, not uiLocale.

Pass supported locale options to existing external auth/payment widgets. Report
provider-controlled limitations; a web app cannot relabel the browser's own
microphone/OS permission dialog. Localize the explanation before that dialog.
Do not mark an external screen as fully translated without checking it.

Treat the bundled messages as draft examples, not permission/price policy or the
full product copy. Human review is required for consent, privacy, purchase terms,
prices, and Mira's important introductory scripts. Keep real free-session count
as a parameter; do not change billing logic while translating wording.

Backends return stable allowed codes and safe params. UI maps to known translated
messages; unknown codes receive the localized generic error. Never display raw
provider errors or stack traces. Database status identifiers stay stable.

Use Intl/next-intl formatters and the actual timezone/currency. Chinese formatting
of an AUD amount is still AUD. Preserve approximate memoir dates such as 'around
1976' without manufacturing a month/day. Kinship uses actual approved family
relationships; don't choose paternal/maternal-specific Chinese terms from an
ambiguous English 'uncle'. Use installed fonts and flexible layout; don't download
or embed new fonts without a justified licensed regional-delivery plan.

## 7. Catalogue and fallback policy

Enable TypeScript message/locale augmentation against actual catalogues. Run the
Python structural check AND the real ICU AST check. The Python name regex is only
an approximate early check; quoted ICU literals can cause false positives. Resolve
such cases with the AST parser, not by corrupting valid messages. The AST check is
conservative about argument types: use equivalent numeric/date/tag inputs across
locales. Language-specific plural categories may differ; preserve the variables.

An absent parser is NOT a passed ICU test. Generic localized fallbacks must be
reviewed; don't expose raw message keys. Block critical flows if required consent
or payment translations are missing. Track actual human review separately from
structural validity. Do not mark AI-generated strings as human reviewed.

## 8. Completion evidence

Run bundle tests, actual repo typecheck/lint/build/tests and browser acceptance.
Check changed screen states in both locales, narrow widths, long labels and
keyboard navigation. Verify no API language change altered original content,
interview settings, edition selection, currency, entitlements or storage region.
Save a real implementation report with remaining blocked/unlocalized surfaces,
not a fabricated coverage percentage. Distinguish passed, failed, blocked and not
run. No browser available means browser tests are not run, not implicitly passed.
