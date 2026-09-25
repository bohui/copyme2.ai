# Profile dropdown design QA

## Comparison target

- Source visual truth: `/var/folders/0p/f6_3s_v55jl9_bcb6h4xby1h0000gn/T/codex-clipboard-607baf11-55e5-4ead-99bb-8a9c30c44c29.png`
- Implementation: `http://127.0.0.1:8000/memoir/start` in the Codex in-app browser.
- Implementation capture: inline in-app browser header crop, clipped to `776 x 163` CSS pixels at the default `1280 x 720` viewport; the browser surface does not expose a persistent local screenshot path.
- Source pixels: `776 x 163`; implementation crop: `776 x 163`; density normalization: none applied.
- State: Memoir story flow, round 1 of 5, anonymous Supabase test session; closed and open profile-menu states were both checked.

## Evidence

- Full-view comparison: the existing paper background, thin divider, muted Supabase status copy, and compact header rhythm remain consistent with the supplied reference. The previously added private-conversation pill is intentionally removed, and the requested profile control remains at the far right.
- Focused region comparison: the profile trigger uses the existing green/sage token system, rounded surfaces, small DM Sans labels, and a compact dropdown with an account summary and `Log out` action. The open menu remains anchored to the trigger at desktop and mobile widths.

## Findings

- No actionable P0, P1, or P2 visual findings remain.
- Initial mobile pass found the icon-only profile trigger lacked an accessible name after its text label collapsed. Added `aria-label="Open profile menu"`; the mobile accessibility tree now exposes the control correctly.

## Interaction checks

- Open and close the profile menu with the trigger.
- Close with click-outside.
- Close with Escape and restore focus to the trigger.
- Activate `Log out` and return to `/memoir`.
- Confirm no browser console errors or warnings during the flow.
- Confirm mobile layout at `390 x 844` keeps the trigger usable and the dropdown readable.

## Implementation checklist

- [x] Reuse existing header typography, colors, borders, radii, and shadows.
- [x] Render the current Supabase/profile identity with an anonymous-session fallback.
- [x] Provide an accessible, keyboard-dismissable dropdown.
- [x] Clear local story state and sign out through the Supabase client.
- [x] Preserve the existing responsive header behavior.

## Follow-up polish

- None required for this requested scope.

final result: passed
