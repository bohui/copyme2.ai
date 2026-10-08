# Place-journey integration contract

The place skill communicates through a control marker. Geographic lookup is performed by the application through the project-owned `POST /v1/projects/{project_id}/place-map` endpoint; the model does not need to execute a mapping tool.

## Transport

The model appends one line per distinct clear place, in first-mention order, in this form:

```text
[[MEMORY_SPARK_PLACE_JOURNEY]]<JSON>[[/MEMORY_SPARK_PLACE_JOURNEY]]
```

`apps/api/place_journey.py` extracts every marker, parses JSON, validates each schema and bounds, deduplicates geographic identities, and returns the visible reply with all markers removed. The parser normalizes Chinese `地球` to canonical `Earth`. Accepted precision is country, region, city or named suburb/town; landmarks, premises and generic labels are rejected even if mislabelled as a suburb. Invalid and unterminated markers are dropped rather than shown to the storyteller; a bad marker does not discard later valid markers. Each accepted place must independently match the current storyteller message. The single-place extraction helper remains available for compatibility.

Before persistence, the runtime also normalizes qualified place cues against the
current message. A `country` or `region` marker that only qualifies an accepted
descendant (河北省承德市 or Chengde, Hebei) stays in that descendant's hierarchy,
not as another record. A separate occurrence or narrative cue retains the broad
record; standalone provinces and independent city/suburb records remain valid.
Uncertain relationships are preserved rather than guessed. This rule applies to
both legacy collector markers and dedicated workspace extraction, and therefore
to saved records, confirmed workspace events, and the final API response.

The validated marker is persisted by the authenticated agent storage boundary in
the RLS-protected `user_place_journey` table. There is one current record per
storyteller; accepted places are persisted in order, and the last one remains
current. A changed place increments its server-owned `revision` and refreshes
`updated_at`. The browser stores all accepted records in project `memory_places`.
The browser must not treat a streamed preview as durable state.

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

When the current extraction explicitly ties a calendar period to a place, its confirmed record also carries `period` for project photo research. Other places in the same turn receive an empty period for current photos; the profile’s date must not date unrelated places. The user-level journey row keeps geographic fields only; project history retains the photo period.

Each confirmed record also carries a server-assigned `life_stage`, using the
seven supported stages or `null` when the association is unknown. The runtime
attaches the current extraction's stage to the unique place matched by
`story_focus.where`. A single-place continuation can retain the response's
stage when the focus omits `where`; mixed-place turns with missing or ambiguous
focus locations remain unplaced. For “现在生活在悉尼，但是我出生在承德市”,
a birth focus in 承德市 assigns `baby` to 承德市 and `null` to 悉尼.

The same per-place assignment appears in the first confirmed workspace event,
the final event, and the turn response, including place-only events that arrive
before profile updates. The browser consumes these fields directly and stores
them in project `memory_places`. The user-level journey row remains geographic;
model markers and previews supply no stage assignment.

The response and confirmed workspace events also contain `place_journeys`, an
array of all accepted records from this turn in marker order. It is empty when
there are no accepted markers or the turn is stale. `place_journey` and
`place_journey_change` remain the last record and its change for existing clients.
Streaming extraction emits a `place_preview` for each complete grounded city or
suburb marker without waiting for the remaining markers or the visible reply to
finish. Country and region previews wait for the complete extraction so the same
normalization can exclude a broad qualifier,
even when its marker arrives before the descendant's. Previews never persist data.

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
skill emits markers only for places the storyteller explicitly names or
corrects; otherwise the existing record is returned unchanged.

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

Multiple places:

```text
Storyteller: 原来学校的家属院在大石庙镇，后来搬到了市区双桥区。每到放假我都回大石庙找小伙伴们玩。
```

Emit separate `suburb` journeys for `大石庙镇` and `双桥区`, each with its
resolved containing-city hierarchy. Use the original full town name for repeat
mentions of `大石庙`; generic `市区` does not create a third location. Both source
records join the 承德 city map after membership resolution, with their own pins
when resolved. A containing city present only in context is a hierarchy label,
not an additional marker. If another mention is ambiguous, omit only that marker.

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
remain separate source entries, with distinct photos and life stages, but appear
as one city map with independent child pins. The `memoir-place-groups` background
service checks each new mention for membership and either adds its pin to an
existing city group or creates another group. Its contract is in
`skills/memoir-place-groups/references/contract.md`. Existing histories are normalized on hydration and on
new place events. Aliases are not guessed or merged across different hierarchies.

Within the same complete hierarchy, the optional Chinese administrative suffixes
`市` and `省` are normalized for identity: 承德/承德市 and 河北/河北省 match.
The backend uses this identity for saved-map lookup and repeat-journey updates;
the browser uses the same rule when merging restored history. Original source
labels remain available, and existing coordinates, photos and life stages survive
a repeat mention that omits coordinates. County, district and town suffixes are
not interchangeable with a city, and different containing regions stay distinct.

The existing extraction call includes compact geographic hints from the latest
saved journey and up to 50 available profile history entries, without photo
metadata. It must still emit a currently mentioned repeat using the current
message's wording. Deterministic identity matching follows extraction; there is
no additional model call for administrative-suffix deduplication.
Multiple currently grounded aliases of the same identity are collapsed before
persistence, retaining known coordinates and the latest grounded source label.

The place-map endpoint accepts the validated journey contract and returns
`status`, `target` (place, latitude, longitude, optional attribution), and `fallback`.
It uses reliable existing coordinates, otherwise searches the full public place
hierarchy from detailed place toward country. An unavailable provider still allows
saved parent coordinates. Parent coordinates belong only to `target`, never to
the child's persisted coordinates. No match leaves the hierarchy visible.

After an explicit location trigger, the project workspace stays available through
unresolved maps, pending photos and private draft checkpoints. Before composition
unlock it retains location and photo panes; after unlock it uses the enabled
composition tabs. Manual collapse remains available. A fifth-round private draft
checkpoint alone does not unlock composition tabs or hide the media workspace.

The default geocoder is Google Geocoding, with cached queries and serialized
requests. Set the server-only `GOOGLE_MAPS_GEOCODING_API_KEY` and, when a
compatible Google proxy is needed, override `GOOGLE_MAPS_GEOCODING_URL`. Set
the separately restricted `GOOGLE_MAPS_BROWSER_API_KEY` for Cesium's Google 2D
Tiles. Only geographic labels are sent, never memoir text. Google attribution
is supplied by the Cesium provider and the external map link.
