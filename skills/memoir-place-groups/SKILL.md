---
name: memoir-place-groups
description: Group memoir locations into city map views with independent public-place pins. Use in the integrated Memoir workspace whenever a place preview, saved place, correction, or restored history arrives; check whether each new place belongs to an existing city group or needs a new group. Run through the background application service without delaying conversation streaming.
---

# Memoir Place Groups

## Workflow

1. Keep every source location distinct, including its original name, life stages, dates, photographs, and history key. Group only the map presentation. Do not collapse a school or town into its parent city's biography.
2. Start the grouping check for every new place preview, confirmed place update, correction, and restored workspace. A single conversation may supply several `place_journeys`; include every accepted source record in the history and membership check. For 大石庙镇 and 双桥区, retain two members of the resolved 承德 city group. Resolve the newest mention first. Keep the conversation stream and immediate map preview independent of the check.
3. Match city membership using the supplied geographic hierarchy or public geocoder administrative components. A city boundary is the grouping criterion; nearby coordinates alone do not establish membership. Preserve region and country distinctions for cities sharing a name.
4. Add a matching location to the existing city group with its own pin. Create a separate group when it belongs to another city or membership remains unresolved. Keep a stable city group key as members arrive.
5. Show one city choice and frame its detailed map around the resolved child pins. For 承德 with 承德师范学校 and 大石庙镇, show one 承德 map with two child pins. New places within 承德 join this map; a place in another city receives another city choice.
6. Use only a place's own supplied coordinates or a non-partial public geocoding result for its pin. Never reuse a parent's coordinates as a child pin. Leave unresolved locations visibly pending while keeping the available map usable.
7. Treat public map results as current approximate references. A historical school name may refer to another campus; do not claim a present-day campus is its historical location. Do not infer private addresses.
8. Prefer the selected source place's photos for the requested period. While its search is pending, empty, or unavailable, keep saved photos from the same city group visible, preferring the saved city and matching period. For a later 大石庙镇 mention, show its photos when found; otherwise retain the earlier 承德 photos. Preserve photo ownership, dates, and attribution, and label the original source place on fallback captions. Keep retry and pagination attached to the selected source place.

## Runtime boundary

The browser invokes the authenticated project-owned `POST /v1/projects/{project_id}/place-groups` service in the background. The service deterministically groups public geographic fields and uses cached Google Geocoding metadata when necessary. It does not invoke another conversation model or modify saved profiles. The browser guards against results for another project or an older correction and keeps photo selection attached to the original source place.

This integrated skill needs no conversation marker. Do not ask the collector to wait for it or put grouping output into the visible reply. Read [references/contract.md](references/contract.md) when changing its service or map renderer.
