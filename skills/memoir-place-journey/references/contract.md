# Place-journey integration contract

The Memory Spark Codex runtime is deliberately configured without model tool execution. The place skill therefore communicates with the browser through a control marker in the model's text rather than by asking the model to call a shell, browser, or mapping tool.

## Transport

The model appends one line in this form:

```text
[[MEMORY_SPARK_PLACE_JOURNEY]]<JSON>[[/MEMORY_SPARK_PLACE_JOURNEY]]
```

`apps/api/place_journey.py` extracts the first marker, parses JSON, validates the schema and bounds, and returns the visible reply with the marker removed. Invalid markers are dropped rather than shown to the storyteller.

The API response from `POST /v1/agent/turn` contains:

```json
{
  "reply": "The visible memoir reply.",
  "place_journey": {
    "place": "Anshan",
    "hierarchy": ["Earth", "China", "Liaoning", "Anshan"],
    "granularity": "city",
    "latitude": 41.1086,
    "longitude": 122.99,
    "duration_ms": 5200
  }
}
```

`place_journey` is `null` when no valid marker is present. It is ephemeral UI context and must not be inserted into the user's canonical memory as a confirmed biographical fact.

## Browser behavior

The browser keeps the most recent valid journey in local view state. Before the full workspace is unlocked, it shows a compact CesiumJS globe under the conversation. After unlock, the Places tab shows the same CesiumJS event with the hierarchy, approximate-place notice, and optional OpenStreetMap link. Replacing a journey is safe; deleting a journey is not a deletion of the user's memory.

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
