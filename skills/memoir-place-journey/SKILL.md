---
name: memoir-place-journey
description: This skill should be used by the integrated Memory Spark Codex worker when a storyteller explicitly mentions geographic places, recalls where a memory happened, or asks to revisit a location. Extract every distinct, coarse, user-grounded place and emit validated place-journey events for the Memoir workspace while keeping the visible reply gentle and concise.
---

# Memoir Place Journey

## Purpose

Turn every distinct place named in the current memoir message into a small, safe visual journey that the Memoir workspace can show beside the chat. Keep the storyteller's words authoritative: a place cue is a navigation aid and memory prompt, not proof of an address, identity, or life event.

## Trigger

Run this workflow only when the current storyteller message explicitly names or clearly connects a geographic place, such as a country, province/state, city, suburb, town, or named administrative district. Suburb/town is the finest supported level. The first journey marker must be grounded in words from that current storyteller message; a saved profile, prior journey, opening prompt, assistant reply, or private context alone cannot activate the workspace. Immediately relevant private context may help resolve a place the storyteller has already named, but it must not create a new place cue. Do not trigger from a place that appears only in a public historical reference or an unrelated source.

## Workflow

1. Read the current storyteller message first. Use only the smallest relevant private context needed to resolve a place already named in that message; never emit a marker for a generic opening or a saved place that the storyteller did not mention in the current turn.
2. Identify every distinct named public place in the message, including both ends of a move and places revisited later. Preserve the most detailed explicitly named administrative place, up to suburb/town level, for each: a message mentioning 大石庙镇 and 双桥区 needs two records, even when both belong to 承德. Repeated 大石庙 in that same account refers to 大石庙镇; use one record with its full name. Generic 市区, 家属院, 学校, 老家 and 河边 supply story context, not named geographic records. Treat a qualified location as one cue: 河北省承德市附属医院 yields only 承德市, with 河北省 in its hierarchy; Chengde, Hebei yields only Chengde. A separate province/country cue, such as later travel across Hebei, retains its own marker. For Chatswood station, emit Chatswood. Keep the hospital, school, street, building or compound detail in the story only. If no containing city, suburb or town is explicitly named, emit no marker. Include a reliably resolved containing city, region, and country in each hierarchy. Use `suburb` for named towns and urban districts. Emit only `country`, `region`, `city` or `suburb` granularity. Never turn an inferred street, building, or home into an exact map point.
3. Use hierarchy labels for geographic containment only, ordered from broad to the named administrative place. The first label is always the literal `Earth`, including in Chinese conversations; translate only the remaining labels. End with the exact source-script place name. Historical names, transliterations, and aliases refer to the same place, not extra administrative levels. Preserve the original wording in the visible reply.
4. Evaluate ambiguity separately for each place. When one mention has competing interpretations, is only implied, or would require guessing a private address, omit that place's marker and ask at most one short clarification question. Emit markers for the other clear places in the message. Several explicitly named locations are distinct places, not competing interpretations of one place.
5. Acknowledge clear places briefly and continue the memoir interview with at most one gentle follow-up question. Append one machine marker per distinct clear place, each on its own line, in first-mention order after the visible reply.
6. Use approximate coordinates for the named place or its administrative centre only. Treat coordinates as a camera target, never as evidence that the storyteller lived there. Omit the coordinate fields when they are not known reliably; the application searches the named place with its hierarchy and falls back to the nearest resolvable parent for the map. Keep the detailed place name even when only a parent has coordinates. Never assign parent coordinates to the detailed place.
7. Keep each new place as its own source record. The application invokes `memoir-place-groups` in the background for each preview and confirmed update: search city membership, add an independent pin to an existing city map when appropriate, or create a new city group. Do not wait for grouping before streaming the visible reply or emitting the journey. Each pin uses the administrative place centre; individual premises never become pins.

## Place-journey marker

Emit compact JSON between these exact delimiters:

```text
[[MEMORY_SPARK_PLACE_JOURNEY]]{"schema_version":1,"place":"Anshan","hierarchy":["Earth","China","Liaoning","Anshan"],"granularity":"city","latitude":41.1086,"longitude":122.9900,"duration_ms":5200}[[/MEMORY_SPARK_PLACE_JOURNEY]]
```

Required fields:

- `schema_version`: integer `1` for this marker contract.
- `place`: the user-grounded display name, up to 120 characters.
- `hierarchy`: ordered labels from `Earth` toward the place, with at most six labels.
- `granularity`: one of `country`, `region`, `city`, or `suburb`.

Optional fields:

- `latitude` and `longitude`: approximate place-centre coordinates, never a private address.
- `duration_ms`: a cinematic duration from 2800 to 9000 milliseconds; default to `5200`.

Do not put Markdown, commentary, raw chat text, private names, street addresses, or extra keys inside the marker. Emit no marker for an ambiguous place, a purely historical cue, or a place the storyteller did not provide.

The server adds `status`, `revision`, and `updated_at` after persistence. Do not
invent those fields in the marker.

## Safety and tone

- Keep the visible reply short enough to speak aloud.
- Say “approximate place” or equivalent when the journey uses coordinates.
- Never claim that a marker proves where the storyteller lived, worked, studied, or visited.
- Never infer trauma, health, politics, religion, identity, or family relationships from a place.
- Treat Google imagery as a current visual reference, never as historical evidence; do not send Google tile imagery or screenshots to Mira for image analysis.
- Let the storyteller correct, skip, or narrow the place before treating it as a stronger memory detail.

## Integration contract

The integrated runtime strips all markers from the assistant's visible reply, validates and grounds each independently, and persists accepted records through the storyteller's private place-journey row. It returns the turn's accepted records as `place_journeys`, the last record as `place_journey`, and a `place_journey_change` object with `created`, `updated`, or `unchanged` and the server revision. On later turns, the current saved record is supplied as untrusted context; emit markers only for places the storyteller explicitly names or corrects. The browser merges every accepted record into the project's place history and checks city membership for each. It can hydrate the current record with `GET /v1/agent/place-journey` only after the current Memoir project has been activated by an explicit place marker, and uses CesiumJS `Viewer` and `camera.flyTo` for the Earth-to-place transition. The application uses Google Geocoding for public-place search when coordinates are missing and Google 2D satellite imagery when a browser-restricted Map Tiles key is configured; the model does not need to call a map service. The closest resolvable parent supplies the map target if detailed lookup fails; the title and saved place remain detailed. The UI labels parent fallback, keeps Google attribution visible through the Cesium provider, and retains hierarchy-only display if no target or CesiumJS is available. Place history merges geographic duplicates across life stages, preserves photos and stages, and links child entries to saved parents. These records are durable navigation aids, not confirmed biographical evidence.

Load `references/contract.md` when changing the parser, API response, or workspace renderer.
