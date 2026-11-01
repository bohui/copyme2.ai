---
name: memoir-author-timeline
description: Extract new or corrected narrator memories and continuity when Lane B selects timeline work, preserving exact sources, event identity, supported placement and uncertainty. Premium display remains separately entitled.
---

# Memoir Author Timeline

The background agent reviews every unique accepted narrator input and selects
this skill for supported memory or continuity work, independently of premium
display. Conversation continues alongside extraction. Accepted evidence survives assistant failure;
a completed round requires a saved successful reply. Technical replay adds no
source or round. An empty extraction is successful processing.

Read [the shared contract](references/contract.md). Return only JSON matching
the supplied output schema to the private worker. Do not emit a conversational
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

Read conversation_history (the preceding twenty conversation rounds, oldest
first) AND last_event before resolving the current memory's identity, location
and year. Each round contains an authorized original excerpt and, when available,
an assistant reply labelled as context. Complete flags identify clipped excerpts;
unlisted or clipped words remain unknown. last_event supplies the most recently
saved earlier event and its original passages, including when it falls outside
the twenty-round window. Use these antecedents to understand “there”, “that year”
and continuation of an existing event. Cite original narrator evidence for each
placement; assistant wording remains context only.

Return locationConfidenceScore and yearConfidenceScore from 0 to 1 for EVERY
proposed event. Select the most plausible coarse location from the authorized
originals, including earlier conversation and saved event context, and cite its
exact location_basis. The location object has place, granularity and hierarchy;
hierarchy begins with the literal "Earth" and ends with the identical place
label, for example ["Earth", "Australia", "Tasmania", "Hobart"]. Its place label
must appear verbatim in a cited location_basis quote. Use 1 for an explicit
unambiguous placement and a score
below 0.5 for a weak guess. Retain the candidate even when its confidence is low;
location=null and score=0 mean no candidate is supported anywhere in that context.
Explain the inference in uncertainty. Birth in Chengde followed by
“小时候在爸爸学校家属院玩” supports a tentative Chengde candidate with low confidence,
plus a broad childhood age/year estimate anchored to the original birth evidence.
The workspace groups provisional candidates with a small question mark below
50%; only scores of at least 0.85 create established map links. Mira still receives
lower-confidence placement for clarification. Keep primary source_refs on the
CURRENT original; earlier placement evidence is a dependency, not new testimony.

When later originals improve a saved event's placement confidence, update that
event with existing_id and expected_revision, revised placement values and the
new evidence. When a follow-up adds activity details without new placement
evidence, carry forward its candidate location and temporal_estimate with their
authorized basis and confidence. Revise them when new evidence supports a
different estimate or contradicts the earlier guess. Return those placements on
the same identity. Keep yearConfidenceScore aligned with
temporal_estimate.confidence while the preferred year remains inferred. New
stated timing takes precedence over an earlier guess.

Stages are baby, childhood, adolescence, young_adulthood, midlife,
later_life and unplaced. Stage placement requires original `stage_evidence`.
Temporal placement retains its original expression, precision, optional supported
year/range and exact evidence basis. Preserve “around 1970” and “十二岁” verbatim.
Store only bounds expressed in the cited words in temporal.year_start/year_end.
For “2012年7月开始在这里住”, the stated start is 2012 and the stated end is null.
Any endpoint derived from created_at belongs only in temporal_estimate, even
after one bound has been confirmed.
For missing years or ages, return the best provisional temporal_estimate: bounded year and/or
age ranges, confidence strictly between 0 and 1, a concise rationale, and exact
basis references. Use contextual dates, elapsed durations and before/after links
across the authorized originals. Anchor “now” and “fourteen years here” to the
cited original's created_at year, recorded as reference_year, so replay keeps the
same estimate. Allow for rounded durations and gaps between life periods.
For a period, estimate its whole span; an explicitly current residence may end
at its original capture year. For a point event, the range expresses uncertainty.
Use the narrator's own birth evidence to convert years and ages; a relative's
birth year is not that anchor. A supported life stage may justify a broad age
range with low confidence (typically 0.2–0.5); calendar estimates need an original
birth/date/duration anchor. Explain those assumptions in rationale. Derive both
year and age ranges when anchors permit. Set temporal_estimate=null only when
the originals cannot support either estimate or stated timing already suffices.
Uncertainty lowers confidence instead of deleting a supported estimate. For a
current residence with an unknown start, use a broad plausible interval from the
authorized birth/life-stage anchors to the original capture year, with low
confidence and the assumed start explained in rationale. Keep inferred numbers
out of stated temporal fields; capture order alone is not
chronology. yearConfidenceScore describes the preferred stated or estimated year
placement, with 0 when neither exists. Estimates remain revisable and never replace
an explicit author correction. Keep a long residence or occupation as one kind:
period interval record, even when it crosses several life stages.

Every source reference cites an authorised original ID/version and exact quote,
with optional Unicode code-point span and attribution. Assistant questions,
summaries and earlier prose are not testimony. Source language is independent
of memoir locale. Before/after relations require a scoped canonical event target
and their original evidence. Person links use already established canonical
family identities; unresolved names do not create or identify a person.

An explicit current chat correction may include `correction` citing the whole
original statement and the target's expected revision. The backend records actor,
origin and authority. Saved user overrides take precedence over model estimates.
A location-only clarification uses an ordinary existing_id update; correction
is for stage or date changes.
A stale revision requires a fresh snapshot. The model cannot grant privacy or
print rights. Removed source links cannot be silently restored.

One active invocation owns the timeline lane; new inputs coalesce into its next
catch-up. Claims, failures and timeouts never advance successful cursors. Retries
retain unfinished ranges and reuse committed effects. Source/event revisions,
policy and bounded ownership tokens fence obsolete output. Private text and
credentials remain outside Temporal history.

Mira owns real-time clarification, topic development and reflection in Lane A.
Return event extraction, geography and supplied continuity fields only; saved
results provide context for her later replies.
