# Lane B photo-research baseline

This round investigates `memoir-place-photo-research`. The running photo worker
has **LLM discovery disabled** (`MEMORY_SPARK_PHOTO_WEB_SEARCH=0`) and standard
expansion (`MEMOIR_PHOTO_EXPANSION=0`). It uses configured SerpAPI, the Google CSE
browser and Commons discovery; Flickr is not selected while SerpAPI is configured.
Placeholder environment strings must be normalized with `_configured_env`:
the worker's `GOOGLE_CSE_API_KEY` and `FLICKR_API_KEY` resolve to unset, despite
being nonempty strings in a naive environment-presence check.
There is no enabled model call to shorten in this skill. Enabling its optional
model would add a call rather than remove existing work.

Reviewed checkout: `d1e624d`, whose application sources match main `527fc73`.
Read-only runtime inspection confirmed matching hashes for the provider,
pagination, browser and optional discovery prompt sources. No application,
prompt, service setting, shared public cache or customer state was changed.

## Execution and delivery

| Step and source | Input / work | Output / dependency |
| --- | --- | --- |
| 1. `agent_routes.project_place_photos` | Authenticate bearer, load owned project, scope cursor to owner plus project, validate coordinates and resolve admitted research period/context year. | A separate photo request. It does not block delivery of the current interview reply. |
| 2. `place_photo_transport.photo_response` | Admit the registered skill and call the private worker with its server-only secret, or use local `PhotoPages` when no worker is configured. | Actual worker transport has a 240-second timeout. NDJSON is forwarded with bounded decoding and progress records. |
| 3. `photo_worker_service.create_photo_worker` | One warm Chromium process; validate private request and coordinates before streaming; reuse the worker's public `PhotoPages` cache. | Immediate `SEARCHING` is progress, not a photo. |
| 4. `PhotoPages._snapshot`, `_search` | Project-bound cursors over provider-configuration-bound public searches. Load a shared public repository when configured. Revalidate cached metadata; coalesce identical in-flight searches. | Successful completed cache can avoid discovery. Failed/partial entries remain distinguishable. |
| 5. `place_photos._search_period` | Run independent selected providers in a thread pool. The observed configuration selects SerpAPI, the configured CSE browser, and Commons. A real CSE API key would enable its API-first branch. Each retains its native limits and failure handling. | Incremental public photo batches; failures from one provider do not erase another's usable photos. Source verification is intended here but has the observed gaps below. |
| 6. `_google_serpapi_expanded`, `_google_cse`, `_commons`, `place_photo_browser` | Search leads, inspect originals/catalogue metadata, enforce public URL/access/date/location/rights rules and fingerprint images for deduplication. SerpAPI's standard source cap is 12; its discovery deadline is 65 seconds. CSE API permits up to ten result pages and can fall back to the configured browser engine. | Public reference metadata only. Source/upload/publication years do not automatically establish capture years. No personal event is inferred. |
| 7. `search_place_photos`, `PhotoPages._search` | Apply explicit containing-decade fallback where applicable; finish requested-period discovery before a zero-result unrestricted-time pass. Preserve original period and fallback labels. | Exact, nearby/decade and time-relaxed results remain distinguishable. |
| 8. `PhotoPages._matches`, `_page`, `stream` | Rank verified capture periods and proximity, deduplicate, retain stable tiers/cursors, publish NDJSON. Strict GPS results may stream early; a GPS-relaxed tier waits for completed strict discovery. | First useful photo can lag first verified provider result. With no centre, `_matches` also waits for job completion before exposing the locality tier. This is a code observation, not yet a measured speed gain. |
| 9. `client.js:api`, `consumePhotoStream`, photo `acceptPage` | Decode pages, reject stale project/place/period/coordinate scopes, merge/rank photos, render, then save workspace state. | Browser paint and workspace persistence are downstream of the worker and are not timed by the isolated ASGI baseline. |
| 10. `agent_routes._selected_place_news` | Register historical-news research after the selected photo response when a period exists. | Separate Lane B dependency. Historical-news discovery and next-question selection retain their existing acceptance blockers. |

## Prompt inventory

| Instruction / source | Purpose and dispatch | Effective state / provenance |
| --- | --- | --- |
| `memoir/skills/memoir-place-photo-research/discovery` | Optional `photo_research.llm_search`: find original public photograph source leads for `{place, temporal}`. One 568-character managed instruction, input JSON, required native `web_search`, source receipt inclusion, 1,024 output-token bound. No output JSON schema or repair prompt. | **Disabled** in the inspected worker. Published v1, SHA-256 `f101aad128deeb167e7363a38bd3ab4a36cefb54a7e63ebbab5a0cad158fdf46`. |
| Inline tool settings and input | Required native Responses search; requested effort `low`; model comes from shared `MEMORY_SPARK_LLM_MODEL`. Completed search receipts and public source URLs are required before original-page inspection. | Conditional only. Shared worker model is `gpt-5.6-luna-pooled`; the separate interviewer review observed that gateway alias enforcing max effort. No photo model call was dispatched, so observed photo effort remains unavailable. |
| `SKILL.md`, linked record/source guides | Standalone research workflow and contracts used to inspect implementation. Search-query templates, HTML extraction rules and rights filters are deterministic code. | These guides are not concatenated into the application's model instruction. No evaluator/judge prompt is used in this round. |

The optional path already uses direct Responses. Its result decoder's accepted
receipt-ID grammar is narrower than the padded-ID grammar addressed in other
skills; this is an unmeasured conditional compatibility risk, not an observed
failure on the enabled photo path. Do not enable or rewrite it merely to obtain
an LLM baseline.

## Frozen live diagnostic

The manifest under `var/optimise-all-skills-20261022/07-place-photo/plan.json`
predeclares Chengde/1980s and Chinese Sydney/current cold searches, each followed
by an identical warm replay. The observer creates a separate application,
browser and in-memory cache inside the existing runtime image, with
`repository=None`; its configuration remains that of the existing photo worker.
Synthetic owners are used. A wrong-owner cursor check must reject without work.

The finite round budget is zero model calls, at most twelve SerpAPI submissions,
eighty catalogue HTTP gets, 256 safe source/image fetches and 72 browser page
calls. Failures consume budget. Browser-internal assets and robots subrequests
are not separately metered HTTP requests; the application's page/deadline limits
remain active. First useful output is a delivered photo, never an empty progress
record. ASGI send timestamps do not establish browser paint, authenticated
API-to-worker network timing or persistent-cache acceptance.

The first observer launch forwarded no stdin through Mocker. It exited without
executing Python or contacting any provider; its empty logs and cleanup receipt
are retained. The corrected launch explicitly keeps stdin open and rejects a
missing result marker. No failed launch is counted as a completed scenario.

## Observed results

**Acceptance: fail.** These are one-sample baseline results, not an implemented
before/after comparison. The current configuration dispatched zero LLM calls.

| Case | First delivered candidate | Completion | Result / quality |
| --- | ---: | ---: | --- |
| English Chengde, 1980s, cold | 60.335s | 60.337s | Ten time-relaxed alternatives; zero requested-period matches. `READY` does not establish quality: a location-map SVG and a geographically contradictory item were admitted. |
| Same search, warm | 0.0106s | 0.0112s | Identical alternatives; zero new provider or fetch calls. Caching retains the quality defects. |
| Chinese Sydney, current, cold | 17.471s | 21.932s | One in-radius current candidate; honest `PARTIAL`, shortfall nine. Independent visual/rights review remains unverified. |
| Same search, warm | 0.0023s | 0.0024s | Identical candidate, no new provider or fetch calls. |
| Wrong-owner cursor | No photo | 0.0018s | HTTP 422, zero new provider or fetch calls. |

No incorrect Chengde alternative is counted as a quality-passing meaningful
result. Sydney's first candidate exceeds ten seconds; these background timings
do not change the separate agreed foreground 5/10-second gates. Browser paint
was not measured.

The Chengde strict-period pass failed across all three providers: Commons HTTP
403, SerpAPI source unavailable, and CSE source robots denial. After approximately
23.1 seconds the application still started the unrestricted-time pass. This
violates the documented rule that provider failures must not alone establish an
empty strict search. The returned alternatives retain `period_match=any_time`
and `search_fallback=gps_time`, so they are not silently relabelled as 1980s.

The alternative named `承德府位置图1820.svg` is a map rather than a photograph.
The candidate named `承德中央公教住宅` has source coordinates
`25.081926,121.521919`, **1,798.4 km** from the requested Chengde centre.
Removing a distance requirement does not prove that a name shared by another
street/building identifies the requested city. Other name-only alternatives
remain unconfirmed; no visual inspection was performed.

In the unrestricted-time pass, CSE returned its ten candidates at approximately
46.8 seconds from submission. The remaining SerpAPI pass failed at approximately
60.2 seconds; the response exposed the candidates at 60.3 seconds. This shows
about 13.5 seconds of delivery waiting after that provider finished. Those
candidates fail quality, so the difference is an opportunity to investigate,
not a valid speedup or a reason to stream them sooner.

The entire live run used eight SerpAPI submissions, three catalogue HTTP gets,
86 safe source/image fetches and 38 browser page calls, all within the frozen
caps. Sydney's sibling discovery includes source failure/rate limiting, while
Commons returned 403. Original partial/error records are retained. Warm-browser
startup took 2.09 seconds before the per-request timer. The owned jobs finished,
browser close completed, runtime reference was cleared, thread pool shut down,
temporary root removed, and the native runner verified its cleanup. No shared
public repository or hosted project was used.

## Recommendation for a later approved photo change

Quality corrections should precede delivery changes. This is a separate proposed
round from the pending interviewer handoff correction; neither is implemented.

| Priority / proposed change | Measured basis / retained contract | Validation / rollback |
| --- | --- | --- |
| First, distinguish unavailable strict discovery from a completed empty search before permitting time relaxation in `PhotoPages._search`. | All strict Chengde providers failed, but a second pass consumed three more SerpAPI requests and about 37 seconds. An unavailable result is honest failure, not a successful fast photo response. Keep usable sibling results and explicit fallbacks. | Reproduce all-provider failure, completed empty, partial healthy sibling, and persisted-cache states through API-to-client replay. Roll back the small admission-condition change if legitimate completed empty searches cease to fall back. |
| Reject non-photo source records and require locality evidence sufficient for the requested city/province in source/browser admission. | A map SVG and a known contradictory location passed name-only matching. Keep real city-qualified photographs and supported source dates; never remove rights/public-URL/fingerprint guards. | Replay the captured bad items plus held-out bilingual maps, same-name streets, genuine local photos and ambiguous coordinates. No LLM is needed. |
| Only after those pass, evaluate earlier delivery within an established fallback tier. | Approximately 13.5 seconds passed after CSE finished before the failed SerpAPI sibling settled. This is an upper observation from invalid alternatives, not an estimated valid-result gain. Preserve stable tier/cursor behavior and eventual discovery. | Repeat the frozen cold/warm cases and actual public source checks; cover later strictly matching arrivals, ordering, cursor reuse, cancellation and failures. Keep the existing completion barrier as rollback. |

There is no reason to move another photo LLM phase to Lane B: the enabled path
already performs provider research outside the interview reply and has no LLM.
Existing warm caching is effective but cannot repair source quality. The next
model-backed profiling target remains selected-outline composition; game stays
last. Full campaign acceptance is still open.

[Evidence index](evidence/lane-b-photo-baseline-20261023.json) records complete
synthetic requests/worker body events, public metadata, provider observations,
source and harness hashes, failed-launch logs and cleanup. Its companion archive
is lossless JSON. It establishes neither authenticated API/browser behavior nor
shared persistent-cache/deployed-worker acceptance.

Post-merge `make test-place-research` passed on this unchanged application
revision: **604 JavaScript, 466 API/database and 95 standalone checks**. The
isolated runner verified native cleanup. These controlled regression passes do
not overturn the live source/fallback failures above.
