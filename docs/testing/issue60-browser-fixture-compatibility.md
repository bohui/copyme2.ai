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

## Navigation interactions after scoped-history repair

The exact `7a9b5b5f` Mac run passed 16 of 38 navigation cases, with 22 failures
and no skips. The captured history responses were valid HTTP 200, project-scoped
empty snapshots. Those failures are separate from the repaired history DTO:

- Six self-start timeouts followed a redundant second start action. Platform
  Begin already starts/resumes self. Two family-start timeouts also used Begin,
  which does not open the self/family chooser. This entry behavior exists in
  baseline `cc068523`.
- Nine cases found the garden narration in the DOM but hidden. Recovery begins
  with collapsed history. Background readiness/private-draft renders can expose
  the composer before the history toggle exists, so the old immediate
  `toggle.count()` check could skip expansion. The corrected helper waits for
  the real toggle and verifies expansion before the original narration check.
- Five detached-stream cases captured B's cache before its ordinary greeting
  started: `null` then became `[]` for the empty streaming placeholder. Unchanged
  `streamAssistantMessage` and `persistChatHistory` reproduce this transition
  without any late packet. The test now waits for B's completed greeting, requires
  a nonempty assistant-only cache, then retains exact byte-for-byte equality
  after delivering the adversarial packet. The unchanged canonical-ledger,
  abort/cancel, hidden late-reply/error, and A/B recovery assertions remain.

Family navigation uses a real `page.goto('/memoir')` after the platform visit and
then its family button. Unchanged `startMemoirStory` and `navigateTo` prove that
only the chooser entry is replaced, leaving `[interview A, platform, interview B]`
for the original Back/Forward assertions. No test-side history mutation is added.

The offline interaction tests execute the actual registered route and unchanged
client rendering/start/cache functions. Controlled locators reproduce delayed
paint and available entry controls; they do not establish browser execution or
replace the original UI/privacy assertions. The exact Mac navigation rerun is
still required. The round-five policy gap documented above remains open.

## Authenticated initial-entry fixture ordering

The exact `197ecb8`/`b4d55860` Mac navigation run passed 36 of 38 cases, with no
skips. Only the phone/desktop authenticated reentry cases timed out on their
initial self-start button. Their empty project/history request ledger did not
establish that config or Auth requests were absent; that ledger records only
project and history routes.

The scenario installed its principal override as a separate page init script.
Playwright does not guarantee ordering between page and context init scripts.
Executing the actual scripts in context-first order reproduced a guest SDK cookie
alongside the account fixture principal. The actual Auth fixture rejected both
preference RPCs with 401. With the installed Supabase SDK and unchanged
`boot`/`ensureAuth`/preference code, the page rendered
`UI preference could not be saved` instead of its start button. Reverse order and
both anonymous orders passed. These 401s are offline reproduction evidence, not
captured Mac responses.

The fixture now selects its validated initial principal in the same script that
seeds the SDK cookie. Intentional account-switch overrides still update both the
session and cookie. The reentry case retains all original assertions and adds an
explicit project-owner UUID assertion. Auth and expected-viewer failures stay
strict. The actual Mac rerun remains required.

## Inherited product races found after fixture repair

The exact `f429e337`/`f3c0922a` Mac navigation run passed 33 of 38 cases, with
no skips. Its retained response bodies establish two different same-owner self
projects and wrong reentry URLs; the three login traces establish a detached
menu item followed by a hidden replacement. No request bodies, saved pointers,
transport/click timestamps, or screenshots of these failures were retained.
Those gaps do not establish the precise historical callback schedule.

Independent deterministic reproductions used unchanged current and `cc068523`
client code. Both reproduced these inherited defects:

- The real locale-change callback can render platform Begin while saved-project
  recovery has only `{id: A}`. Begin awaited Auth but not project recovery and
  could allocate B. A controlled response barrier, the installed Supabase SDK,
  real fixture Auth handlers and real project TestClient routes reproduced the
  second HTTP 201 for both anonymous and authenticated principals.
- A normal greeting/readiness/private-draft repaint rebuilt an open profile
  dropdown as hidden, replacing the pending login target and losing focus.

The authorized product fix fences start admission behind current project/history
recovery, coalesces repeated Begin, and checks navigation, owner, session and
logout state after the wait. Recovery finishes before opening-copy streaming;
failed or denied saved-self recovery does not allocate a replacement. Cold
starts and intentional family-project creation retain their separate behavior.
Profile-menu intent and focus survive only same-scope story paints, and explicit
close, Escape, navigation, logout and principal/project changes discard them.
No original browser assertion was removed or delayed to hide either defect.

These changes affect production client code and require fresh source validation;
prior fixture-only tree equivalence is not evidence for this delta. The Mac went
offline before a rerun, so actual browser acceptance remains blocked until that
same machine reconnects. The round-five draft-access gap remains open.
