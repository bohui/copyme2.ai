# Historical photo sources: Chengde in the 1980s

Research checked 2026-09-28. Recommendation: prioritize Flickr's documented search and album APIs, then add a broad image search API for discovery. Increasing Commons limits alone cannot establish ten relevant photographs. A verified photographer album already demonstrates substantially more relevant material exists.

## Verified source and date evidence

[Chengde 承德 1983, by kattebelletje](https://www.flickr.com/photos/kattebelletje/albums/72157614775600805/) reports **115 photographs**. The photographer describes an October 1983 visit and notes that some pictures were taken by their mother in May 1984. Both dates satisfy a **1980–1989 decade** request, but neither satisfies **exactly 1980**. Keep this distinction explicit in query normalization.

The following individual source pages were opened; each displays a capture date in October 1983 separately from its March 2009 upload date:

| Photo | Source |
|---|---|
| Small Potala gate | [3331819468](https://www.flickr.com/photos/kattebelletje/3331819468/) |
| Summer palace | [3330979551](https://www.flickr.com/photos/kattebelletje/3330979551/) |
| Chengde streets | [3331810508](https://www.flickr.com/photos/kattebelletje/3331810508/) |
| Temple | [3331804480](https://www.flickr.com/photos/kattebelletje/3331804480/) |
| Palace tower and lake | [3330980297](https://www.flickr.com/photos/kattebelletje/3330980297/) |
| Lake lotuses | [3330978689](https://www.flickr.com/photos/kattebelletje/3330978689/) |
| Willow trees | [3331813658](https://www.flickr.com/photos/kattebelletje/3331813658/) |
| Pavilions | [3330977377](https://www.flickr.com/photos/kattebelletje/3330977377/) |
| Camel photography | [3331811890](https://www.flickr.com/photos/kattebelletje/3331811890/) |
| National Day | [3330975589](https://www.flickr.com/photos/kattebelletje/3330975589/) |

All ten pages show a Creative Commons rights link. The first photo's link was followed and resolves to [CC BY-NC 2.0](https://creativecommons.org/licenses/by-nc/2.0/). Check the exact license per photo; do not assume the whole album shares one license. The noncommercial restriction matters if this product is used commercially. Attribution should retain photographer, source and license. These are verified metadata examples, not a claim that all 115 images are unique, visually suitable, or licensed for every deployment.

Another first-party example, [Stan Siao's Chengde street photograph](https://www.flickr.com/photos/199156859@N02/54754232265), describes 1988-04-29 but was uploaded in August 2025. It is marked all rights reserved. This illustrates why upload date is not historical date and discovery does not establish reuse permission.

## API comparison

| Source | Documented capability | Practical conclusion |
|---|---|---|
| **Flickr** | `flickr.photos.search` supports text, capture-date bounds, license filters, photo-only media, page/per_page (up to 500), and metadata extras including description, date_taken, owner_name and image URLs. An application API key is required; public search does not require user OAuth. [Search API](https://www.flickr.com/services/api/flickr.photos.search.htm) | Best evidenced option for this location/decade. Use separate English/Chinese queries, capture-date filtering, then validate metadata and deduplicate. Query place alone within dates as well as place plus historical years. |
| **Flickr albums** | `flickr.photosets.getPhotos` accepts album ID, owner ID, API key, metadata extras and pagination (up to 500 per page). [Album API](https://www.flickr.com/services/api/flickr.photosets.getPhotos.html) | Expand discovered albums, rather than depending on every image having the city in its title. The verified album ID is `72157614775600805`. Do not use undocumented website keys or scrape private API endpoints. |
| **Brave Images** | Subscription-token authentication; up to 200 images per request; language/country targeting; source-page, original-image and thumbnail URLs. No pagination/offset. `page_fetched` means crawler time. [API reference](https://api-dashboard.search.brave.com/api-reference/images/image_search) | Useful independent discovery channel. Request a substantial candidate pool, then inspect source pages for actual dates and rights. It has no documented historical capture-date guarantee. No authenticated relevance benchmark was run here. |
| **SerpAPI Baidu** | `engine=baidu`, Chinese queries, `ct=2` for simplified Chinese, result offset `pn`, up to 50 results via `rn`. [Provider documentation](https://serpapi.com/baidu-search-api) | Useful for discovering Chinese articles and albums. This documented endpoint is Baidu web search, not a dedicated historical-image archive or guaranteed image API. Avoid interpreting webpage time filters as photo capture dates. No authenticated benchmark was run here. |
| **Openverse** | Openly licensed media search; documented client supports image queries, source/license filtering and authenticated or unauthenticated clients. [Official client documentation](https://docs.openverse.org/packages/js/api_client/index.html) | Useful supplementary discovery across providers. Local unauthenticated requests for `Chengde`, `Chengde 1983`, and `承德` all returned HTTP 403 in this research environment. Coverage is unverified, not zero. |
| **Library of Congress** | JSON/YAML collections search and item metadata. [Official API documentation](https://www.loc.gov/apis/json-and-yaml/) | Keep as an archival fallback; this research did not establish ten Chengde 1980s photos there. |

Flickr application setup is documented in the [developer guide](https://www.flickr.com/services/developer/api/); select an appropriate key category according to the [API terms](https://www.flickr.com/help/terms/api). API access does not override each photographer's image license. No account signup, purchase or credential modification was performed.

## Other archival evidence

[Reed College's Peking, Chengde, 1985 record](https://archivesspace.reed.edu/repositories/2/archival_objects/7431) identifies photographs/slides in the Francis and Clare Murphy collection. It confirms relevant physical holdings and research access, but the record does not itself provide ten downloadable images; it is not an immediate gallery API solution.

## Integration acceptance criteria

1. Count only unique photographs with evidenced place and capture period. Exclude currency, objects, maps and modern uploads without historic capture evidence.
2. Preserve distinct capture-date, upload-date and source-page-date fields. Unknown dates do not satisfy the decade quota.
3. Expand relevant albums and retain album provenance for items with generic titles.
4. Require ten eligible images before reporting the target met; a source failure must remain distinguishable from an empty result.
5. Keep key configuration and provider failures observable. Refresh previously persisted short galleries once a provider becomes available; changing search code cannot retroactively refresh old records by itself.

The minimum-ten target is supported by the ten individually checked Flickr records above for the **1980s**. End-to-end API retrieval remains unverified until a valid application key is configured.
