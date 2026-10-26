# GAME DESIGN — The Blue Gate

## Experience contract
Display “Fictional example”. English (Australia), hybrid, 3–5 minutes plus untimed reading. Control the unnamed eight-year-old author. Walk → approach → read → changed landmark → choose another branch. Borrow Night in the Woods’ side-on legibility and A Short Hike’s returns, not their stories. Offline native HTML/CSS/JavaScript; no network, storage, forms or runtime models.

## World and coverage
Display “Memory paths, not dates” at junctions. Hub posts: school x400, shed x800, outings x1200, garden x1840. Three branches enter at x80; exits at x80/x1840 restore their hub-post position. Completed guidance dims; revisits remain available. No resources, randomness or timers. State: scene, position, visited set, garden phase, overlay; camera derived.

| Internal coverage | Scene: position → contextual account |
|---|---|
| C1/T1 | hub:80 → move-in, family objects, school worry. |
| C2/T2; C3/T3; C4/T4; C9/T9 | school:400/800/1200/1600 respectively → first day with Dad; recurring reading/qualified praise; child classmate Sam/bottle tops/lunches/permission uncertainty; play/tree/sun cue/line said. |
| C5/T5 | shed:400 → repeated lessons, first lifted/later flat patch. |
| C6/T6; C7/T7; C8/T8 | outings:400/800/1200 respectively → market/list/coin search; library/Mum/Mr Lee/card/bird book; Grandma/two nights/Mum’s dry-drawings report. |
| C10/T10 | garden:400 → post-school beans/checks/next-morning opening/drawing. |

## Movement and accessibility
Every scene: width 1920 logical units, responsive 480-unit view, author-centre bounds [80,1840], speed 400 units/second. Camera = clamp(x−240,0,1440): scenery translates; author strides. Dialogue does not scale. Left/Right or A/D move; E/Enter interacts within 96 units; Escape closes reading. Interactions are edge-triggered. Touch buttons, including #left, #right and #interact, are ≥56px. Movement stops on release, cancellation, blur and overlays. Portals require interaction. Nearby prompts highlight; otherwise Interact is disabled. Reading pauses movement; visible focus, scrollable dialogue and focus restoration are mandatory. Reduced motion removes bob/easing, not travel.

## Progress, agency and ending
Closing an inspected memory changes its physical marker and adds unique credit; full-text viewing/revisits add none. Wrong turns cost walking only. Nine memories unlock garden: exploration, not chronology. Inspect garden for tenth credit; walk to exit x1840 and interact at “Next-morning memory”. Re-enter at x80, approach opened seedling x400 and interact: drawing tableau, “Journey complete — The Blue Gate”. Restart restores hub/80/camera0/count0/exploring, markers, overlays, held inputs, guidance and initial focus on #viewport.

## Reading boundary
Every memory interaction presents its complete unchanged source passage; all ten remain accessible throughout. Read host memoir-source JSON and display with textContent under place headings, never public chapter/timeline/source identities. Generic figures only; no invented testimony or missing book/play words. Keep quotation qualifiers, uncertain chronology, Sam’s uncertainty, unknown coin recovery and creek flooding. Practical activities stay contextual in this whitebox.

## Observable interface
#game exposes data-player-x, data-camera-x (rounded rendered positions), data-scene, data-count and data-phase. Initial: hub/80/0/0/exploring; #scene-name reads “Blue-gate junction”. Stable #viewport, #world, #player, #scene-name, #progress, #nearby, #dialogue, #close, #full-text, #restart; movement controls above. Visible location/progress mirror attributes.

## Executable whitebox and validation
Risk: real camera-following travel without tedious backtracking or implied chronology. Prototype the complete route in plain geometry. Planned replay (<70 steps), ordered assertion checkpoints: inspect hub; hold #right, value ArrowRight, 5000ms to x1840/camera1440 (input); travel to school, inspect first-day memory (coreLoop: school/count2); finish remaining memories and morning walk (outcome: complete/count10); restart (restart: initial state). Holds use movement buttons, 50–5000ms, never debug shortcuts. Browser checks: NOT_RUN. Revise if camera remains static, proximity misses, routes confuse, chronology is inferred or reset fails. Non-goals: combat, practical puzzles, skill-gated history.
