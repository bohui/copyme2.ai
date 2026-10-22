# Game generation specification

This specification records the GPT-6-authored approach supplied by the author.
The intended experience is a personal homepage expressed as a playable journey:
visitors learn about the author by exploring scenes and meeting NPCs.

## Product requirements

1. **Side-scrolling play.** Give the player direct control of a playable main
   character representing the author. Movement and interactions should work with
   keyboard and touch controls.
2. **Personal introduction through NPCs.** Use non-player characters to introduce
   the author's selected experiences, interests and values. Each encounter should
   contribute something meaningful to the introduction. Present dialogue as an
   adaptation from the author's perspective; factual claims about other people
   must remain supported and permitted.
3. **Privacy through adaptation.** Use author-approved memories as inspiration.
   Select, abstract, alias or omit details so the experience communicates the
   intended meaning without exposing sensitive private information. Review the
   complete combination of dialogue, scenery and identifying clues. A literal
   quotation is appropriate only when the author permits its disclosure.
4. **Multiple connected scenes.** Create distinct settings that contribute to the
   introduction. Make travel between them smooth, with predictable controls, safe
   arrival positions and consistent interaction state. Respect reduced-motion
   preferences. Choose the scene count to serve the story and current milestone.
5. **Reuse existing resources.** Consult suitable open-source projects, official
   examples and documented implementation experience before building game
   infrastructure. Evaluate fit, maintenance and license terms; retain required
   notices and record the origin and version of reused code and assets. Select an
   engine or asset pack when it improves the experience, rather than making one
   a prerequisite for every game.
6. **Develop by milestones.** Use the [acceptance milestones](acceptance.md) to
   define a concrete outcome and evidence for each stage. Start with a small
   playable loop, establish the personal introduction and scene travel, then
   expand after review. Optimize a measured problem after the relevant milestone
   works; measure the change against that baseline.

## Implementation boundary

The current runtime is an initial private adaptation: exactly two scenes and two
NPCs, exact source-backed quotations, generic scenery and a fixed browser
renderer. Its [runtime contract](runtime-contract.md) and
[privacy rules](privacy-and-grounding.md) govern what it can generate today.
These implementation limits describe the current milestone, not the full product
goal. Broader scene counts and reviewed abstractions require corresponding
changes to the proposal contract, validation, renderer and acceptance evidence.

“Personal homepage” describes the introduction experience. The existing private
adaptation permission does not authorize public publication; audience and sharing
must be decided explicitly before a public version is implemented or released.
