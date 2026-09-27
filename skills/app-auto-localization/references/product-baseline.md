# Source baseline and additions

## User-provided basis

Source: `Pasted text(20260926-094026).txt`, 549 displayed source lines, attached
26 September 2026. This skill follows that recommendation rather than replacing
its architecture. The original file was supplied in full; no repository source
code was provided with this request.

| Source lines | Requirement retained |
|---|---|
| 1–5 | next-intl; one app; prepared UI translations; no per-page LLM translation |
| 7–39 | Separate UI/interview/source/book language, timezone and region; per-account UI |
| 41–71 | Same `/memoir/*` and `/voice` paths; no locale prefixes; `en-AU`, `zh-CN` |
| 73–87 | Explicit device > account > browser > default; persist deliberate signed-in choices |
| 89–218 | Namespaced JSON; full ICU messages and placeholders; adapted Chinese copy |
| 222–383 | Request-scoped messages; explicit loaders; root provider; server-side cookie updates |
| 385 | Defer changing language until an active recording is safely saved |
| 387–458 | Stable API codes; safe fallback; conversation/source/edition independence; TTS keys |
| 460–500 | Locale formatting not currency conversion; preserve approximate dates; layout/accessibility |
| 502–534 | Git catalogues, human review for sensitive copy, type and catalogue/interaction tests |
| 536–547 | Public marketing locale URLs are optional separate work, not an app route migration |
| 549 | next-intl + EN/ZH JSON + per-user UI preference, independent Mira/book language |

## Added to satisfy automatic identification

These are proposed implementation policies added by this package, not statements
from the original attachment:

1. A temporary automatic-session locale between saved account and browser signals.
2. Optional local language classification of current-viewer UI input, with two
   consistent events and abstention on uncertainty; no use of memoir transcripts.
3. Automatic/fixed modes, visible Undo, a bounded evidence window, revision checks,
   account-bound session hints and deferred state transitions.
4. Conservative supported-locale mapping: explicit Traditional Chinese is not
   silently labelled Simplified Chinese. Generic browser `zh` maps to the initial
   `zh-CN` catalogue as a product fallback, not an inference about identity.
5. A coding skill that implements the runtime in the repository; it is not a
   production agent that autonomously rewrites UI strings per end-user request.

## Source limitations

The attachment does not include the current repository, actual authentication
schema, complete translation inventory, localization test outputs, a text-language
detector, accuracy measurements or an implemented runtime auto-switch tool.
This package must not claim these already exist. The implementation skill inspects
and supplies the missing integration in the actual repository when invoked.
