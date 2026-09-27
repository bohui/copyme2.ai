# App Auto Localization — Memoir app skill

An installable, repository-scoped Memoir skill for implementing automatic end-user
UI localization in CopyMe2 through the app-managed Codex worker. It follows the attached final recommendation:
**next-intl, prepared `en-AU`/`zh-CN` JSON catalogues, existing routes, per-viewer
preferences, and independent interview/source/book languages.**

## What this is

Run this skill inside the app repository. Codex inspects real code, implements
language selection and switching, migrates interface text and tests the result.
The production app then selects locale through ordinary runtime code. There is
no mandatory translation SaaS, custom tool server, MCP server or per-page LLM call.

Installing the skill does **not** by itself modify a running app. No CopyMe2
repository was provided in this conversation, so this package has not changed or
deployed it. The bundle contains executable policy helpers and implementation
instructions; actual Next.js/auth/recording integrations are performed by Codex
in your repository, not invented here.

## Install into Memoir

From the Memoir repository root, with the local Compose stack running:

```bash
make install_skill
```

To refresh only this skill while debugging its activation:

```bash
SKILLS="app-auto-localization" make install_skill
```

The target packages the checked-in repository skill and refreshes Memoir's
managed `codex-worker`; it is not a personal Codex desktop installation. After
installation, matching implementation or audit requests may invoke the skill
implicitly. `$app-auto-localization` remains available for explicit invocation.

No dependency installation is required just to load SKILL.md. Runtime integration
uses the app's existing package manager. The bundle self-tests need Python 3.10+,
Node.js with `node:test` (tested on Node 22) and a TypeScript compiler. Optional
HTTP, text and ICU adapters additionally need their documented project packages.

## Use

```text
$app-auto-localization

Implement automatic UI localization across this CopyMe2 repository using next-intl.
Support en-AU and zh-CN, preserve the existing URLs, and detect the viewer's
language automatically unless they have explicitly chosen one. Keep recordings,
Mira's interview language, original memoir text, book editions, timezone, currency
and hosting region unchanged. Inspect and modify the actual code; add tests and
report anything that remains untranslated, disabled or untested.
```

More focused prompts are in `references/example-prompts.md`.

## Runtime behaviour it implements

| Situation | Result |
|---|---|
| New visitor with Chinese browser preference | Chinese interface on first server render |
| New visitor with English browser preference | Australian English interface |
| Explicit device language | Wins over account/browser/inferred language |
| Saved account language, no device override | Used across authenticated visits |
| No explicit choice; enabled eligible UI-input detector finds consistent language | One safe temporary inferred switch |
| Father speaks Mandarin while daughter uses English controls | No UI switch from interview recording |
| Recording/upload/dirty form/IME/payment is active | Switch waits for a safe boundary |
| User chooses English, 简体中文 or Automatic | Deliberate preference action; always accessible |
| User presses Undo after inference | Restores and pins the previous interface language |
| Unsupported or uncertain language | Keep/fall back to supported UI with language control |

### Browser detection versus input detection

Browser/account detection is the immediate baseline. The optional local text path
uses `francAll` through a conservative adapter and only eligible current-viewer UI
input. It does not monitor memoir content. It needs real detector fixtures in the
target app before activation. Its short-input, mixed-language and script gates
intentionally abstain often; scores are not calibrated probabilities.

The detector's two-event/five-minute/one-switch defaults are new product choices,
not claims from the attached recommendation. Details are in `detection-policy.md`.

## Whole-app scope

Localize application-owned controls, menus, forms, validation, tooltips, status
messages, errors, loading/empty states, accessibility labels, date/number formats,
notifications and recipient-facing system emails. Use external widgets' locale
options where available and report limitations. A web app cannot rewrite the
browser's own permission-dialog text.

Do not change interview questions' chosen language, source transcripts, user names,
existing manuscript text, book edition selection, AUD prices, timezone, hosting
region or session allowance. Existing photo-reference labels preserve whether the
reference is historical, current or undated. Changing UI language is not content
translation, currency conversion or a hosting-region migration.

## Package contents

```text
app-auto-localization/
├── SKILL.md
├── README.md
├── agents/openai.yaml
├── assets/
│   ├── runtime/locale-policy.ts
│   ├── runtime/text-signal.ts
│   ├── runtime/browser-languages.ts
│   └── messages/{en-AU,zh-CN}.json
├── scripts/
│   ├── inventory.py
│   ├── check_catalogs.py
│   ├── check_icu.mjs
│   └── self_test.sh
├── references/
│   ├── product-baseline.md
│   ├── detection-policy.md
│   ├── integration.md
│   ├── acceptance.md
│   ├── example-prompts.md
│   └── sources.md
├── tests/
│   ├── test_runtime.cjs
│   └── test_helpers.py
├── VALIDATION.json
└── test-results.txt
```

The bundled catalogues contain 54 draft keys each, not the entire real app. They
have not received native-speaker or sensitive-copy approval. Catalogue key parity
is not the same as complete app coverage or reviewed translations.

## Run the bundle checks

```bash
bash skills/app-auto-localization/scripts/self_test.sh
```

When TypeScript is installed in your repository rather than globally:

```bash
TSC="$PWD/node_modules/.bin/tsc" \
  bash skills/app-auto-localization/scripts/self_test.sh
```

The test script compiles pure policy/adapter TypeScript in a temporary directory,
runs Node tests, Python helper tests and the structural catalogue check. It does
not install packages or mutate your app. Node/Python/TypeScript must be available.

For the real project's catalogues (replace paths after inspecting your repository):

```bash
python3 skills/app-auto-localization/scripts/check_catalogs.py \
  apps/web/messages/en-AU.json apps/web/messages/zh-CN.json

node skills/app-auto-localization/scripts/check_icu.mjs \
  apps/web apps/web/messages/en-AU.json apps/web/messages/zh-CN.json
```

The second check requires `@formatjs/icu-messageformat-parser` installed/resolvable
in the target app; it exits with an error when unavailable. The Python check
rejects duplicate keys, invalid shape, missing/extra messages and approximate
argument mismatches, but is explicitly NOT a full ICU grammar parser. Run both.
The AST signature check is conservative; inspect legitimate syntax differences
rather than changing translations blindly to silence a validator.

## Validation status for this delivery

**97 offline tests passed: 81 Node tests and 16 Python tests.** Pure TypeScript
compilation and structural equality of the 54-key catalogues passed. Text-adapter
tests inject stub rankings: they validate policy gates, NOT real language accuracy.
The browser adapter, Next.js runtime, authenticated persistence, recorder flow,
real franc classifier and browser end-to-end tests have not been executed here.
Full ICU validation has not run because its dependency is unavailable in this
container. A dependency registry request failed; no successful install is implied.
The ICU checker correctly fails closed when that dependency is absent.

See `VALIDATION.json` and `test-results.txt` for the exact scope. Run the target
repo's own typecheck, build, tests and the acceptance checklist. The skill must
report disabled or blocked features instead of claiming production completion.

## Expected output after Codex runs

Real source changes and a localization implementation report with preference
behaviour, actual account integration, translated surfaces, third-party limits,
remaining untranslated states, human-review blockers and actual test results.
Codex must not automatically commit, deploy or run production migrations.
