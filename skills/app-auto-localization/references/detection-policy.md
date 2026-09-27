# Detection and preference policy

## Which language are we detecting?

Detect an application viewer's preferred **interface locale**. This is not a
language label for every piece of memoir content. The person using the controls
may be a different person from the storyteller.

A daughter can use English controls while Mira interviews her father in Mandarin.
Neither the father's recording nor its Mandarin ASR metadata changes her UI.
A profile's UI choice belongs to the authenticated viewer, not to the project.
No inference from IP, surname, nationality, story location or hosting region.

## Resolution

```
valid explicit device choice                 fixed, wins
else valid explicit account choice          fixed, wins
else valid current-viewer automatic session  temporary new extension
else first supported browser preference      normal automatic default
else en-AU                                  application fallback
```

A browser `Accept-Language` header is a preference signal, not proof of the
speaker's language. Parse its quality values and canonicalize BCP 47 tags. Feed
positive supported candidates in quality order to the resolver. Do not treat
`includes('zh')`, geolocation or the first comma-separated token as negotiation.
If all candidates are unsupported/unacceptable, render the product fallback with
a visible language control rather than claim the visitor chose English.

`en`, `en-US`, `en-GB` use the reviewed `en-AU` pack. `zh`, `zh-CN`, `zh-SG` and
explicit `zh-Hans` use `zh-CN`. `zh-Hant`, `zh-TW`, `zh-HK`, `zh-MO` do not
silently select Simplified Chinese; try the next supported preference, otherwise
fall back and expose the language selector. An explicit `zh-Hans-HK` request is
Simplified Chinese and may map to `zh-CN`; region alone is not identity.
Unsupported languages remain unsupported until catalogues and layout tests exist.
Do not generate an unreviewed new language pack at runtime.

## New input-based automatic mode

Enable only on UI-help/onboarding input where the application knows that the
current viewer is addressing the application. Do not connect a global listener to
every chat message. Eligible input is finalized, same-viewer and fresh; a dedicated
UI voice command may be eligible after authorized microphone use and transcription.
An interview utterance is ineligible even when the current viewer is also the
storyteller. Source-language detection can still happen separately for transcripts.

The bundled local text adapter accepts `francAll` as a normal function dependency.
It uses full-language rankings rather than an English/Chinese-only classifier.
It abstains on short, mixed, quoted, code-like, unsupported, ambiguous or
script-unresolved input. Its small Chinese script marker lists are a conservative
heuristic, not a general Han-script recognizer. Rank scores are not probabilities.
Run a target-domain detector benchmark before enabling this mode in production.
When unavailable, leave it off; browser/account automatic selection still works.

Default candidate gates:

- At least 60 letters for an English candidate; at least 20 Han characters and
  Simplified script evidence for a Chinese candidate.
- Two distinct, consistent, final events within five minutes.
- No deliberate device/account choice may be active.
- At most one inferred switch per current-viewer UI session until Auto is reset.
- Mixed, weak or contradictory eligible signals reset the consecutive candidate.

These are product defaults, not research-derived certainty thresholds. They
prioritize avoiding disruptive switches and deliberately miss some valid samples.
Treat first-time browser resolution separately: it does not wait for two messages.

## Commands and deliberate choice

A language selector is the authoritative non-LLM way to select a fixed locale.
A clear direct UI instruction such as 'Change the interface to Chinese' can also
be treated as deliberate intent if the existing application routes commands to a
validated preference action. Do not add brittle phrase matching across arbitrary
pasted text. 'Translate this paragraph into English' is not a UI-language command.
An explicit unsupported-language request presents available choices without
pretending to translate the entire app.

## Safe transition

```
observation → eligible? → consistent? → new locale candidate
    → busy? queue with expiry and expected revision
    → safe? re-check preference + identity + revision
    → persist appropriate preference → update locale provider
    → success: commit reducer state → localized notice + Undo
```

Busy includes recording, an unsaved recording, active upload, IME/text composition,
unsaved forms and payment. Manual switches obey the same data-preservation gate.
Never discard recordings to satisfy a locale change. No reload/remount keyed on
locale; recorder effects must not restart just because translated text changes.
A failed preference write leaves the old active locale and exposes a safe error.
The reducer's `apply` result is a proposal, not evidence of successful persistence.

Manual choice cancels inference and pending work. Undo restores the old UI and
pins it. Automatic clears only the viewer's fixed UI preference after their
explicit action; it does not erase conversation settings. Reset session detection
on login/logout/account change, cancel stale requests, and bind hints to the
current viewer. Do not retain anonymous text inference after a different account
signs in. A fixed anonymous choice may be deliberately carried into the initial
login session, but must not automatically overwrite an existing saved account.

## Data and events

Store only necessary preference data and bounded session metadata. Suggested
application concepts (adapt the actual schema):

```
account: uiLocaleMode ('auto'|'fixed'), uiLocale (supported or null), revision
fixed device cookie: validated locale; provenance distinct from automatic hint
session: viewerScope, locale, policyVersion, revision, expiresAt
```

These are not instructions to create a new table without inspecting the repo.
Do not log raw input, recordings, IPs, family memoirs or full prompts for detection.
Emit only result reason, supported locale, policy version and necessary bounded
operational metadata through the application's existing privacy controls.
