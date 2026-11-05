{{prompt:author_timeline}}

{{prompt:timeline_contract}}
This is the internal canonical event lane for every authorised accepted narrator
source, independently of premium display.
{{#events_only}}Return only {"events": [...]}
matching the supplied schema; empty extraction is a successful result.
{{/events_only}}{{#places}}Return {"events": [...], "place_journeys": [...]}
matching the supplied schema; empty arrays are valid.
{{/places}}{{prompt:timeline_grounding}}