# Fifty-round conversation preflight — 4 November 2026

Status: code and harness fixes are verified; the live fifty-round conversation
has not started. The selected retained-account test requires approval to create
the missing `test2@test.com` synthetic account. No existing account credentials,
email confirmations or application history have been changed.

The existing account-setup command was rejected by automatic approval review
because it can create/reset all five remote evaluation accounts. The narrower
pending action creates and confirms only the missing selected account, sends
no email and changes no existing account.

## Verified fixes

| Finding | Change | Observed verification |
| --- | --- | --- |
| Queued-source JSON exceeded the packet envelope | Compact tool JSON and bound compact history text by serialized bytes, preserving exact original-source windows and offsets | Previously one failed/three passed; now all four 40-window cases pass |
| Historical-clue reply received generic repair guidance | Named `CONTRACT_33`, consistent schema descriptions and published repair guidance v3 | English and Chinese production repair-path regressions pass |
| Composer re-reviewed mismatched craft evidence until timeout | Published exact-copy guidance for source/prose witness identifiers; retained strict validators | English first checkpoint passes in 81.646 seconds with two model calls, within the unchanged 150-second bound |
| Fifty-round preflight used a Linux-only executable path and obsolete expected-file pin | Resolve the installed `true` executable; pin the current checked-in expectation file | Combined current API/historical coverage checks: 194 passed |
| Old session tests expected retired payloads to bypass canonical admission | Require rejection before worker/provider execution | All five old role payloads are rejected with zero provider sends |

The composer failure was replayed from retained outputs using byte-identical
request hashes, without generating replacement evidence. The new live follow-up
is experiment `39c4d4266737d7dd`; its input, expected output, actual result and
scores were read back successfully from Langfuse. The old failed run is retained.
One successful follow-up establishes this observed result, not a latency SLA.

Additional checks: 20 composer grounding/craft regressions passed. The required
`make test-place-research` passed 741 JavaScript, 821 Python and 96 skill checks.
Both changed prompt Markdown artifacts were committed before publication; their
generated v3 receipts were reviewed and committed.

## Planned live campaign

- One current-API Chinese case: `chengdu-tea-ledger`.
- Fifty distinct original narrator turns with exact source/reply readback.
- Ten saved memoir checkpoints at rounds 5 through 50.
- Current GPT 6.1 Sol routing, two-hour case limit and 20,000 backend-request cap.
- Owner-scoped test allowance; no billing or Family entitlement changes.
- Preserve failed attempts, repair any discovered bugs, revalidate and push the
  reviewable branch `codex/fifty-round-agent-evaluation` after the campaign.

The old disposable launcher retains a historical model/worker contract; it
cannot substitute for a current-agent acceptance run. Its refusal of obsolete
worker payloads remains intact. The current retained-account API path needs the
selected account to exist before execution.

The [preflight evidence ledger](test-evidence/fifty-round-preflight-20261104.json)
records the pending account action, actual zero live-round count, measured
composer result and hashes/paths for preserved test logs.
