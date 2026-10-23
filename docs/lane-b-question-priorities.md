# Lane B findings in the next interview question

Lane B can change the next Lane A question without adding a foreground model
call or waiting for unfinished research. Lane A uses only background results
already available when it assembles that turn's governed context. Results that
finish later become eligible on a subsequent turn.

The compact reply contract previously received historical-news context but
could not select a news question or return its clue identity. Its adapter also
discarded the historical bridge/display metadata, and the strategy transaction
accepted only plan candidates and pending confirmations. The new regression
failed with `Candidate is stale, asked or outside this project`. Plan-only
confirmations and the missing topic-expansion objective had separate failing
regressions.

## Selection order

Current stop, privacy, correction, explicit redirection and pacing instructions
take precedence. Within that boundary the supplied hints are ordered:

| Priority | Available background result | Next-question behavior |
| --- | --- | --- |
| 1 | Pending conflict, identity, chronology or other confirmation | The oldest supplied pending confirmation wins over an ordinary follow-up. Exact narrator evidence and answer-backed retirement remain required. |
| 2 | An active `broaden_scope` strategy plan | Its prepared questions invite a less-covered topic or period. Lane B recommends a change; it cannot declare a life stage complete. |
| 3 | Ready historical/public-event clues for the admitted place/period | Lane A may select a relevant clue with the existing neutral optional memory invitation and public citation. |
| 4 | Ordinary prepared follow-ups | Follow the story when higher-priority hints are irrelevant or absent. |

Lane A still interprets the current message and relevance. Unfinished news work
does not block delivery. Public clues are not personal facts, and their dates
do not become biographical dates. Disabled, used, uninspected, stale and foreign
clues do not become selectable hints. Existing SQL source/policy/project fences
also recheck authority before saving.

Both reply-v2 and the older strategy selector preserve the host-owned historical
clue ID and optional bridge. The database now accepts a ready news identity
independently of an optional strategy plan, checks its neutral question, and
saves its citation through the existing interview-plan writer. Saved retries
replay that citation without another reply call. The client already supports the
public historical snapshot; no UI change is needed.

## Verification and activation

The new regressions cover both languages, unavailable news, fabricated personal
evidence, changed news questions, conflict/person/order clarifications, answered
confirmation retirement, topic expansion, precedence, SQL commits, one reply
call per new turn, cached retry, and the actual saved API result through the
production JavaScript client. They are included in `make test-place-research`.
These use controlled model and public-source transports, not live semantic or
latency acceptance.

Observed checks on this change:

- `make test-place-research`: **604 JavaScript, 466 API/database, 95 standalone
  checks passed**, including the new API-to-client news replay.
- **188** compact reply/news/clarification/strategy and prompt-governance checks
  passed; the standalone new priority/replay cohort has **37** passing cases.
- **88** additional historical-news/strategy SQL authority, stale/shadow-plan,
  scoped rollout and adversarial review checks passed.
- All isolated runs retain exit-code/process-cleanup receipts under
  `var/optimise-all-skills-20261022/checks/lane-b-priorities-*`. Initial red tests,
  incomplete fixture attempts and the missing recall-helper replay failure are
  retained alongside the corrected passing runs. No failed case is counted as
  passing until rerun.

The combined reply and governed-turn instructions remain **1,986 characters**,
including the separating newline. Lane B's existing extraction call gains the
`broaden_scope` objective; no classifier or additional model phase is added.

Two prompt sources change: the compact reply's hint priority rule and the
background strategy proposal's topic-expansion guidance. Their Langfuse receipts
are intentionally unchanged on the feature branch. Merge reviewed source to
`main`, publish via `make prompt-sync`, commit the genuine receipt updates, and
verify `make prompt-check` before activation/live acceptance. The fresh-install
database baseline also includes the strategy transaction change; no running
database or service was changed by these tests. PR #117 stays draft and unmerged.

This fixes the selectable-question handoff. It does not establish useful live
news discovery coverage: the earlier bilingual live research baseline still
returned zero verified clues. Its source-grounding failures and the campaign's
other quality blockers remain open in `optimise-all-skills.md`.
