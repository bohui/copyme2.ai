# CopyMe2 Memoir Story Game — Review and Playability Plan

## Review conclusion

Build this as a source-grounded, chapter-based exploration game rather than an automatically generated open-world RPG. A completed chronological memoir should supply an evidence-linked story manifest; a constrained game compiler should turn that manifest into scenes; a trusted, fixed browser runtime should execute the scenes.

The original bundle is careful about authority and evidence, but its acceptance document explicitly identifies the playable runtime as unimplemented. Structural validation is not gameplay validation.

This document distinguishes findings recorded during the skill review from proposed implementation work. It does not certify production integration, real-device performance, legal rights, or the historical truth of personal recollections.

## 1. Findings to address

### P0 — Implement and test an actual runtime

The original acceptance milestones describe only a two-scene/two-NPC data fixture, not a functioning renderer. Add a small end-to-end implementation: chapter entry, movement or point-and-click navigation, an interaction, dialogue/reading, a visible outcome, travel to another scene, and a resumable exit.

A JSON scene package is an authored game description, not proof that someone can play it.

### P0 — Remove interview strategy as an access gate

Comfort, Explore and Shape are internal interviewing strategies. Neither game creation nor play access should depend on the current strategy. An automatic Lane B strategy change must not start a game, disclose an artifact, destroy a running game, or revoke access.

Keep the meaningful gates: authenticated actor, project/item access, eligible source edition, adaptation consent, permitted media, required review, and current publication/delivery authority.

Use separate adaptation-request and game-release state. Shape is not any of these.

### P1 — Make omissions visible

A review probe found that an otherwise completed chapter could be left out of the game without a coverage failure. The host must supply the complete selected, authorised chapter/event scope, independently of the candidate game.

Require an explicit disposition for every selected event and chapter. A missing record is an error, not an implied exclusion.

Distinguish full-memoir adaptation from an explicitly selected excerpt. An excerpt can legitimately omit chapters outside its declared scope; it cannot claim full-memoir coverage.

### P1 — Separate people from appearances

A review probe found that one person could not appear as an NPC in multiple scenes.

Use stable Person IDs and separate SceneActor instance IDs:

- person_father
- scene_school:actor_father
- scene_move:actor_father

All appearances resolve to the same authorised person, but positions, presentation, interaction state and supported age context belong to the scene instance. Unknown age stays unknown. Do not duplicate real people merely to satisfy scene-level uniqueness.

A father's own recollection must remain attributed to him; placing his avatar in a scene does not make it the storyteller's personal experience.

### P1 — Validate playability separately from schema validity

Add checks for graph reachability, safe spawn, reachable interactions, collision-free exits, valid completion conditions, keyboard/touch equivalence and recovery after a missing asset.

A valid scene can still be unplayable: its objective may reference a missing hotspot, a transition may lead nowhere, or a required photograph may no longer be permitted.

## 2. Product definition: exploration changes, biography does not

The player explores how to experience the memoir, not how to replace its historical facts.

Allow choices about which person, object, recording or location to inspect next. Do not let a gameplay choice change the canonical marriage, migration, school, occupation, relationship or outcome recorded by the memoir.

Core loop:

1. Enter a short scene associated with a real event or small cluster of related events.
2. Read or hear a brief source-backed introduction.
3. Explore one or more objects, people, photographs or recollections.
4. Receive a clear outcome: an unlocked passage, a listened-to memory, an explained connection or a chapter keepsake.
5. Continue, explore an optional branch, revisit a source or leave.
6. Save play progress separately from memoir evidence.

Keepsakes are interface achievements, not newly discovered biographical evidence. Avoid health/memory scores, punishment, timers and compulsory quizzes.

A chapter may contain several short scenes. The 7,000-word chapter ceiling is not an instruction to put 7,000 words on a game screen.

## 3. Scene templates for broad coverage

| Template | Appropriate material | Player action | Fallback |
|---|---|---|---|
| Place exploration | Home, school, workplace, neighbourhood | Inspect grounded objects and hear connected memories | Clearly labelled schematic setting; no exact coordinates required |
| Journey | Moving home, migration, travel, school journey | Visit supported stops and open recollections | A route diagram or transition cards, not an invented precise path |
| Everyday moment | Meal, game, hobby, routine, household task | Choose an object and reveal its story | An illustrated object gallery or text/audio cards |
| People and relationships | Family, friends, teachers, colleagues | Select whose attributed account or memory to hear | Person cards with unknown relationships preserved |
| Life transition | Starting work, leaving school, retirement | Explore before/after accounts and a supported turning point | A simple two-part story scene |
| Photo/document exploration | Family photograph, letter, diary, certificate | Open permitted details, captions or recordings | Text/audio version; no fabricated image replacement |
| Historical context | An independently sourced news event or period | Open an optional background panel | Omit external material while retaining personal testimony |
| Family archive | Infancy, inherited family anecdotes, another person's experiences | Explore a labelled family account | Attributed narration; not firsthand reenactment |
| Undated or sparse memory | Meaningful recollection without a firm date/place | Enter a memory room and inspect the available account | One short accessible scene; no invented date or location |
| Sensitive recollection | Bereavement, trauma, harm, disputed or private material | Choose whether to read/listen or skip | Narration-only, restricted or excluded according to policy |

These are reusable interaction templates, not mandatory categories every life must contain. Scene presentation and factual content are separate: a schematic can provide navigable geometry without claiming an authentic historical reconstruction.

## 4. Concrete memoir example

A canteen recollection might support a small scene called “The Canteen at Lunchtime”:

- Inspect the meal: reveal the storyteller's actual description.
- Inspect the large pot and ladle: reveal the remembered rice soup.
- Inspect a tree outside: reveal the separately described outdoor recollection.
- Open an eligible photograph if one exists.
- Continue after one discovery, or explore all available details.

Do not invent a school uniform, price, year, building plan, teacher's dialogue or emotional lesson. Do not substitute generic artwork for a real family photograph.

A private bathing recollection need not become an embodied simulation. A short optional narrated passage may represent it more appropriately. Animal-harm recollections must not become interactive harm challenges.

Corrections from the working sample should be regression assertions: skating at the Summer Resort must not become skating at the school playground; a friend's school must not become the storyteller's school; a father's skating account must not become the child's firsthand memory.

## 5. Composer-to-game handoff

Do not give the game skill only chapter prose. Extend the composer's structured output with a StoryManifest.

The manifest should include:

- Edition ID/revision and manuscript digest.
- Stable chapter IDs, title, chronology and reader-facing block references.
- Stable event IDs, evidence references and attributed speakers.
- Original time expressions, approximate ranges and source-supported ordering constraints.
- People and place references; unresolved identities remain unresolved.
- Eligible image/audio/document references and medium-specific permission decisions.
- Historical-context references in a separate namespace.
- Sensitive-content handling and authorised adaptation scope.
- Event/chapter disposition ledger.
- Source, rights, consent and policy revisions used to build the snapshot.

The compiler receives the selected scope from the host. It cannot make coverage look complete by dropping inconvenient events from its own denominator.

Pipeline:

Authorised sources
→ canonical events and source-linked chapters
→ frozen StoryManifest
→ coverage plan
→ template selection
→ scene graph
→ factual/editorial checks
→ deterministic playability checks
→ author adaptation review
→ immutable game release
→ permission-aware runtime.

If a change is required in the memoir itself, send a correction proposal upstream. The game compiler must not quietly rewrite the book.

## 6. Scene and interaction contract

A SceneDefinition should specify:

- stable scene_id and source chapter/event references;
- template_id and template version;
- setting, time label and attribution label;
- approved local asset references;
- SceneActor instances that reference stable Person IDs;
- source-backed text/audio blocks;
- hotspots and their accessible labels;
- explicit player actions and allowlisted progress effects;
- optional prerequisites;
- completion/skip rules;
- exits with valid destination IDs;
- reduced-motion and text-only representations;
- source/policy fingerprints.

Separate scene actors, hotspots, dialogue blocks and transitions. Avoid one global object ID namespace that treats multiple appearances of one person as duplicate identities.

Useful allowlisted actions include inspect_hotspot, open_photo, play_recording, read_passage, visit_scene, continue, back, skip and propose_correction. Effects may update play progress, open permitted content, or request a separately authorised application action.

Do not allow generated JavaScript, arbitrary HTML, unrestricted URLs, shell commands, payment operations or direct writes to memoir facts in a game manifest.

## 7. Coverage contract

Each selected event receives one primary disposition:

- interactive_scene;
- narrated_scene;
- montage_or_chapter_bridge;
- reference_only;
- excluded_by_author_or_policy;
- deferred_with_reason;
- needs_review.

Store primary scene references, optional supporting scene references and a machine-readable reason where required. Repeat references to one event do not increase coverage.

For a declared full adaptation:

1. Every eligible chapter has a representation or explicit reviewed disposition.
2. Every eligible event is accounted for.
3. All selected important events are reachable on the main path or a clear optional branch.
4. Unknown dates, absent photos and missing coordinates are not automatic exclusion grounds.
5. Sensitive events may be narration-only or intentionally excluded.
6. No count, title or exclusion reason leaks a private event to an unauthorised player.

Report separate measures:

- accounting completeness;
- narrative representation;
- interactive representation;
- critical-event representation;
- reachability;
- deferred/excluded content with permitted reasons.

“Everything accounted for” is not “everything playable.” “All scenes reachable” is not “all chapters represented.” An attractive percentage must not hide either distinction.

## 8. Graph and progression rules

Use a chronological main path for the supported sequence, with optional local branches that return to it. Honour partial ordering when exact dates are unknown. Do not claim chronology merely from chat order.

A scene must have a reachable continue or skip action even when optional media fails. A sensitive scene must not be required to unlock the rest of a person's life.

Require:

- a valid entry scene;
- no missing transition target;
- a reachable completion/exit state;
- no accidental dead end;
- no objective that can become impossible after a missing asset;
- safe spawn and movement bounds;
- every required interaction reachable;
- explicit handling of revisits and replay;
- choice state separate from original event data.

Intentional loops are acceptable for revisiting; they must not trap the player. Do not require every optional hotspot to complete a chapter.

## 9. Runtime and access

Keep a fixed trusted browser renderer. The original package envisages Phaser; the central decision is declarative scene data, not an unbounded choice of engines.

Use semantic DOM controls for menus, dialogue, evidence panels and the accessible reading alternative. Canvas alone should not be the only interface.

Load optional maps and richer graphics progressively. The main play loop should continue with locally available approved assets or text/audio fallbacks. Avoid live model calls on movement or ordinary dialogue clicks.

Separate creator-review and player audiences. Creators can propose corrections and review provenance. Family readers can explore only material explicitly shared with them. Play progress does not grant access to source recordings or other projects.

The game adaptation is a separate durable workflow. Lane B may request or prepare an authorised adaptation job, but large compilation, image processing and chapter updates must not block Lane A's interview response or the small next-question plan.

## 10. Progressive updates and saved games

Freeze each released game against a precise story/asset/policy snapshot. New memories create a draft adaptation revision, not a silent mutation of an approved release.

Maintain stable scene IDs around event identity and template purpose, not title or display position. Preserve unchanged scenes and personal edits.

For changed scenes, maintain lineage so progress migration can distinguish:

- cosmetic changes: retain completion;
- substantive new content: show new material as unvisited;
- split/merged scenes: map prior progress explicitly;
- revoked content: block access and remove dependent delivery;
- stale source references: rebuild or withhold.

Recheck authorisation at delivery and before serving restricted assets. A running client should remove content it is no longer authorised to receive, without promising to erase prior downloads.

A conversation strategy change alone never resets the game.

## 11. Verification plan

### Contract and compiler checks

Test omitted chapters/events, duplicate identities versus repeat actor instances, mismatched source revisions, unsupported chronology, invalid rights, fabricated quotations, source-role confusion and explicit adaptation scope.

Test missing assets, disconnected graphs, loops without exits, objectives with missing dependencies, unreachable hotspots, unsafe spawn and replay idempotency.

Test revisions arriving out of order, correction during build, consent withdrawal before release and deletion during a running task.

### Browser checks

Test a complete main-path playthrough, optional branches, back/next, skip, replay and saved-game restoration.

Exercise keyboard, mouse and touch-style input; keyboard-only dialogue controls; focus return; reduced motion; a text-only route; resizing; interrupted media; offline/missing assets; and clean unmount/remount.

Check that pointer capture, animation frames, timers, listeners and canvases do not accumulate after repeated mount/unmount.

Desktop touch emulation is not a physical-phone performance measurement. Automated browser interaction is not a full accessibility or visual-design certification.

### Editorial checks

Every factual line must resolve to the right source and speaker. Source links alone do not establish entailment.

Check the sample's corrections, uncertain dates, family-attributed accounts, privacy restrictions, no-photo scenes and short later-life sections.

## 12. Delivery sequence

1. Correct the authority contract: remove Shape access gating without weakening edition/consent checks.
2. Add StoryManifest, event/chapter coverage accounting and repeat-person scene instances.
3. Build one real two-scene runtime with a meaningful interaction, transition, skip and text alternative.
4. Add reusable scene templates and compile a representative mixed-coverage sample.
5. Add versioned release, progress migration, stale-write and revocation handling.
6. Complete browser/device/editorial testing before making a production-playability claim.

A useful first release is a coherent playable journey through selected representative chapters, clearly labelled as a sample, rather than hundreds of generated locations with no meaningful actions.

## 13. Evidence status

The original acceptance document explicitly states that no playable-runtime milestone has passed. Earlier work in this conversation reported 55 original composer tests and 46 original game-contract tests, followed by 82 composer and 70 game/compiler checks for the enhanced work.

The working example was described as eight short Chinese chapters, 29 identified events and 15 connected scenes, with four events represented through narration rather than reenactment.

Those reported counts are not a substitute for the corresponding saved logs or browser sign-off. This review document does not claim a completed physical-device, production-integration, or final browser acceptance campaign.

## Reference anchors

- Original game bundle: acceptance.md, “Acceptance milestones” and “Runtime checks for later implementation.”
- Composer v1.0.0: SKILL.md sections 2–4 (authority, evidence and chronological outline), 6 (photos), 7 (7,000-word ceiling), 8–10 (progressive updates, event dispositions and completion).
- Updated product decision in this conversation: Comfort/Explore/Shape are internal interviewing strategies selected by the background planner, not artifact-access or publication permissions.

## Final recommendation

Keep the evidence and permission safeguards, remove interview-mode gating, add complete event accounting and repeated character appearances, and invest next in a fixed, accessible runtime with a small reusable scene grammar.

The goal is not to re-enact every sentence. It is to let every important, eligible memory have an honest place in a connected experience that a person can actually explore.
