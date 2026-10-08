---
name: memoir-author-timeline
description: Propose canonical MemoryEvents for every authorised narrator input, preserving exact sources, identity, supported placement, uncertainty and author corrections. Premium display remains separately entitled.
---

# Memoir Author Timeline

The backend processes every unique accepted typed or transcribed narrator input
in its durable timeline lane, independently of premium display. Conversation
continues alongside extraction. Accepted evidence survives assistant failure;
a completed round requires a saved successful reply. Technical replay adds no
source or round. An empty extraction is successful processing.

Read [the shared contract](references/contract.md). Return only schema-bound
JSON `{"events": [...]}` to the private worker. Do not emit a conversational
reply, Family-document timeline marker, or direct database write. The application
validates proposals and atomically commits them to PostgreSQL.

Read saved canonical events and original context before reconciliation. One
input may support zero, one or several events, and an event may collect several
inputs, including late details about a much older memory. Use `existing_id` and
`expected_revision` only when original evidence establishes continuity. Similar
titles, dates and places do not establish identity. Keep recurring experiences
separate. Ambiguous matches retain scoped `candidate_ids` and unresolved status;
conflicting accounts retain attribution and uncertainty rather than a winner.
Propose new or changed events; use unchanged saved facts as context. An
acknowledgement with no new personal evidence returns an empty event list.

Stages are baby, toddler, childhood, adolescence, young_adulthood, midlife,
later_life and unplaced. Stage placement requires original `stage_evidence`.
Temporal placement retains its original expression, precision, optional supported
year/range and exact evidence basis. Preserve “around 1970”, “十二岁” and unknown
or uncertain dates. Capture order, elapsed time and a stage label never establish
a story date. Age estimates need explicit narrator birth evidence, not a relative's
birth. Keep a long residence or occupation as one kind: period interval record.

Every source reference cites an authorised original ID/version and exact quote,
with optional Unicode code-point span and attribution. Assistant questions,
summaries and earlier prose are not testimony. Source language is independent
of memoir locale. Before/after relations require a scoped canonical event target
and their original evidence. Person links use already established canonical
family identities; unresolved names do not create or identify a person.

An explicit current chat correction may include `correction` citing the whole
original statement and the target's expected revision. The backend records actor,
origin and authority. Saved user overrides take precedence over model estimates.
A stale revision requires a fresh snapshot. The model cannot grant privacy or
print rights. Removed source links cannot be silently restored.

One active invocation owns the timeline lane; new inputs coalesce into its next
catch-up. Claims, failures and timeouts never advance successful cursors. Retries
retain unfinished ranges and reuse committed effects. Source/event revisions,
policy and bounded ownership tokens fence obsolete output. Private text and
credentials remain outside Temporal history.
