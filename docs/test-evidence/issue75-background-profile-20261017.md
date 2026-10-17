# Issue 75: background narrator profile

Initial implementation: `c4c0a3c8e0c8344bca48219943801d4c2ca67db1`.
The commit containing this evidence also includes the user-review fixes below.
Base: `22f44d3a64407e70b7eb6bb91a7dae7850f38e4f`.
PR: https://github.com/bohui/copyme2.ai/pull/78
Specification: `docs/Memoir_Background_Memory_Context_Spec.md`.

All database checks used disposable native PostgreSQL. Provider responses were
controlled at the existing worker HTTP boundary. No production migration, live
memoir access, paid provider request, or rollout activation was performed.

## Review fixes and revalidation

- The canonical chosen-name writer clears superseded background name evidence
  before publishing a replacement. Real Lane A commits now survive edits and
  withdrawals of the older Lane B source, including repeated same-value names.
  Withdrawal of the current source still removes its inferred name. All four
  new cases failed before the fix and passed afterward.
- Failed private-profile hydration is retried on the next first-message attempt.
  Continued failures preserve typed/reviewed-voice drafts without inferring a
  language; recovered explicit preferences bypass both first-reply helpers.
- Authoritative private-profile reads replace the six supported personal fields,
  including deletions, while retaining workspace, photo and newer manual state.
- The existing readiness loop now returns a fenced private-profile projection
  and remains pending while scheduled profile work is outstanding. Active
  interviews refresh values and deletions without another service or reload.
  Recording/voice capture avoids a composer rebuild.

Observed after these fixes:

| Check | Outcome |
| --- | --- |
| `tests/test_background_profile_postgres.py` + `tests/test_background_profile_workflow.py` | 55 passed |
| Final additional active-readiness cases, `tests/test_background_profile_workflow.py -k active` | 2 passed, 5 deselected |
| `tests/test_lifetime_name_provenance.py`, `tests/test_two_lane_memory.py`, `tests/test_background_profile.py`, `tests/test_profile_settings.py`, `tests/test_mobile_openapi_contract.py` | 95 passed |
| All JavaScript regressions | 533 passed |
| `tests/test_two_lane_browser.py` + `tests/test_profile_settings_ui.py`, source frontend in Chromium | 14 passed |
| Production web build, Node 24, Next.js webpack/standalone | Passed |
| Mobile OpenAPI snapshot | Matched, 48 operations |
| Whitespace checks | Passed |

The final active-readiness cases cover pending → saved → withdrawn readback,
wrong-project rejection, and withdrawal during a profile read: a stale captured
birth fact is rejected before HTTP publication. Browser checks cover both UI
languages and all three conversation strategies, visible name/artwork updates,
withdrawn values, and preservation of an unsent draft. These controlled strategy
cases do not claim implementation of #76's skill-applicability map.

## Initial implementation checks

| Check | Outcome |
| --- | --- |
| Profile SQL lifecycle, existing chosen-name lifecycle, controlled five-case publication | 70 passed |
| Authenticated conversation/profile workflow and existing two-lane workflow | 32 passed |
| Profile proposal and active skill/evaluation checks, excluding the separately tested native publication case | 226 passed, 1 deselected |
| Profile settings API and mobile OpenAPI tests | 29 passed |
| Profile editor Chromium checks | Passed |
| All JavaScript regressions | 522 passed |
| Mobile profile settings contracts | 15 passed |
| Reviewed mobile OpenAPI snapshot | Matched, 48 operations |
| Production web build, Next.js 16.3.6, Node 24, webpack/standalone | Passed; existing next-intl cache warnings |
| Live-skill dry plan | Zero HTTP dispatches |
| Whitespace checks | Passed |

The conversation workflow runs through round 20 using the authenticated API,
actual timeline worker, provider admission guard, canonical SQL commits, and
authenticated profile reloads. A birth fact supplied in round 2 is saved at 5;
a childhood place supplied at 7 is saved at 10. A UI-owned birthplace remains
reference context but is excluded from later writable targets. Confirm-all at 10
suppresses further profile model calls through 20 and records that later milestone
as skipped rather than parsed. Separate barriers hold or fail the profile provider
while the next foreground reply commits.

Lifecycle tests cover configurable cadence and high-round catch-up, frozen
frontiers, accepted originals without replies, failed-range coalescing, partial
windows/restart/replay, Unicode evidence, overlapping windows, protected blanks,
stop/release/re-enable, source/privacy invalidation, current names and newer name
authority, stale provider admission and commits, and account/project isolation.
Locale submission tests observe zero calls to both first-reply helpers for explicit
choices, including reviewed voice, delayed hydration, and account/manual-change
races. Native HTTP tests also verify the chosen locale reaches the collector.

These checks establish persistence, validation, scheduling, and UI behavior with
controlled model output. They do not measure live extraction quality or latency.
The user owns review of PR #78. No independent review or merge approval is claimed.
