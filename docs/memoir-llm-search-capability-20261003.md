# LLM web-search capability check — 2026-10-03

## Finding

The configured local gateway is reachable at the existing `.66.1:4000/v1`
endpoint. Its authenticated read-only `GET /models` response lists only
`gpt-5.6-luna-pooled` and `legal2ai-luna-low`; it does not advertise tool
capability metadata. A `GET /responses` `405` was not treated as a capability
signal because it used the wrong HTTP method.

The checked-in Codex runtime writes a Responses-compatible provider config, but
does not declare `web_search = "live"` or
`supports_standalone_web_search = true`, and it does not expose an external
search connector to Memoir. The local Codex feature inventory reports
`search_tool` as removed/disabled and `standalone_web_search` as
under-development/disabled. The worker can observe a `webSearch` activity item
if a runtime emits one, but that telemetry is not proof that a search occurred.

One bounded, authenticated, synthetic POST probe was then sent to
`/responses` with the native-looking `{"type":"web_search"}` tool request.
The gateway returned HTTP 200 with a response id and model, but the response
contained only `reasoning`, `message`, and `output_text` item types, with zero
observed web-search items and zero citation hosts. The result is recorded as
`inconclusive_no_search_evidence`, not as a provider failure or a capability
pass. It establishes that this route accepted the request shape, but it does
not establish tool execution. Receipt:
[provider-web-search-probe-20261003-escalated.json](../var/memoir-five-case-evaluation/provider-web-search-probe-20261003-escalated.json).
A model-generated URL or citation remains untrusted unless the application
records an actual tool/provider request, returned source and capture timestamp.

## Existing parallel path

`place-photo-research` already runs its configured SerpAPI and Google CSE
catalogue searches independently, with bounded timeouts, a 24-hour public
metadata cache, source-page/date/rights filters, provider attribution and
cross-provider image deduplication. A CSE challenge stops CSE retries while
preserving sibling results. This is the current production-shaped search path;
it does not pretend that an LLM citation is a sourced photo record.

## Safe future adapter

If a future gateway exposes a genuine provider-native search tool, add it as a
third, flag-off adapter behind an explicit capability preflight. The preflight
must force or otherwise make tool use observable and require a returned source
receipt; a 200 plain answer is insufficient. Run the adapter in parallel with
SerpAPI/CSE, normalize every result into the same candidate record, and pass
all candidates through the existing location, capture-date, rights, URL-safety
and fingerprint filters. Persist provider name, tool-call receipt, source URL,
observed metadata, capture time and rights state; never cache private prompt
text, bearer URLs or guessed citations. A provider/tool failure must be
isolated from the catalogue siblings and report unavailable, not an empty
match. Keep the current provider as the default until a bounded live preflight
demonstrates tool execution and citation provenance.

No new key, subscription, security permission, external sharing or provider
was enabled by this check.
