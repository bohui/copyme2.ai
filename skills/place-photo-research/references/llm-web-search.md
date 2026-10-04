# Configured LLM web search

Use this route when the configured gateway supports Responses `web_search` and
`MEMORY_SPARK_PHOTO_WEB_SEARCH=1`. The flag is off by default. Configure the
existing server-side `MEMORY_SPARK_LLM_BASE_URL`, `MEMORY_SPARK_LLM_MODEL` and
`MEMORY_SPARK_LLM_API_KEY` in the environment or project `.env`. Keep the key in
that environment; command arguments and research artifacts contain public data.

After initializing a run, use:

```bash
"${PHOTO_RESEARCH_PYTHON:-python3}" "$SKILL_DIR/scripts/photo_research.py" discover \
  --run "$RUN_DIR" --source-limit 24 --provider-timeout 30
```

The run's resolved place and scene-date window determine the query. Omitted
periods use the current window from the initializer. Historical discovery uses
capture dates, without applying a webpage-publication date restriction. The
helper requests required tool use, at most one search tool call, included search
sources, and a bounded response. It accepts completed search-call receipts and
safe returned sources or native citation annotations accompanying those calls.
A plain answer, even with URLs or citation text, returns an unavailable error.
See the [Responses web-search contract](https://developers.openai.com/api/docs/guides/tools-web-search).

Source inspection uses the existing public-only, pinned-address HTTP fetcher
with robots checks, standard ports, explicit redirect hosts and bounded HTML.
It reads image-specific Photograph/ImageObject metadata and figure captions.
The source must establish the requested place and capture period; page titles,
publication timestamps, search snippets and model prose cannot date images.
Albums retain distinct original image URLs. Capture precision stays a day,
year, decade or documented range.

`discovery.json` records normalized provider, response and tool-call receipts,
source URLs and observation times. Successful public search receipts are cached
within the run for 24 hours, scoped to place, resolved period, gateway and model.
Use `--cache-ttl 0` to refresh discovery. Original pages are rechecked while the
run still needs photographs. Failures consume the ordinary search/read budgets;
individual unavailable pages preserve sibling results. The helper records a
shortfall when the target or read budget prevents completion.

Each request has a bounded timeout; source inspection is limited to 24 pages
and the run's remaining page budget. Unknown rights stay unknown. Candidates
permit memory-reference display only, with download, print and publish disabled.
The ordinary audit and download gates still require separate rights evidence.

Memoir's application photo search uses this same adapter alongside its existing
catalogues when enabled. A gateway or source outage does not discard catalogue
photographs. The private photo worker receives the same server-only settings
through Compose. No new search subscription or Python dependency is needed.
