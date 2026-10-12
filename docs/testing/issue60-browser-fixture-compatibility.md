# Issue 60: recovery fixture compatibility evidence

## Retained limitation: round-five private-draft access

The requested opt-in private draft at round five is **not established by these
compatibility tests**. The current client hides an early private draft unless
`show_thinking_steps` is enabled. Ordinary saved-draft access appears in Chapters
after the free-recall threshold. That gate already exists in reviewed baseline
`cc068523`; baseline sameness does not waive the user-facing round-five
requirement. No production gate or phase behavior was changed here, and developer
mode was not enabled to make the tests pass.

The former mapped stage cases expected ordinary round-five draft access and
failed. Their replacements test an eligible paid round-20 state with developer
mode off. A replacement pass must not be reported as a pass for the original
round-five expectation. The separate round-five product-policy gap remains open.

## Place/readiness compatibility

The unmapped stage cases retain their Chengde cue and `NO_MATCH` response. They
now assert the current place/photo workspace remains available without a map,
with the life-stage strip and without prematurely showing Chapters or a private
draft. The mapped cases retain their coordinates and all red/amber/green readiness
assertions. The prior expectation that an unmapped cue hides the whole workspace
contradicted both baseline `workspaceContentAvailable` and the separately passed
`test_unmapped_place_keeps_places_and_photos_available_after_round_five`.

## Independently reproduced recall fixture failures

Calling the actual registered API handlers in the four authenticated recall-start
cases returned HTTP 200 `{}` for `/user/projects/recall-project/history?limit=100`.
Feeding those responses to unchanged `startMemoirStory` and
`hydrateAccountHistory` cleared the project and reported a history error, matching
the retained landing-page/send-button failures. The busy-history fixture also
returned `{}` and its legacy entries lacked project scope. These are distinct
from the stage visibility mismatches.

The corrected fixtures use owner/project-bound history, the real recovery
projection, explicit error responses, and source/client/server IDs matching each
acknowledged saved event. The busy-preview case restores its original legacy
memory from project-scoped history; only its guest opening is imported as a
scoped attachment. Raw aggregate account history is not re-enabled.

Actual browser reruns are still required after publication. Offline runtime-route
and client-function checks are evidence of fixture wiring, not browser passes.
