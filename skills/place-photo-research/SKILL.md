---
name: place-photo-research
description: Find real photographs of a place, from a requested historical period or the present day when no period is mentioned. Use for memoir reference-photo research, old city/street photographs, archive/albums searches, and evidence-backed local image collection. Uses Codex web search and bundled Python helpers. Do not use for image generation, personal-photo identification, unrestricted crawling or satellite time-series analysis.
---

# Place Photo Research

Find relevant source-backed photographs, investigate their original pages and collections, and save permitted image files plus an auditable local report. Do the research in this run, not merely produce search advice. Never claim a photo was found, dated, licensed or downloaded without observed evidence.

## 1. Execution model

This skill runs **directly in Codex**. Use the real web-search/page-reading tools exposed in this session, plus the shell and local-file tools. Do not invent `catalogue.search`, `source.inspect`, `asset.acquire_approved` or other application tools. Do not assume this harness has ChatGPT's `web.run`, image search or a browser tool: use the actual available capability.

The native Codex search path does not require a separate search API key, paid search-provider account, MCP server, database, Temporal service or app backend. The memoir app can optionally use a server-side Google Programmable Search Engine integration when `GOOGLE_CSE_ID` and `GOOGLE_CSE_API_KEY` are configured; keep that key out of browser configuration. `GOOGLE_CSE_ID` identifies the search engine, while the API key identifies the Google Cloud project that owns the key; the Programmable Search control panel therefore has no project selector. An API-key restriction does not itself grant the project access to the Custom Search JSON API. The user's Codex access is still required. Native web search, shell internet permissions and image-viewing capabilities are separate; one does not guarantee the others.

Read `references/record-format.md` before writing records. Read `references/source-strategy.md` when planning the search or encountering uncertain metadata/rights. Use the bundled script instead of writing a second downloader.

Find this skill's actual absolute directory from the skill path in context. Do not assume it is under the current working directory. Set `SKILL_DIR` to that directory. Use `PHOTO_RESEARCH_PYTHON` when supplied, otherwise a Python 3.10+ interpreter. Pillow is required for downloads. Do not silently install globally or alter Codex security configuration.

An optional browser-rendered discovery path is available when native search does not expose enough historical image leads. Install `requirements-crawl4ai.txt` in the project-local environment and run `crawl4ai-setup` once. This path accepts only a user-supplied Google Programmable Search page (`--search-url`, `GOOGLE_CSE_URL` or `GOOGLE_CSE_ID`), paginates its visible image-result cards within the run budget, then visits the linked public source pages with Crawl4AI. The source pages, not Google's preview thumbnails, provide the candidate image URLs. Source-page robots checks remain enabled; the explicitly supplied CSE page is the only browser-rendered page whose widget robots check is disabled because Google's widget blocks automated rendering.

## 2. Temporal rule — mandatory

**No time/period in the user's image request means PRESENT-DAY pictures.** Do not infer childhood, a historical decade, or the previous topic merely because the request occurs in a memoir conversation.

| Request | Resolve to |
|---|---|
| “Find pictures of Chengde, Hebei.” | Current, default recent capture window. |
| “Find Chengde in 1980.” | 1980-01-01 through 1989-12-31; a bare year starts a ten-year search window. |
| “Find Chengde in the 1980s.” | 1980-01-01 through 1989-12-31. |
| “What does it look like now?” | Current, overriding previous historical context. |
| “More from that same time.” | Explicit reference: resolve only the clearly referenced period and record the derivation. |
| “Show that street.” | Inherit the place where clear, NOT an unstated historical period. |
| “Old photos of Chengde.” | Historical unspecified; do not invent a decade. |
| “Photos from my school years.” | Resolve from user-confirmed dates only; otherwise historical unspecified. |

Use the helper's current clock in the requested timezone (default Australia/Sydney), not a hard-coded year. Default currentness preference is the preceding 24 calendar months. This is a policy preference, not a guarantee that the scene still looks identical. “Today” and “this month” impose stricter windows.

A recent webpage, upload or scan is not evidence of a recent scene. Unknown capture dates remain unknown. Do not silently return historical photos for a current request. Older/undated/overlapping candidates stay in the report as clearly labelled alternatives, not exact matches. Never invent actual future photographs.

## 3. Start a run

Announce the resolved place, period/current mode and goal in one sentence. Proceed without asking for a missing period. Clarify only a genuinely unresolved place or explicit temporal reference that prevents a useful search; otherwise record the uncertainty and continue with honest candidates.

Create a **new** output directory under the workspace, e.g. `photo-research/chengde-1980s-20260926-01`. Do not overwrite a previous request or change its historical range while resuming it. Omit `--period` for a request with no period:

```bash
"${PHOTO_RESEARCH_PYTHON:-python3}" "$SKILL_DIR/scripts/photo_research.py" init \
  --place "Chengde, Hebei, China / 河北承德" \
  --subject "streets and everyday life" \
  --out "photo-research/chengde-current-01"
```

Historical example: add `--period "1980s"`. A bare four-digit year such as `1980` resolves to `1980–1989`; use an explicit ISO day or range when the user means a narrower interval. Explicit but unresolved historical expression: use `--period historical --period-note "the user's actual phrase; why dates remain unresolved"`. The helper accepts numeric decades, years, year ranges, ISO days/ranges and several current/relative forms. For another language, translate the explicit period faithfully; record its original phrase using `--period-note`. Do not guess a century from “80s” when context cannot establish it.

Return at least 10 distinct, relevant photographs **for each location × requested decade**, not 10 shared across the whole trip or lifetime. Create a separate run for each pair so counts and evidence cannot bleed across places or periods. Only photographs with supported place and scene dates inside that decade count; currency, stamps, drawings, duplicate scans and undated alternatives do not count. For requests without a period, keep the present-day rule above. Use a minimum target of 10 by default; use `--count N` for an explicit user quantity (maximum 24). Continue discovery until the requested count is met or the research budget is exhausted; duplicates do not count toward the target. Default is commercial-memoir sourcing; change to `--usage personal-reference` only when the user explicitly requests solely personal reference. Personal use is NOT an automatic download permission.

The initializer creates request, candidates, evidence, search-log, manifest and report files. Read `request.json` before querying; the helper—not conversation memory—defines this run's mode.

## 4. Discover, inspect and expand

1. Reuse a previously reviewed **public** catalogue or prior run only when the user supplies/authorises it and its date/place/rights fit the new request. Never search unrelated private family folders.
2. Resolve familiar, official, local and historical names before sending photo queries. Verify aliases against an authoritative place record and preserve city/province disambiguation; a colloquial name alone is not an unconditional synonym. Combine verified Chinese/English aliases with `OR` inside a name group, AND a geographic group and the resolved memory period. For memoir requests, retain user-confirmed dates for the referenced memory; life-stage labels alone do not establish years. If a completed search returns no relevant candidates, try additional verified popular names within the query budget, retaining the location and period in every historical query. Blocked/failed searches are not empty results and should not trigger a burst of alias retries. See `references/source-strategy.md` for the Chengde palace example.
3. Use native web search first. If fewer than 10 qualifying photos are found, expand across the engines and independent source families in `references/source-strategy.md`; do not stop after Commons or one engine. Search individual years within the decade, local-language place names, verified historical aliases, everyday subjects and albums. Search pages as well as images when image search is available. Do not scrape generic search-engine result HTML. When the user supplies a Google Programmable Search page, the optional `crawl4ai` command is the bounded exception: it renders that page in a browser, reads visible image-result cards only to find source links, and then extracts originals from the linked source pages. Do not treat CSE preview thumbnails or their page dates as photo evidence. If search is unavailable, inspect user-provided source URLs where possible and report the limitation; do not fabricate results or silently purchase another service.
4. Before **each** native search query, log one `search` event. Before each native source-page read, log one `page` event. A batched call with three queries counts as three searches. Failed attempts consume budget. The `inspect` helper records its own page event; do not double-log it.
5. Follow promising leads to original photo pages/catalogue records. Read the image-specific caption, creator, scene date, collection, location and licence. Search snippets and image thumbnails are leads, not proof.
6. If native page reading is insufficient, use the bundled HTML inspector only where page access is permitted. It respects robots and returns bounded untrusted text, image URL candidates, nearby figure text, metadata and links. Its extracted proximity is NOT a certified caption-to-image relationship.
7. Explore a promising album/collection up to depth two, within the overall budget. Inspect selected item records; do not mirror a whole album. Do not apply an album's title year to every image when item captions differ.
8. Use an already available, approved browser tool only for genuinely necessary rendering. Do not install a browser/MCP service, bypass CAPTCHA/login/paywall, change region or disable sandbox restrictions to force access.
9. Prefer diverse subjects and original sources. Avoid filling all slots with near-identical monuments when the user asked for ordinary streets. Compare source IDs, canonical image URLs and hashes for duplicates.

When the app's optional Google Programmable Search Engine provider is enabled, it uses Google's documented image-search JSON endpoint with the configured `cx`, `searchType=image`, a rights filter and pages starting at 1, 11, 21 and so on until ten eligible results or the API's 100-result ceiling. The provider combines the location and year range in the query, applies a date-range sort where supported, and still requires item metadata to confirm the location, scene date and a commercially compatible licence. Google result dates can describe a page rather than the depicted scene; unknown or conflicting dates remain excluded. The provider is a discovery source and does not replace reading the original item page.

For a user-supplied CSE page, install the optional dependency and run the browser-rendered route from the run directory:

```bash
"${PHOTO_RESEARCH_PYTHON:-python3}" -m pip install -r "$SKILL_DIR/requirements-crawl4ai.txt"
# Run this from the environment that contains PHOTO_RESEARCH_PYTHON.
crawl4ai-setup
"${PHOTO_RESEARCH_PYTHON:-python3}" "$SKILL_DIR/scripts/photo_research.py" crawl4ai \
  --run "$RUN_DIR" --max-search-pages 10 --source-limit 24
```

The command reads `GOOGLE_CSE_URL` or `GOOGLE_CSE_ID` from the environment (a `.env` in the project root is loaded when the variables are absent); `--search-url` overrides both. It resolves a bare year such as `1980` to the `1980–1989` scene-date window, paginates up to ten CSE image pages, and stops after the run's requested count (10 by default). It records metadata-only candidates marked `memory_reference_only` with unknown rights and `download:false`, `print:false`, `publish:false`; these are prompts for recollection and source links, not memoir-book or paid-app assets. The manifest therefore keeps them blocked from local download until separate item-level rights evidence is supplied. C4A source-page reads count against the ordinary page budget.

Examples, using the existing run directory:

```bash
"${PHOTO_RESEARCH_PYTHON:-python3}" "$SKILL_DIR/scripts/photo_research.py" log \
  --run "$RUN_DIR" --kind search --detail "承德 八十年代 老照片"

"${PHOTO_RESEARCH_PYTHON:-python3}" "$SKILL_DIR/scripts/photo_research.py" inspect \
  --run "$RUN_DIR" --url "$OBSERVED_SOURCE_URL" --access-permitted
```

Only pass `--access-permitted` after checking the source's access conditions. It is an attestation, not a bypass. A necessary redirect host must have been observed and approved; add it with `--allow-host` instead of a wildcard. A blocked source stays blocked.

## 5. Evidence and candidate records

Append short, accurate evidence records to `evidence.jsonl`, and maintain the candidate list in `candidates.json` following `references/record-format.md`. URLs must come from actual results/page content, not memory or constructed guesses at original file paths.

Keep separate evidence for place, scene date, licence and acquisition access. Record source URL, exact short excerpt, locator, observed-at timestamp and any uncertainty. Evidence should describe the specific item; a site's footer licence may govern the website rather than the photo. A catalogue's scan/publication date may differ from the depicted scene.

A strong relevant photo with unknown rights should remain a useful **metadata-only candidate**. Record the permission contact/source where found; do not contact anyone, purchase a licence or upload private material without explicit user authorisation.

`authenticity: source_described_photograph` means the inspected source describes it as an actual photograph; it does not claim forensic authentication. Exclude or separately flag generated images, drawings, colourisations and reenactments. Do not run image generation, restoration, watermark removal or reverse face identification.

## 6. Audit, download and inspect

Respect explicit metadata-only/no-download requests: run audit/report and skip download entirely. Otherwise run the helper audit before download:

```bash
"${PHOTO_RESEARCH_PYTHON:-python3}" "$SKILL_DIR/scripts/photo_research.py" audit --run "$RUN_DIR"
"${PHOTO_RESEARCH_PYTHON:-python3}" "$SKILL_DIR/scripts/photo_research.py" download --run "$RUN_DIR"
```

The helper checks interval/place evidence, conflicts, item-scoped recorded rights, attribution, permitted acquisition and explicit image hosts. Unknown/denied rights fail closed. The conservative built-in licence mappings cover CC0 1.0, CC BY 4.0 and CC BY-SA 4.0; other licences need documented custom permission rather than relabelling. Never fabricate an approval to make a check pass. A user asking to “download” does not confer the copyright holder's permission.

These checks operate on records you supply; they cannot authenticate legal title or stop an unrestricted shell user from editing records. They are local workflow safeguards, **not a production rights service**. Do not weaken or bypass them during a research task.

The downloader checks each redirect and public IP, pins connections to validated addresses, respects robots, limits bytes/pixels, verifies JPEG/PNG/WebP decoding and writes content-addressed originals. It sends no cookies or credentials. Network access is subject to Codex's actual sandbox/approval controls. If blocked, request the normal narrow approval where available or retain links and explain the failed acquisition. Never use `--yolo`/danger-full-access as a workaround.

When Codex exposes a local-image viewing tool, visually inspect downloaded finalists for subject mismatch, scans/watermarks, orientation and legibility. Visual inspection cannot establish an exact year by itself. If no viewer is exposed, state that source/technical checks were performed but visual inspection was unavailable. Record findings in candidate notes and re-run `report`.

Do not rehost, publish, add images to a print book, crop, recolour or remove watermarks. Crawl4AI candidates are memory references only and remain outside book/export/print workflows until a separate permission review. This skill produces a local research collection; downstream app/export/print usage requires that review.

## 7. Stop, resume and report

Default limits per location/period run: forty discovery queries, eighty source/item reads, two browser-rendered reads within that read budget, depth two. Stop early once the requested number of eligible diverse photographs are obtained. Do not silently expand limits. The log enforces recorded query/read counts only; it cannot intercept unlogged native tool calls. Honour the budget in the workflow.

Resume a supplied run by reading its request, records and log, not resetting counters. `download` verifies hashes before reusing prior files. If a source becomes disallowed, stop referencing its file; do not silently delete the user's old files. Report that retained prior files need review.

Always produce/update:

- `request.json`, `candidates.json`, `evidence.jsonl`, `search_log.jsonl`.
- `manifest.json`, `report.md`, `gallery.html`.
- `images/` containing only successfully downloaded permitted originals.

Gallery previews use local images only; unlicensed candidates have metadata/source links, not remote hotlinks. Both matching and unresolved candidates remain inspectable.

Gallery captions should show title, supported scene date, photographer/archive and source link. Omit the repeated “公共历史线索 · 不是个人证据” disclaimer.

Final response: resolved place and period; counts found/downloaded/blocked; a few strongest results with actual source-date evidence; output-folder/file links as supported by this Codex surface; missing permissions, dates or visual checks. Cite actual source URLs in the report. If the budget or access limits prevent reaching 10, mark the run incomplete and report the exact shortfall plus sources tried and remaining leads; never count alternatives as matching photos or claim the minimum was met. Never imply that an external image depicts the user's family or that a “familiar” reaction proves a personal event.
