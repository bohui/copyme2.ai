# PR 58 review follow-up — 12 October 2026 (Sydney)

## Result

Addressed the [review comment](https://github.com/bohui/copyme2.ai/pull/58#issuecomment-6109235714)
with a reproduced startup save-gating fix, expanded backend acceptance cases,
real-proxy smoke and explicit negative full-suite evidence. **Issue 53 remains
open.** Faster quality-preserving generated replies have not passed the release
gate. Normal model, maximum effort, full legacy prompt and service flags remain
unchanged. No candidate rollout or shared gateway policy change was made.

Application base/head examined: `20dbeb40143409ca7882756dcf7281309c9b94ab` /
`d7eb7af87600e9e56a5fff2c86d6562a41b5c8bc`, plus this follow-up's source changes.
Relevant running API/private-worker source hashes matched that head. The deployed
worker uses Codex 0.156.1; host profiling uses 0.155.1. These versions must not be
silently treated as the same experiment pin. The profiler now records its binary
version, or unavailable, alongside the application revision/source hash.

## Reproduced and fixed

The fixed introduction keeps the composer available while painting. Its completion
then unconditionally reset `state.loading`, even if the storyteller had started a
generated turn. A red JavaScript regression reproduced this independently of any
provider. Removing that redundant reset makes the generated turn retain ownership
of the busy flag until saving or controlled failure. Introductory copy, model
requests, source history and reply quality are unchanged. Existing project-navigation
fencing still applies.

The normal-route real-proxy smoke also observed early readiness before the fix.
An initial cloned-stream observer could race the UI; a separate red/green test now
requires observation of the native reader before the UI consumes each unchanged
packet. The final native-reader run against the corrected production frontend passes.
Reload comparison uses rendered `innerText`, not `textContent` which omits `<br>`
line breaks. Earlier incomplete runs are not successful acceptance evidence.

## Backend acceptance coverage

The existing backend streaming profiler has an opt-in `--extended` mode: 40 matched
baseline/candidate generations covering both languages and short, long-stress,
Family and public-reference cases, plus two unpaired rollback generations. Rollback
resumes the **actual just-generated candidate history**, clears operator overrides,
and preserves sources, saved plan and Family context. Tests distinguish candidate
history from baseline history rather than assuming identical replies prove rollback.

The frozen bound is 42 foreground generations, at most 84 application app-server
turns, 120 seconds per generation, 1,200 seconds overall, stop at first failure.
Those are not exact upstream request budgets. The default remains the existing
24-generation campaign. Neither extended nor combined-candidate live comparison was
dispatched in this follow-up. Long repeated synthetic text is a completeness stress
case, not representative emotional-story quality acceptance. Controlled provider
coverage is plumbing/contract evidence, not semantic equivalence.

## Confirmed routing confound and proposed next step

[Safe request-shape receipts](issue53-request-shape-20261012.json) use the real Linux
worker/app-server with fresh tenant-owned homes and a loopback provider that returns
400. **No upstream model was called.** The existing `memoir-luna-low` alias makes
Codex advertise seven tools and changes instruction layout; the normal pooled route
advertises none. Gateway policy still maps both to the same underlying model, with
max versus low effort. Therefore the previous trial was not an effort-only harness
comparison. This does not prove the cause of every prior slowdown.

A proposed `gpt-5.6-luna-memoir-low` alias produced the same request sizes/layout and
empty tool set as the baseline on Codex 0.156.1. That name is **not provisioned or
live-policy-verified**. Operator approval was requested before adding it to the
local gateway. The concrete change would copy the existing low-route entry and
change only its alias, preserving underlying model, endpoint, credentials and low
policy; leave all existing aliases/shared max policy/defaults unchanged.

After approval/provisioning, verify the new policy read-only, pin one app-server
version and run bounded matched backend quality/latency comparisons. A compatible
alias is not itself evidence of faster or equally good replies. Do not close 53 or
enable a default based on this preflight or the browser smoke.

## Verification

Counts overlap; they are not a unique-test sum. No CI pass is claimed.

| Check | Observed result |
| --- | --- |
| Default backend configuration/preparation/profiler/language/name/plan/photo/real PostgreSQL readback/lease/stream set | 192 passed, 23.01s; final profiler version metadata checked separately |
| Profiler + existing Codex runtime tests | 80 passed, 6.19s |
| Final profiler, including version metadata and extended cases | 5 passed (result recorded after the metadata addition) |
| JavaScript streaming/navigation/history/photo/project restore/observer set | 59 passed, 0.188s |
| Production frontend build, Node 24 + Webpack | Passed; non-fatal next-intl webpack cache warnings |
| Corrected production frontend desktop/phone save-gating, reload and fresh-tab controlled smoke | 6 passed, 10 deselected, 19.63s |
| Real production web proxy → running API → private Linux worker → live provider → Supabase save/reload | 3/3 saved; no early unlock, duplicate reply or reload resubmission |
| Full Python suite attempted | 4,009 passed, 69 failed, 194 skipped, 39 setup errors, 536.82s; **not green** |

The full-suite failures include macOS `/bin/true` assumptions, a locale SQL fixture
that does not use the Apple-container backend and fails `initdb`, and older
controlled-provider fixtures producing unstructured replies. A disposable base
snapshot comparison selected 107 matching cached failed node IDs: 68 failed, one
passed and 38 errored. The cache also contained stale IDs; the snapshot lacks Git
metadata and has different browser prerequisites. This is evidence of several
pre-existing failures, **not proof that every head failure is unrelated**.
The initial snapshot command had unavailable node IDs and ran no tests; it is not
verification. Temporary snapshots were removed after their subprocesses finished.

A low/compact-enabled controlled set had 189 passes and one failed fixture assertion
expecting the legacy `test-model` route while the collector override correctly selected
`memoir-luna-low`. Its normal-configuration counterpart passes. Do not describe that
entire candidate-enabled run as green or as live semantic-quality acceptance.

### Final real-proxy smoke

Task-owned production frontend on 3347 forwarded to the unchanged running API on
8010. No browser auth/API/provider/stream replacements. A new synthetic anonymous
memoir `project_d6dbb01585ee` was used; its saved test exchanges remain for readback.
Frontend/backend/smoke source SHA-256:
`49645bfe6e0e28977995103b7000ecafd57f5ab4068f96b0534e88657e7e761d`.

| Case | First public text | First rendered text | Validated reply | Conversation saved |
| --- | ---: | ---: | ---: | ---: |
| First/name | 8.509s | 8.513s | 10.102s | 10.102s |
| Later/name change | 7.401s | 7.402s | 8.464s | 8.464s |
| Reloaded/resumed pause | 4.065s | 4.066s | 4.569s | 4.576s |

One question in each non-stop reply; none after the pause. The saved prior reply
restored exactly once and reload dispatched no new turn. These are normal-route
smoke observations, not candidate speed improvement, production percentiles, or
comprehensive quality evidence. Synthetic accounts/projects were not deleted.
Six individually capped smoke invocations dispatched ten foreground requests in
total while developing/verifying the check; only the final three-turn invocation
completed every assertion. Exact upstream request/retry counts remain unavailable.

## Closure gate still outstanding

The compatible dedicated route requires approval/provisioning and live policy
verification. Representative matched first/later/resumed quality and latency,
long/Family/reference/rollback live evidence, and a resolved final verification
position remain necessary. The no-normal-response-quality-loss requirement is
unchanged. Issue 53 must stay open until those gates genuinely pass.
