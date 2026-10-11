---
name: historical-news-research
description: Prepare optional source-grounded public historical context for later memoir questions, independently after the visible reply is saved.
---

# Historical news research

This is an application-owned background lane, not a collector tool. The collector
consumes only an already-ready projection. Never run research during its reply,
add a classifier, infer biography from a public event, or change photo defaults.

Use the deterministic adapter in `apps/api/historical_news.py` and gateway adapter
in `apps/api/historical_news_provider.py`. Their input is accepted versioned life
context; their only output is external contextual clues. See the contract below.

- Favor the active personal memory and ordinary retained questions first.
- Missing, conflicting, excluded or overly broad context means no lookup.
- Birthplace is tentative geography, never proof of later residence.
- Discovery uses only reviewed public place labels, coarse years, neutral terms.
- Require a completed native search receipt, returned URL and inspected page.
- Public event dates are distinct from source publication and personal dates.
- A shown clue produces no narrator evidence or MemoryEvent. A later answer is
  the storyteller's exact testimony, with the cue separately attributed.
- At most one ready clue joins the five-candidate pool. Exactly one question is
  visible, in the current interview language, with the source title preserved.
- Invite recall neutrally; no assumed awareness, attendance, residence or emotion.
- Permit skip and uncertainty. Retire shown/rejected clues; opt-out fences jobs.
- Never select unsolicited violence, trauma, discrimination or political conflict.
- No credentials, paid plans, production migrations or live evaluations are
  authorized by this skill. Default rollout is off.

Read `references/contract.md` for budgets, evidence, privacy and review boundaries.
