# Background-question handoff corrections

The user requested continuation through completion after reviewing the named
correction proposal. This implements that proposal on the existing
`optimise-all-skills-2` continuation branch; the branch requirement in the user's
campaign takes precedence over the workflow skill's default main checkout.
No worktree was created. The earlier failed live baselines remain unchanged.

The compact reply packet now explicitly labels eligible hints as highest
priority first. The reply schema describes the coupling between hint index,
selection reason and host-owned evidence, and requires acknowledgements to
leave pending clarification unresolved. The revised reply instruction is
1,978 characters including the governed dispatch. A normal request to change
subject is distinguished from an actual topic exclusion/pause in privacy
guidance; unresolved explicit privacy targets still fail closed.

A hint-quote mismatch receives a dedicated `CONTRACT_31` repair code. The
original invalid proposal is rejected unchanged; repair regenerates the
envelope with the hint's index/reason and `quote=null`. No invalid source
metadata is dropped, no coordinates are manufactured, and the host retains
the original exact evidence. No validator, schema field requirement or SQL
authority check is relaxed.

Offline validation passed: **110 focused tests**, then the required
`make test-place-research` (**604 JavaScript, 466 API/database, 95 standalone**),
with verified isolated cleanup. Regression coverage includes actual rejection
and repair through the existing provider seam and retention of the hint's
original evidence. These passes do not establish live model quality.

The next live manifest retains all sixteen original cases and eight new
bilingual identity, subject-switch, exclusion and stop cases. It has a
120-call ceiling including policy retries and reply repairs, no model judges,
60-second provider deadlines and a 30-minute arm deadline. It uses the existing
collector-approved low route only in isolated SQL/runtime state. Shared model
settings remain unchanged. Full source/receipt provenance, output, save,
previous-reply and cached-retry witnesses are required.

**Publication complete; live acceptance still fails.** PR119 merged and the
normal main-only publisher created reply v3, privacy review v6 and repair codes
v6. All 93 pins verified. The [fresh before/after comparison](lane-b-handoff-comparison-20261024.md)
retains both new cohorts and failures: the first improves from 10/16 to 15/16
passing originals; its repeat has a news-selection failure and a provider 502.
A bounded invalid-review recovery is implemented and verified, and the final
news-intent clarification is prepared for review/publication. No feature-branch
publication or live loader bypass was used. Game remains last.
