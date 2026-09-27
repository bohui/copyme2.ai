# Place-journey integration contract

The Memory Spark Codex runtime is deliberately configured without model tool execution. The place skill therefore communicates with the browser through a control marker in the model's text rather than by asking the model to call a shell, browser, or mapping tool.

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
`unchanged`; `changed` is true only when a new record was written. A client can
also hydrate the same record with `GET /v1/agent/place-journey`.

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
and optional OpenStreetMap link. Replacing a journey is safe; deleting a
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
