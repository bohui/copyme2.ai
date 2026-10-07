# Browser locale quality ordering

## Scope

This follow-up to issue #1 was reproduced on main
`3a9a339813ed06fb06ba18815bf32b880072314e` and then integrated on
`76feea0ffcb35a7296870b8eb419b02cb285a434`. It changes only browser preference
negotiation and its tests. The accepted first-reply session bridge, explicit
device preference, account/auth behavior, voice/recovery flows, source text and
book editions are unchanged. The 77 sensitive-copy messages remain pending
human review, and the broader issue #1 acceptance audit remains open.

## Reproduction and contract

Before this change, both the real installed FormatJS matcher and the Next server
render selected a lower-priority exact locale over a preferred regional variant:

| Accept-Language | Before | After |
| --- | --- | --- |
| `en-US;q=1,zh-CN;q=0.1` | `zh-CN` | `en-AU` |
| `zh-TW;q=1,en-AU;q=0.1` | `en-AU` | `zh-CN` |
| `en-US,zh-CN` | `zh-CN` | `en-AU` |

[RFC 9110 sections 12.4.2 and 12.5.4](https://www.rfc-editor.org/rfc/rfc9110.html#name-accept-language)
define quality values as relative language preferences. The application parser
already sorts equal weights in header order; the resolver now honors that
tie-break too. This is not a claim that every HTTP implementation must use it.

The [FormatJS API](https://formatjs.github.io/docs/polyfills/intl-localematcher/)
accepts requested tags, supported tags and a no-match default. The locked version
is `@formatjs/intl-localematcher` 0.6.2. Its installed `BestFitMatcher` and
`findBestMatch` implementation compare language/script/region distances across
the entire requested list; they do not receive HTTP quality weights. Sorting the
list before that call therefore did not guarantee the application's intended
quality ordering.

## Change

The resolver now examines each valid preference in descending quality/header
order, calling the same best-fit matcher with one tag at a time. It uses the
valid `und` tag as a distinct no-match sentinel and accepts only values in the
existing UI-locale allowlist. An unsupported earlier language can therefore be
skipped without prematurely selecting the English application default.

This preserves the existing single-tag regional mappings. In particular, the
current library maps `zh-TW` alone to the available `zh-CN` catalogue; this fix
retains that behavior rather than introducing a Traditional-Chinese catalogue or
making a new script-support decision. Any future script-specific policy needs
its own acceptance decision.

Malformed tags and malformed, duplicate, out-of-range or zero-quality parameters
still follow the existing rejection/fallback rules. Explicit device cookies
still win before browser negotiation. Neither locale parser nor cookie writing
was changed. No dependency version changed.

## Verification

- Focused real-matcher RED: 5 failed, 10 passed against the unchanged resolver
- Focused real-matcher GREEN: all 15 passed after the resolver change
- Real Next server-render RED: 3 failed, 13 passed against the unchanged resolver
- Real Next development HTTP GREEN: 16 passed before adding two further explicit
  cookie-priority checks
- JavaScript app and memoir-composer suites: 227 passed
- Catalogue and ICU validation: 541 messages valid

- Final production HTTP suite: 18 passed, including explicit cookie priority
- Optimized Next 16.3.6 production build: passed

- Full Python regression: 1,678 passed, 232 skipped and one failure in the
  mobile OpenAPI snapshot contract. The same failure reproduces on clean,
  unchanged main `3a9a339`; no locale file is involved. Current `StorySpeechInput`
  permits null `voice` and `instructions`, while the snapshot still records
  their old string defaults. Upstream main `76feea0` corrects that snapshot;
  all 13 focused localization-review/mobile-contract tests pass on the new base.
  No mobile, recovery or voice source was changed in this locale slice. The two additional
  cookie-priority HTTP cases were executed separately in the 18-case production
  run after the full suite had collected its cases.

The browser/hydration test now includes six additional regional,
quality and tie-order cases. Those browser assertions have not been run in this
cloud environment; they remain part of the coordinated native-browser check.
No live model/provider call, production action, migration or deployment is part of
this change.

## Current-main integration

- Base: `76feea0ffcb35a7296870b8eb419b02cb285a434`
- App and memoir-composer JavaScript: 232 passed
- Focused localization manifest and mobile OpenAPI contract: 13 passed
- Catalogue/ICU: 541 messages valid
- Optimized Next production build: passed

- Production HTTP locale contract: 18 passed
- Full portable Python: 1,715 passed, 236 skipped, three warnings; no failures
- The 18 HTTP cases skip in the aggregate run without `MEMOIR_BROWSER_URL` and
  were executed separately against the production frontend
- `git diff --check`: passed

These checks cover this bounded source change; they are not a security audit or
a claim that broader issue #1 acceptance, human review or native browser checks
are complete.
