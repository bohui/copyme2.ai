# Prompts for Codex

## Implement in the current repo

```text
$app-auto-localization

Implement automatic end-user interface localization throughout this CopyMe2 repo.
Follow the supplied next-intl recommendation: en-AU and zh-CN catalogues,
unchanged /memoir/* and /voice paths, explicit device/account preference first,
then automatic language detection. Preserve Mira interview language, original
memories, book editions, currency, timezone and hosting region.

Inspect the actual app and implement the runtime, account/cookie persistence,
safe language switcher, translated UI and tests. Add optional local input-language
detection only on eligible current-viewer UI surfaces; never on interview text.
Do not stop at a spec or leave invented tool/API placeholders. Report any disabled
or untested portion. Do not commit, deploy or run production migrations.
```

## Audit without editing

```text
$app-auto-localization

Audit only. Find missing localization, incorrect preference precedence,
shared-family locale leaks, recording-switch hazards and untested surfaces.
Use the actual repository and produce a path/line-based report. Do not edit code.
```

## Existing next-intl app: focused automatic behaviour

```text
$app-auto-localization

Keep our current translations and routes. Implement/fix first-render browser
language negotiation, account/device preference persistence, safe deferred
switching and Undo. Reuse the actual profile and recorder APIs. Treat existing
English database defaults as automatic unless explicit choice provenance exists.
```

The prompt's own language does not identify the customer's runtime UI locale.
