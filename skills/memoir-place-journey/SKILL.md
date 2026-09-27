---
name: memoir-place-journey
description: This skill should be used by the integrated Memory Spark Codex harness when a storyteller explicitly mentions a geographic place, recalls where a memory happened, or asks to revisit a location. Extract a coarse, user-grounded place and emit a validated place-journey event for the Memoir workspace while keeping the visible reply gentle and concise.
---

# Memoir Place Journey

## Purpose

Turn a place named in the current memoir conversation into a small, safe visual journey that the Memoir workspace can show beside the chat. Keep the storyteller's words authoritative: a place cue is a navigation aid and memory prompt, not proof of an address, identity, or life event.

## Trigger

Run this workflow only when the current storyteller message explicitly names or clearly connects a geographic place, such as a country, province/state, city, town, suburb, neighbourhood, school, station, or named landscape. The first journey marker must be grounded in words from that current storyteller message; a saved profile, prior journey, opening prompt, assistant reply, or private context alone cannot activate the workspace. Immediately relevant private context may help resolve a place the storyteller has already named, but it must not create a new place cue. Do not trigger from a place that appears only in a public historical reference or an unrelated source.

## Workflow

1. Read the current storyteller message first. Use only the smallest relevant private context needed to resolve a place already named in that message; never emit a marker for a generic opening or a saved place that the storyteller did not mention in the current turn.
2. Prefer the broadest place that preserves the memory thread. Use country, region, city, or suburb granularity; never turn an inferred street, building, or home into an exact map point.
3. Treat historical names, transliterations, nicknames, and modern aliases as separate labels in the hierarchy when the storyteller supplied them. Preserve the original wording in the visible reply.
4. If two places are plausible, if the place is only implied, or if resolving it would require guessing a private address, ask one short clarification question and do not emit a journey marker.
5. If the place is clear, acknowledge it briefly and continue the memoir interview with at most one gentle follow-up question. Append exactly one machine marker on its own line after the visible reply.
6. Use approximate coordinates for the named place or its administrative centre only. Treat coordinates as a camera target, never as evidence that the storyteller lived there. Omit the coordinate fields when they are not known reliably; the workspace can still show the hierarchy as a non-map journey.

## Place-journey marker

Emit compact JSON between these exact delimiters:

```text
[[MEMORY_SPARK_PLACE_JOURNEY]]{"schema_version":1,"place":"Anshan","hierarchy":["Earth","China","Liaoning","Anshan"],"granularity":"city","latitude":41.1086,"longitude":122.9900,"duration_ms":5200}[[/MEMORY_SPARK_PLACE_JOURNEY]]
```

Required fields:

- `schema_version`: integer `1` for this marker contract.
- `place`: the user-grounded display name, up to 120 characters.
- `hierarchy`: ordered labels from `Earth` toward the place, with at most six labels.
- `granularity`: one of `country`, `region`, `city`, `suburb`, or `landmark`.

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
- Let the storyteller correct, skip, or narrow the place before treating it as a stronger memory detail.

## Integration contract

The integrated harness strips the marker from the assistant's visible reply, validates it, and persists the validated record in the storyteller's private place-journey row. It returns the latest record as `place_journey` plus a `place_journey_change` object with `created`, `updated`, or `unchanged` and the server revision. On later turns, the current saved record is supplied as untrusted context; emit a replacement only when the storyteller explicitly names or corrects a place. The browser can hydrate the record with `GET /v1/agent/place-journey` only after the current Memoir project has been activated by an explicit place marker, and uses CesiumJS `Viewer` and `camera.flyTo` for the Earth-to-place transition, with a hierarchy-only fallback when CesiumJS or coordinates are unavailable. This record is a durable navigation aid, not confirmed biographical evidence.

Load `references/contract.md` when changing the parser, API response, or workspace renderer.
