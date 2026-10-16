# Issue #66: bounded historical-photo discovery expansion (draft)

Base: merged PR #71 / main at `4e7b131dc9bb73405b4af56a8576cd671fab77d3`.
Scope: opt-in offline-testable first slice, not full ticket acceptance.

## Behaviour

- `MEMOIR_PHOTO_EXPANSION=0` preserves existing SerpAPI and warm-Crawl4AI browser discovery.
- When enabled, sparse historical SerpAPI research broadens trusted place aliases
  into archive, street, album/photographer and sampled year searches. At most
  **7 discovery queries**, **36 distinct original/linked pages**, **12 initial leads per query**, **65 seconds**,
  **4 concurrent original page inspections**, **6 same-host album links per page**
  and **2 linked-page hops** are allowed.
- On the keyless Google CSE browser route, the existing warm crawler searches
  at most **3 query pages** with **12 original pages** across the queries.
- Photo evidence remains item-specific. A search snippet or a photographer
  album title is not allowed to date a photograph. Album location context may
  help match linked images, but capture date must come from the inspected item.
- PR #72 P2 repair: only links inside explicit album/gallery item containers
  can inherit location. Navigation, recommendations, sidebars and bare same-host
  links are excluded. Conflicting photo location metadata or recognizable
  different-city titles veto inheritance. This is not a global gazetteer.
  Verified sibling members may still inherit locality without inventing a date.
- P2 follow-up at PR #72 comment 6211230780: explicit item location must retain
  the **geographic anchor** for landmark+city queries. For “离宫, 承德市”,
  “Summer Palace, Beijing” or “summer palace” alone never establishes Chengde;
  “Chengde”, “承德市” and “Summer Palace, Chengde” remain compatible. A child
  explicitly mentioning both the requested city and another known city is
  rejected as ambiguous. The album title cannot override either exclusion.
- Same-host public page restrictions, robots/source validation, source
  deduplication, historical-only fallback, and end-user publish/print guards
  remain in the existing source processors.
- A provider-level failure ends further discovery for that provider, while
  previously verified photos remain available.
- New cache keys avoid treating previously completed sparse legacy results
  as exhaustive after enabling the new feature. Rollback retains legacy keys.

## Offline verification plan

Run from a clean checkout of this PR with project dependencies installed:

```sh
python -m pytest -q tests/test_place_photo_browser.py
python -m pytest -q tests/test_photo_worker.py tests/test_place_photo_pages.py
python -m pytest -q tests/test_place_photo_relevance.py tests/test_llm_place_photos.py
```

The new controlled fixtures cover a one-photo initial search expanded to ten
source-verified photographs, distinct item dates in albums, wrong-city and
modern exclusions, original fetch receipts, bounded browser queries, provider
outage after partial success, authenticated endpoint readback using MemoryStore,
and expanded-vs-legacy cache separation with HTTPX MockTransport. They do not
require a local PostgreSQL instance or production deployment.

**Verification status (updated 16 October 2026):** P2 helper behaviour was
reproduced in an isolated local Python harness. Nine focused helper-behaviour
checks passed, covering gallery membership, excluded navigation/recommendations,
explicit title/structured-place conflicts and malformed source inputs. These
were checks of a reproduced helper implementation, **not** full GitHub checkout
tests. The PR contains additional controlled original-source/endpoint fixtures
for valid siblings alongside wrong-city metadata and same-host links.
The follow-up geographic-anchor logic was separately exercised with 10
synthetic accepted/rejected locality cases in a reproduced matching harness;
all matched their expected outcomes. The integrated source-inspection tests
for the wrong-city “Marble Boat” case and seven additional locality variants
have been committed but not executed in a full repository checkout.
Full repository pytest, browser and live-provider verification have **not** run.
The commands above are a verification plan, not claimed passing checks.

## Remaining acceptance gates

- The keyed `GOOGLE_CSE_API_KEY` JSON API route is unchanged, and complete
  source-inspection parity across all providers is not yet established.
- The expanded SerpAPI path now publishes verified original-source
  results through the existing `on_items` callback before completing later
  discovery queries. Full JSON/NDJSON endpoint/browser streaming and safe
  diagnostics for partial outages still need independent acceptance.
- Real source availability, archive coverage, dates/attribution, cursor stability,
  refreshed gallery states, CSE widget behaviour and source-budget accuracy
  need independent integrated review and execution.
- A separately approved, bounded forced-fresh live comparison for historical
  Chengde, including April 1983, remains necessary. Do not claim that ten
  accessible real photographs are guaranteed.
- The inherited full-suite failures/errors/skips reported by #71 remain
  unresolved; neither targeted test cases nor a merged predecessor waive them.
- Leave the feature disabled, PR in draft, issue open; no merge,
  deployment, local database access, provider live spend, or migration.

