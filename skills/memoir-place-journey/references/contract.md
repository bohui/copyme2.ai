# Place-journey integration contract

The place skill communicates through a control marker. Geographic lookup is performed by the application through the project-owned `POST /v1/projects/{project_id}/place-map` endpoint; the model does not need to execute a mapping tool.

## Transport

The model appends one line in this form:

```text
[[MEMORY_SPARK_PLACE_JOURNEY]]<JSON>[[/MEMORY_SPARK_PLACE_JOURNEY]]
```

`apps/api/place_journey.py` extracts the first marker, parses JSON, validates the schema and bounds, and returns the visible reply with the marker removed. Invalid markers are dropped rather than shown to the storyteller.

The validated marker is persisted by the authenticated agent storage boundary in
the RLS-protected `user_place_journey` table. There is one current record per
storyteller; a changed place increments its server-owned `revision` and refreshes
`updated_at`. The browser must not treat the marker itself as durable state.

The API response from `POST /v1/agent/turn` contains:

```json
{
  "reply": "The visible memoir reply.",
  "place_journey": {
    "schema_version": 1,
    "status": "active",
    "revision": 2,
    "place": "Anshan",
    "hierarchy": ["Earth", "China", "Liaoning", "Anshan"],
    "granularity": "city",
    "latitude": 41.1086,
    "longitude": 122.99,
    "duration_ms": 5200,
    "updated_at": "2026-09-26T10:20:00Z"
  },
  "place_journey_change": {
    "changed": true,
    "kind": "updated",
    "revision": 2
  }
}
```

`place_journey` is the latest persisted record, even when the current turn did
not emit a marker. It is `null` when the storyteller has no saved place. The
optional `place_journey_change` object reports `created`, `updated`, or
`unchanged`; `changed` is true only when a new record was written. When the
current turn explicitly emitted the same already-saved place, `mentioned` is
true even though `changed` is false, so a new Memoir project can activate its
local workspace without inheriting an unmentioned place. A client can also
hydrate the same record with `GET /v1/agent/place-journey`.

The runtime drops a marker when its displayed place cannot be matched to the
current storyteller message. A saved profile or prior journey may help the
model understand a place the storyteller has just named, but it cannot activate
the workspace by itself.

The Codex prompt includes the current saved record as untrusted context. The
skill emits a replacement marker only when the storyteller explicitly names or
corrects a place; otherwise the existing record is returned unchanged.

## Browser behavior

The browser hydrates the current persisted journey only for a Memoir project
that has already been activated by an explicit place marker, and replaces it
from later turn responses. A saved user-level journey must not create a Places
surface in a fresh conversation. Before the full workspace is unlocked, it
shows a compact CesiumJS globe under the conversation. After unlock, the Places
tab shows the same CesiumJS event with the hierarchy, approximate-place notice,
and a Google Maps link. When configured, the Cesium surface uses Google 2D
satellite imagery and displays the provider credit; without a browser key it
keeps the globe and hierarchy fallback. Replacing a journey is safe; deleting a
journey is not a deletion of the user's memory.

## Example conversations

Clear:

```text
Storyteller: I grew up near Chatswood station.
```

Emit a journey for `Chatswood` at `suburb` granularity, with approximate centre coordinates if known. Do not use a station entrance as the storyteller's home.

Ambiguous:

```text
Storyteller: We lived by the river.
```

Ask which town or region they mean. Do not emit a marker.

Historical-only:

```text
Assistant context: A public photograph from Beijing in 1960 is available.
```

Do not emit a journey unless the storyteller independently connects their memory to Beijing.

## Place identity and map resolution

The browser merges saved places by normalized geographic hierarchy and name,
independently of life stage. It preserves the union of `life_stages` and `pictures`;
`parent_place_key` references the nearest saved ancestor. A city and its suburb
remain separate entries. Existing histories are normalized on hydration and on
new place events. Aliases are not guessed or merged across different hierarchies.

The place-map endpoint accepts the validated journey contract and returns
`status`, `target` (place, latitude, longitude, optional attribution), and `fallback`.
It uses reliable existing coordinates, otherwise searches the full public place
hierarchy from detailed place toward country. An unavailable provider still allows
saved parent coordinates. Parent coordinates belong only to `target`, never to
the child's persisted coordinates. No match leaves the hierarchy visible.

The default geocoder is Google Geocoding, with cached queries and serialized
requests. Set the server-only `GOOGLE_MAPS_GEOCODING_API_KEY` and, when a
compatible Google proxy is needed, override `GOOGLE_MAPS_GEOCODING_URL`. Set
the separately restricted `GOOGLE_MAPS_BROWSER_API_KEY` for Cesium's Google 2D
Tiles. Only geographic labels are sent, never memoir text. Google attribution
is supplied by the Cesium provider and the external map link.
