# One continuous chronological walk

Generate one RPG side-scrolling stream. The author walks forward to memories in
the supplied timeline order. Place later visits to the same place further along
the stream. Preserve uncertain dates and ordering within a life stage; the walk is
an editorial sequence through memories, not an invented dated itinerary.

The host owns the runtime, markup and replay. The model supplies a validated route
plan, art direction, scene illustration requests and a small styling layer. Build
outputs extend `game.css`; runtime changes belong in reviewed host code. This
keeps future generations in the requested format. Source passages stay unchanged.

At design, return `design/GAME_DESIGN.md` and `design/JOURNEY_PLAN.json`:

```json
{
  "version": 1,
  "blend": 180,
  "segments": [
    {"id": "arrival", "scene": "home", "title": "Home — the blue gate", "start": 0, "end": 1000},
    {"id": "school", "scene": "school", "title": "The new school", "start": 1000, "end": 2000}
  ],
  "stops": [
    {"chapter": "C1", "segment": "arrival", "x": 160},
    {"chapter": "C2", "segment": "school", "x": 1500}
  ]
}
```

Expand this shape to **every supplied chapter**, exactly once. Public `C1..Cn`
identifies each chapter by its position in the supplied chapter array; use the
timeline's `formal_chapter_id` to establish traversal order. The host validates
coverage/order, contiguous coordinates, unique IDs, segment lengths of 640–4000,
80–240 units of illustrated overlap, and at least 240 units between memory stops.
Stops sit at least 100 units inside their segment. Each segment serves a memory.
For a single-memory source, place its stop at least 640 units along the route so
the replay can demonstrate camera travel before reading it.
Scene IDs match the scene-art plan; reuse an ID when its artwork can be reused.
Split at life-stage or approved outfit changes, even if the location stays the same.

`journey.py` binds source age/life-stage to the reusable avatar family. Work
clothing and a profession label come only from host-approved
`source/character-profile.json`, keyed by public chapter ID, for example
`{"C8":{"outfit":"workwear","profession":"Carpenter"}}`. This is optional
owner input, outside model output paths. Use `casual`, `professional` or `workwear`;
when that outfit is unavailable at an age, retain its age-appropriate casual
avatar. A parent's occupation or an activity does not establish the author's job.
The fictional age-eight benchmark keeps its child avatar throughout.

The runtime provides a global increasing position/camera, forward keyboard/touch
input, proximity reading, reading pauses, progress, full source view, ending and
restart. It holds at the next unread memory, so a reader can keep moving forward
without needing to return for a missed passage. All places lie on that one path;
travel menus, hub returns, portals and coordinate resets do not belong in the plan.

Illustrations pan within a place and blend across the segment boundary as the
player walks. Match adjacent images' ground, perspective, scale and light. Reuse
the same illustrated strip for connected places such as market and library.
Keep the player, foreground baseline and camera continuous during transitions.
Reduced motion keeps forward travel and uses stable scenery with direct changes.

Verify actual positive progress across boundaries, overlapping images in normal
motion, age/outfit selection, all original passages, touch/keyboard, reading pause,
ending and complete restart. Generated plans and model text are not QA evidence.
