# Five-case full Memoir evaluation

Goal: five conversations of 50 original rounds, with saved Lane A replies,
grounded locations, photographs, historical context, saved memoir checkpoints,
and an author-approved private game visible and playable in the UI.

## Current campaign

- Run: `dcd5bac0-992f-46fa-89fb-4fc05c319bb9`.
- Evidence: `/Users/bohuihan/memoir-test-results/dcd5bac0-992f-46fa-89fb-4fc05c319bb9`.
- Frozen conversation source: `c1d7103caafdbc9d8d976f136b31939803027f3a` in the
  attached `memoir-full-e2e` worktree.
- Five fixed, separate test owners; remote Supabase persistence; current live
  gateway; authenticated turn and canonical source/draft readbacks.
- The conversation runner uses the API. Separate real-browser checks cover UI
  recovery, media selection and the complete game authorization/play flow.

## Completion evidence required

| Requirement | Required authoritative evidence | State |
| --- | --- | --- |
| 250 Lane A turns | Exactly 50 distinct original turns per owner; nonempty saved replies; owner-scoped database recovery | Running |
| Location skill | Grounded named places saved against the accepted originals and displayed in each workspace | Pending |
| Photo skill | Real source-backed discovery/cache receipts and rendered images for selected places; unsupported periods remain explicit | Pending |
| News skill | Verified public sources saved by the after-delivery runner and visible as attributed context | Pending |
| Memoir composer | Ten complete saved checkpoints per case, original source coverage and preserved unchanged prose | Pending |
| Game generation | Real provider completion after persisted composition/adaptation authority, validated original-grounded candidate | Implemented and controlled-provider tested; live campaign pending |
| Author authorization | Private authenticated review of exact candidate and specific character permissions; missing/stale/revoked consent rejected | Actual PostgreSQL and browser checks passed; five-case verification pending |
| Game publication | Atomic private save after exact-candidate approval; fresh authority checks through actual HTTP delivery | Database publication/send-race checks passed; five-case verification pending |
| UI game | Two connected scenes and two permitted people; keyboard, touch and text equivalent; refresh recovery and revocation removal | English desktop and Chinese phone checks passed with real routes/disposable SQL |
| Langfuse | Durable experiment/score readback tied to campaign evidence and source versions | Pending |

The earlier isolated skill baseline is recorded in
`skill-trigger-delivery-evaluation-20261018.md`. It establishes neither these
250 turns nor successful production game integration.

## Game integration verification

- `var/story-game-checks/browser-play.json`: two complete source-frontend flows
  passed, including formal completion, consent, exact-candidate/person approval,
  keyboard and real touch movement, scene travel, text equivalence, refresh recovery
  without regeneration, and revocation removal. External Auth/model were controlled;
  application HTTP routes and PostgreSQL were real.
- `var/story-game-checks/integrated-regression.json`: 103 affected checks passed.
- `var/story-game-checks/migration-chain.json`: 15 real PostgreSQL checks passed,
  including stale-token rejection, three-attempt bound, original matching, owner
  isolation and revocation racing the actual HTTP send.
- The remote database already contained game migration `202610180002`; it was
  preserved. Additive `202610180003_story_game_delivery_fixes.sql` was applied and
  all three changed function bodies were read back and matched to source.
- All 70 managed prompt artifacts were checked against exact Langfuse versions.
  Game instructions/runtime contract are v2; the new proposal prompt is v1.
- Main-checkout UI/API inspection uses ports 3011/8011. The conversation campaign
  uses 3010/8010. Its separately recorded composer repairs are described below.

## Round-35 recovery

The first case saved 35 replies but stopped with 34 settled rounds and six
completed checkpoints. The pending composer reported
`LIFETIME_MODEL_BUDGET_REQUIRED`. A rollback-only database capture and offline
replay reproduced its actual draft rejection in under one second, with no live
provider calls. The retry packet included a failed candidate, validation and
review in addition to the complete canonical request.

The first repair regenerated from the unchanged request when the optional failed
candidate and review exceeded the input budget. Its regression passed with 60
affected checks, but the real model then repeated unsupported editorial wording:
dropping the earlier review lost useful correction context. That attempt remains
an incomplete result.

The next repair allocates 98,304 input tokens to composer phases within the same
131,072-token model context, retaining the 16,384 output and 2,048 framing
headroom. Timeline phases retain their 65,536 input limit; explicit environment
limits are respected. This admits the complete captured repair, including all
review feedback, in the actual worker image with one controlled draft dispatch
and no real provider call. Host validation remains unchanged. The 102 affected
checks passed. The host-only replay initially used a different Node/ICU version;
the successful replay used the evaluation worker's exact runtime.

The campaign checkout now includes the three composer files
`lifetime_memory_composer.py`, `lifetime_memory_lane_engine.py` and
`memoir_preview.py`. Each change is recorded in the existing run's source-change
history. The first case has an explicit four-hour elapsed-time allowance recorded
to cover diagnosis; original budget values and submission counters are retained.
Earlier turns keep their original checkout fingerprints. No saved turn was
discarded or intentionally resubmitted. The UI-game acceptance process waits
until each case has all 50 complete original rounds and ten checkpoints before
beginning its private flow.

## Scoped strategy activation and history recovery

At 45 original submissions (45 saved replies, 44 settled rounds), authenticated
UI inspection found no current interview mode. The remote rollout was enabled
with `strategy_shadow=true`; no foreground strategy outcomes had been delivered.
This correctly prevented the new private game from becoming eligible. The runner
was deliberately interrupted before any further original submissions; its saved
round 45 remains recoverable by the same UUID.

Migration `202610180004_scoped_interview_strategy_rollout.sql` adds an operator-only
owner cohort. It applies to planner pages, foreground strategy context and current
mode reads, while retaining both global kill switches. It enrolls nobody itself.
Twenty-nine affected SQL/runtime checks passed, including real controlled-provider
foreground delivery, owner isolation, denied self-enrollment and rollback.
The remote preexisting function bodies were compared before application; all four
resulting function bodies were read back and matched afterward.

Only the five fixed, confirmed test owners were enrolled. Other owners retain
shadow behavior and the global rollout row is unchanged. The durable receipt is
`strategy-rollout-activation.json` in the campaign directory. Activation creates
no strategy outcome, generated reply or game permission; the remaining original
turns must establish their actual delivered strategy.

The next source-change receipt also includes the tested photo/news protocol fixes
and the three additive migrations in the campaign checkout. The original dataset,
owner bindings, conversation identities and submission ledger are retained.

History inspection separately found that the first 20 replies were saved against
older preference revisions (2–4; current revision 5), so the existing authority
checks withhold them on reload. The UI acceptance checks all 50 exact original
messages, matches rendered saved-reply IDs against the authenticated history
projection, and reports withheld replies explicitly. It does not restore stale
replies from raw storage or count the opening greeting as a saved turn. Evidence
that all 50 replies were originally saved remains a separate campaign requirement.
