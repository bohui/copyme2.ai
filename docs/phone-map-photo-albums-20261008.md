# Phone map photo albums

Original base: `e6c06cafd5ad56f34b31edb8dd5e85dd7e96bc56`.
Integrated main: `c51ef44926f215382af30d116bf52318ceb534ca`
(tree `976b300755b7d00e70393ae7a18f4dbb0ddc0ac5`, verified PR #31 merge).
Task branch: `codex/phone-map-photo-albums-20261008`.

## Behavior

At widths up to 760 CSS pixels, the conversation header is 52 pixels high
without a device safe-area inset. The place workspace uses 44% of the available
conversation panel. The map fills that upper workspace, with the workspace
toggle and map link overlaid. The redundant visible `地点` and city heading are
hidden. The city remains in the map region's accessible name; album buttons and
the unresolved-pin legend retain accessible place names. Life stages become
44-pixel text controls instead of large portraits. Desktop headings, gallery,
life-stage artwork and marker selection retain their existing behavior.

Every resolved map pin has a 44-pixel marker target and an album button with up
to three permitted thumbnail images. Nearby album cards move apart and connect
to their actual pins with stems. If the map cannot fit them, a horizontally
scrollable tray keeps crowded albums reachable. The tray also exposes every
non-pin member of the active city group, including the parent city suppressed
by child pins and places with unresolved pins. Its controls are 44 pixels high
and it fits its contents. Albums remain available when the group has no pins;
no geographic marker is invented. Offscreen resolved pins hide their albums.
The surrounding canvas continues to handle map gestures. If Cesium is
unavailable, album buttons remain reachable over the existing map fallback.

Tapping a marker or album opens a native modal dialog with the corresponding
reference photographs. It reuses the existing source links, actual capture-date
captions, filtering and fallback labels. Searching, empty and unavailable
results remain distinct; retry and pagination controls work in the dialog.
Verified photos arriving during a search update both the open dialog and the
map stack. Closing, Escape and browser Back dismiss the album; Forward restores
it. Focus returns to the matching updated album after streamed results replace
the original thumbnail. The album history entry preserves the current URL and
existing history state, using only the `memoirPhotoAlbum` field.

No photo-search period, provider, backend, credentials, account settings,
deployment or model behavior changed. No time specified still produces an empty
`period` parameter for the existing present-day policy.

## TDD and validation

The new module tests first failed because the album implementation was absent.
The phone acceptance test failed against the original 67-pixel header. A new
streaming-focus assertion failed before its focus restoration fix.

Independent review of `9851764232456d3539fc4fc652ce32230c7be445` found that
collecting albums from resolved pins omitted the parent city's own pictures
and every unresolved-pin album. Two new JavaScript regressions first failed
because no independent group-member collector existed. Four new browser
cases then failed: two albums instead of three with child pins, and zero
instead of three for no-pin groups. The fix collects the active group's
members independently of pins and uses the compact tray for non-pin members.
The browser cases verify each city/child album's distinct source titles and
dates, plus empty/error/retry states without Cesium entities. An additional
no-pin loading case verifies streamed photos and focus restoration. The map
gesture assertion targets an actual canvas point outside the tray.

Further review of `05f4e8985f330a323f306c02ed18ba187aa69127` found two
interaction issues. Both first failed in Chromium: a pinned overflow album
lost Tab focus across six Cesium postRender frames, and a city-chip tap opened
the town album when its transparent marker projected behind the chip. The
fix leaves overflow anchors in their existing parent and raises the tray's
stacking priority above marker targets. The regressions exercise Tab/Enter,
real Cesium frames, `elementFromPoint`, touch tapping and exact album attribution.

Commands run from the task worktree:

```sh
node --test tests/js/*.test.mjs
python3 scripts/check_localization_catalog.py
MEMOIR_BROWSER_URL=http://127.0.0.1:19492 python3 -m pytest -q tests/test_phone_map_albums_browser.py
MEMOIR_BROWSER_URL=http://127.0.0.1:19492 python3 -m pytest -q tests/test_conversation_scroll_browser.py
cd apps/web && npm run build
```

- JavaScript: 176 passed.
- Localization: 544 messages valid in `en-AU` and `zh-CN`.
- Phone/map albums: 14 passed. Real Cesium camera, scene projection and picking;
  synthetic grid imagery, photos, auth and all API responses. No live photo,
  provider or model calls.
- Conversation/keyboard/scrolling and saved-draft cases: 4 passed, no deselection.
- Production Next.js build: passed with Turbopack after making a private local
  dependency copy. The initial external dependency symlink was rejected by
  Turbopack; no dependency or lockfile changes were needed.
- `git diff --check`: passed.

Phone checks include 390x844, 320x568, 430x932, 760x580 and 390x500;
desktop checks use 1440x960. They cover distinct overlapping albums, 44-pixel
marker/album targets, source dates, real marker picking, close/reopen,
Back/Forward, map dragging, empty/error/retry, streamed arrivals, focus,
present-day search defaults, viewport resizing, a retained Cesium viewer and
the desktop gallery. Existing conversation checks exercise keyboard-height
changes and streaming scroll behavior.

## Landed-main integration

Before PR #31 landed, `test_workspace_stays_reachable_without_page_scroll`
failed on this task and pristine `e6c06ca` at the missing private-draft status.
After merging verified main, it reached that status and passed its viewport
and inner-scrolling assertions, then failed at a nonexistent workspace toggle.
The test still assumed that a draft without an active map opens a workspace,
contrary to the existing JavaScript workspace policy. It is now named
`test_saved_draft_stays_reachable_without_page_scroll` and explicitly asserts
that the saved draft remains readable inside the conversation while the empty
map workspace and its toggle remain absent. Its viewport, content expansion,
inner scrolling and composer reachability assertions are retained. No
progressive runtime behavior was changed to satisfy the stale assertion.

Baseline reproduction used a separate task-owned frontend on port 19494 and
the pristine test from that archive. The server helper stopped it afterward.

Verified main merged cleanly at integration commit
`0eee92c9a068b0559d0e93a60e279600ed4c9bea`, with parents `dc73aae` and
`c51ef44`. Eleven navigation, account/history, progressive-draft and workspace
functions are byte-identical to landed main, including `navigateTo`,
`bindViewActions`, `bindProfileMenu`, `hydrateAccountHistory`,
`privateDraftPreview` and `workspaceHasContent`. The existing global popstate
listener is preserved. An additional browser case verifies phone workspace
collapse/reopen and album Back preserve the project URL, prior history state
and composer. Unmerged PR #33 was not imported or modified.

## Evidence and coordination

Validated local screenshots and test receipts are in the ignored directory
`output/phone-map-albums/`: `before-phone.png`, `after-phone.png`,
`after-phone-album.png`, `after-desktop.png`, `js-tests.txt`,
`browser-final.txt`, `conversation-tests.txt`, `baseline-regression.txt` and
`build-final.txt`. Screenshots show synthetic fixtures, not fetched archive
photos or real Google imagery.

Review-fix receipts: `js-city-tray.txt`, `browser-city-tray-final.txt`,
`conversation-city-tray.txt`, and `build-city-tray.txt`. New screenshots
`after-saved-all-albums.png` and `after-unresolved-all-albums.png` show all
three distinct group albums; the standard after screenshots are refreshed.

Interaction-review receipts: `overflow-review-red-confirmed.txt` (both
behavioral failures), `overflow-review-green.txt`, `browser-overflow-final.txt`,
`js-overflow.txt`, `conversation-overflow.txt`, and `build-overflow.txt`.
`after-short-phone-overflow.png` captures the compact overflow controls.

Integration receipts: `js-main-integration.txt`,
`browser-main-integration-final.txt`, `conversation-main-integration-first.txt`
(stale toggle assertion), `conversation-main-integration-final.txt`,
`workspace-route-main-integration.txt`, `build-main-integration.txt`, and
`shared-client-main-audit.json`. All after screenshots are refreshed from the
integrated branch; the original before screenshot is retained.

Library screenshot saving is blocked: the required current prepared-upload
helper reports `Library prepare_uploads is not available` on this Mac, before
creating upload sessions. No Library screenshot IDs were produced.

Shared `client.js` changes are confined to the album import/controller,
`renderStory` album synchronization, new `mapPhotoAlbum`/status helpers,
`lifeStageNavigator` phone labels, `placeJourneyMarkup` pin keys/accessibility,
and Cesium initialization/disposal/marker hooks. The new module owns its album
history listener; the existing global route listener, logo, home link,
`navigateTo`, account history and anonymous-history functions are untouched.
The original checkout remains unchanged and clean at
`ac6eb6bb0e531c5fda55809f53a744aeca60a82c`. The phone branch incorporates the
reviewed progressive changes through verified landed main only.

Independent cloud review and any required fixes remain pending. No deployment
or merge is authorized by this result.
