# GAME_DESIGN — A Patch That Stays

## 1. Experience contract
System-led close-up repair puzzle; signature_command: N/A. As the narrator, revisit Dad’s lesson in explicitly labelled game exercises, never additional Saturdays. Observe → infer → mark → prepare → press → test → revise. Implement workspace entry, goal, manipulation and retesting; omit walking/inventory/economies: one workspace, not a life simulation.

## 2. Rules and state
Deterministic, untimed. State: screen/exercise, selection, observations per region (0–2), mark, preparation (0–2), pressed/tested flags, result, total tests and fault history. Remembered facts never mutate.

Game-only layouts, left/middle/right: guided = clear/persistent/transient; independent = persistent/transient/clear. First Observe: bubbles on persistent/transient regions, none on clear. Second: persistent returns; transient clears. Types stay hidden; observations supply evidence and the visible legend explains it. Two Wait turns reach visible readiness: invented turns, not actual drying times.

| Action | Prerequisite → effect |
|---|---|
| Select/Observe | Before glue: select region; Observe advances evidence, capped at 2. |
| Mark/Glue | Unglued: Mark requires selected, observed region; replaces chalk mark. Glue requires mark; locks location, preparation=0. |
| Wait/Press | Glued, unpressed: Wait increments preparation, capped at 2; Press freezes it. |
| Test | Pressed, untested: count test. Wrong location: leak; preparation<2: curling; both: both faults. Otherwise flat/sealed. |
| Retry | Failed test: clear selection/mark/preparation/pressed/tested/result; retain observations and totals/history. |
| Continue | Flat: guided→fresh independent retaining totals/history; independent→ending. |

## 3. Decisions and pacing
Compare regions and choose when to press; no highlighted answer or mandatory failure. Changing leak position defeats copying the guided location. Target 3–5 minutes: opening, guided investigation, independent transfer, closure; no timed padding.

## 4. Feedback, ending, reset
Inputs update visible evidence/marks/readiness/patch plus persistent readable feedback. Unavailable controls explain prerequisites. Failures explain actual faults. Ending: “Practice complete — two flat patches”, showing test count and only encountered faults, never a life grade. Initial: title and Start, exercises untouched. Restart restores that screen, closes memory and clears all mutable state.

## 5. Narrative allocation
Presentation order is not chronology; no new dialogue or private knowledge.

| Source units | Treatment |
|---|---|
| C1–2 | Opening context: rental and Dad’s first-day walk. |
| C3/C9 | Help context: cardboard guide and painted-sun cue; no invented book/script words. |
| C4/C6–7 | Between-exercise context: companionship, useful list, library; coin recovery stays unknown. |
| C5 | Gameplay anchor; fixed remembered first-lift/eventual-flat outcomes remain visible regardless of practice. |
| C8/C10 | Closing context: Mum’s report, opened seedling and later drawing; never repair rewards. |

## 6. Language/access
English (Australia), first-person recollection. Display “Fictional example” and persistent “Game practice”. Preserve uncertainty, including praise if quoted. All ten unchanged passages remain accessible without private provenance. Keyboard, pointer and touch reach every action; visible focus, legible reflow and reduced motion are required.

## 7. Executable whitebox/UI contract
Stable surfaces: #intro/#workspace/#ending/#feedback/#memory. Controls: data-action=start|observe|mark|glue|wait|press|test|retry|continue|restart|memory-open|memory-close. Regions: data-zone=left|middle|right. Root: data-screen=intro|practice|outcome; data-exercise=guided|independent. Styling preserves hooks. Memory preserves state and restores opening-control focus.

Replay: Start; select Middle, Observe×2, Mark/Glue/Press/Test → curl. Retry; select Middle, Mark/Glue/Wait×2/Press/Test → flat. Continue; select Middle, Observe×2, Mark/Glue/Wait×2/Press/Test → leak. Retry; select Left, Observe×2, Mark/Glue/Wait×2/Press/Test → flat. Continue → ending (four tests; curl/leak recorded); Restart → intro.

## 8. Validation
NOT_RUN. Largest risk: rote sequencing. Host checks timing, fault comprehension, history/practice separation, complete text and keyboard/pointer/touch paths. Revise if blind location-copy succeeds, inspection seems irrelevant, or prerequisite feedback fails. Non-goals: repair physics, ten scenes, altered biography.
