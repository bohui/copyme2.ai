# Background city-map contract

The service accepts `{ "places": [...] }` with at most 1,000 validated place journeys. Send only public `place`, `hierarchy`, `granularity`, and optional `latitude`/`longitude`; do not send memoir prose, dates, family details, or photos. The authenticated account must own the project.

One conversation can contribute multiple source places. The browser merges all
confirmed `place_journeys` into history before starting membership checks, so
大石庙镇 and 双桥区 are both submitted even without a separate saved 承德 entry.
This service groups those records; the journey skill extracts them from prose.

The result contains `schema_version: 1`, `skills: ["memoir-place-groups"]`, `status: READY | PARTIAL`, and one `places` record per input:

```json
{
  "index": 0,
  "city_key": "[\"中国\",\"河北\",\"承德\"]",
  "city": {
    "place": "承德",
    "hierarchy": ["Earth", "中国", "河北", "承德"],
    "granularity": "city"
  },
  "pin": null,
  "pin_status": "UNRESOLVED"
}
```

A resolved `pin` retains its source display name and own coordinates, with `accuracy: approximate | public-map`. `index` refers to this request's input order, with the newest mention first. Do not use it as a durable identity. A partial provider match can establish administrative membership but cannot create a precise child pin. Provider failure ends further provider lookups in that request; explicit hierarchy grouping remains available. A city mention missing its region joins a full country/region/city path only when that path is unique among the supplied records. Conflicting regions remain separate. Lookup count is bounded and successful public queries share the existing geocoding cache.

The browser keeps enrichment in a project-scoped transient cache, checks that public fields still match, and rejects superseded responses. It does not change the profile. Source place keys still own photo requests, time periods, and life stages. A pin click selects the corresponding source place's photos. A city choice selects a member of that city group, including when the city was discovered by the provider and has no separate saved source entry.

City map choices replace child location choices. Resolved children determine the map frame and replace the parent centre pin. Unresolved children remain named with a pending label, without invented map positions. Membership checks are detached promises outside the agent turn stream; neither map grouping nor photographs delay text delivery.

Photo display prefers embeddable results for the selected source place and
requested period. If none are available, it shows saved group-member photos,
preferring the city's records and the same period. Existing photos remain visible
while a child search runs or returns no match or an error. Broader references
keep their original dates and source-place captions; a display-only
`reference_place` label never copies city photos into the child's saved record.
Retry and pagination continue to target the selected child. When its own photos
arrive, they replace the broader fallback in the gallery without deleting it
from the city's history. Other city groups are excluded from this fallback.

Implementation: `apps/api/place_groups.py`, `apps/api/place_geocoding.py`, `apps/web/client/memoir/places.mjs`, and `apps/web/client/memoir/client.js`. No database migration or model prompt extension is required.
