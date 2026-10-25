# Product brief — Age Eight

## Product decision
- **Mode:** quick. This handoff completes intake and full-source analysis only; no game direction has been selected.
- **Deliverable:** one complete, original, self-contained browser-game prototype for private Memoir hosting. Export as `build/app/index.html`, with inline CSS, JavaScript and SVG.
- **Source:** the complete fictional age-eight benchmark: ten composer chapters and ten linked canonical timeline entries. The game must identify itself as a **fictional example**.
- **Language:** English (Australia), retaining the retrospective first-person narrator and source terms such as Mum, tyre and practised.
- **targetFinish:** playable-prototype.
- **experienceProfile:** provisional hybrid, to be confirmed by concept selection. Game form remains open; the source must determine it.
- **Audience:** general readers, including people with little gaming experience. Gentle treatment of childhood worry, temporary displacement and learning; no added threat, diagnosis or adult content.
- **Session:** single player; one complete 3–5 minute main path. Reading, optional full-text access and retries remain untimed and may extend the session.
- **Core promise:** participate in attention, exploration or practice around things the narrator remembers doing, while leaving the remembered life unchanged. Small achievements must arise from understandable player actions, not merely advancing passages.

## Platform and implementation boundaries
| Dimension | Requirement |
|---|---|
| Production runtime | Native HTML/CSS/JavaScript in modern desktop and phone browsers; no engine, framework or build dependency |
| Delivery | Offline webpage suitable for private Memoir embedding/hosting; no publishing or deployment work |
| Display | Responsive portrait and landscape layouts; design targets 360 × 800 phone and 1280 × 720 desktop, with usable reflow at 320 CSS pixels wide |
| Inputs | Desktop keyboard and pointer, plus phone touch; the complete path must work through ordinary buttons/choices without dragging or timed precision |
| Accessibility | Semantic controls, visible keyboard focus, legible body text, adequate contrast, generous touch targets, reduced-motion support and no essential animation or sound |
| Reading | Readable first-person memory passages and an accessible complete-text view containing all ten original chapter passages, including their uncertainty statements |
| State | Deterministic local rules; no runtime model requests, randomness-dependent outcomes or persistent saving |
| Assets | Original inline CSS/SVG shapes and system fonts only; incidental design inventions must not masquerade as remembered facts |
| End and reset | An observable designed ending and a restart that restores the declared initial screen and all game state |
| Text safety | Insert source passages with `textContent`; keep source IDs and internal provenance outside the player-facing game |
| Network and APIs | No remote requests, libraries, external links, navigation, forms, downloads, frames, service workers, workers, storage or device APIs |
| Audio | Not required; no voice production. All necessary information must be available visually and as text |

## Memoir adaptation contract
1. Supported events, relationships, quotations, explicit unknowns and chronology are fixed. Retain the narrator's perspective, including the difference between witnessing something and being told about it.
2. Player variation may affect attention, exploration order, practice, retries and mastery of a supported activity. It must be presented as game activity, not newly asserted autobiography.
3. Historical outcomes remain fixed: the remembered first patch lifts; a later patch stays flat; the school line is eventually said; the seedling opens the next morning. The dropped coin's recovery remains unknown.
4. Do not manufacture precise dates, the house number, market location, stallholder name, book or play titles, the play's line, diagnoses, motives, testimony or later biographical consequences. Do not say the creek flooded.
5. If the remembered teacher wording is quoted, its uncertainty must be visible alongside it: the narrator cannot promise that ‘You kept going’ is exact.
6. Do not turn uncertain event ordering into a dated itinerary. An exploration sequence is not evidence that events happened in that sequence.
7. The timeline supplies stage, recurrence, relative precision and source links; the chapters supply narrative evidence. Preserve any difference in specificity as uncertainty rather than silently resolving it.
8. This fixture is wholly fictional. Preserve the source's statement about Sam in the complete text, but do not invent a real-person permissions decision or build approval controls.

## Direction still to be decided
Concept selection must compare meaningful alternatives using the full source, not a preselected scene pool. Candidate material includes supported reading assistance, observing and patching a tyre, handling a market list, noticing a stage cue and watching a seedling. These are evidence-backed action possibilities, not selected scenes. Every timeline event must subsequently receive an explicit playable, contextual or omitted treatment with a reason.

## Budget, verification and ownership
- Budget: three generation passes—intake/analysis; concept/design/whitebox; art/production—with at most two repair passes. Each pass is capped at 24,000 tokens including reasoning. Only the host's measured usage establishes consumption.
- Use the seven supplied upstream skills as separate stage contracts. Memoir's adapter supplies the factual, delivery and verification overrides; it does not modify or merge the skill bundle.
- The harness controls model configuration and browser execution. Stage ownership changes within the same model session; no model switch is part of this plan.
- Target runtime: desktop and phone browsers. Tested runtime: not yet established by host observations.
- A whitebox must expose the largest design risk before art production. Production requires a complete ordinary-input playthrough description for host verification.
- Only host observations may establish QA status. No runnable candidate or QA conclusion belongs to this intake/analysis handoff.

## Explicit non-goals
No whole-life simulation, altered historical outcomes, invented child dialogue, inferred diagnoses, competitive timers, drag-only tasks, remote assets, live generation, accounts, saving, sharing, publishing, provider sign-in or production writes. Memoir retains authentication, access, private saving and sharing. The existing higgsfield-websites implementation remains an untouched manual comparison/backup option; this evaluation does not replace any saved private game.

## Unconfirmed assumptions and blockers
- The 3–5 minute target applies to the main game path, not reading all ten chapters in the optional complete-text view.
- Baseline browser and assistive-technology versions are not supplied. Device-specific coverage must be reported from actual host checks, not inferred from responsive code.
- Visual identity, game form and final event allocation remain open for concept/design.
- **Blocking intake questions: none.** The fictional fixture and explicit delivery constraints permit quick-mode analysis to proceed.
