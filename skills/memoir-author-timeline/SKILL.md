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

The host supplies [the shared contract](references/contract.md) and the required
phase instructions with this skill. Return private draft events in the supplied
JSON schema. Include a start and end estimate and a location candidate when
supported by the originals. Leave unsupported bounds or geography unknown and
retain the evidence and confidence for every proposed placement. The Timeline
reconciliation step matches these drafts to published events before the host commits.

Read saved canonical events and original context before reconciliation. One
input may support zero, one or several events, and an event may collect several
inputs, including late details about a much older memory. When the schema
requires a null existing_id, return a private draft for new testimony even if it
continues a known event. Keep expected_revision and correction null and leave
candidate_ids empty. The next Timeline operation selects the identity. Legacy
requests that allow existing_id require original evidence for continuity. Similar
titles, dates and places alone do not establish identity. Keep recurring
experiences separate. Combine passages about the same memory in one draft
and retain all supporting original spans. An acknowledgement with no new
personal evidence returns an empty event list.

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
proposed event. Select the most specific supported event setting using the authorized originals,
including earlier conversation and saved event context, and cite the exact
context clues in location_basis. The location object has place, granularity and hierarchy;
hierarchy begins with the literal "Earth" and ends with the identical place
label, for example ["Earth", "Australia", "Tasmania", "Hobart"]. Use 1 for an
explicit unambiguous placement and a score below 0.5 for a weak guess.
For scores of at least 0.2, the place label must appear verbatim in location_basis.
Use suburb for a named town/neighbourhood and landmark for a named public
hospital, school or other public point of interest. Keep the containing city in
the hierarchy. For “出生在河北省承德市附属医院”, location.place is “承德市附属医院”,
with hierarchy ["Earth","中国","河北省","承德市","承德市附属医院"] and granularity
landmark. For a later clarification “承德师范，当时在大石庙镇”, update the existing
childhood event's location to “大石庙镇” under 承德市, granularity suburb. Retain the
stated historical name; a public map resolves coordinates separately. Household,
building-unit and room details stay in the narrative; an unnamed hospital or
school compound supplies no landmark identity. City-only context stays city-level
until originals support a finer setting. Preserve detailed placements on later
continuations. Only legacy requests can include a separate place_journeys array.
When only a country or broader setting is plausible, still choose a provisional
real city within that setting, preferring the narrator's known places. Give this
city a confidence strictly between 0 and 0.2, typically 0.05–0.15. Its name need
not appear in the original: location_basis quotes the actual country/context
clues, and uncertainty explains the assumed country/city and why that city was
chosen. Keep it distinct from the narrator's stated facts. Mira will prioritize
a neutral city clarification in Lane A. Retain the candidate even when confidence
is very low; location=null and score=0 mean no plausible setting can be inferred
from any available context. Explain every inference in uncertainty. Birth in Chengde followed by
“小时候在爸爸学校家属院玩” supports a tentative Chengde candidate with low confidence,
plus a broad childhood age/year estimate anchored to the original birth evidence.
The workspace groups provisional candidates with a small question mark below
50%; only scores of at least 0.85 create established map links. Mira still receives
lower-confidence placement for clarification. Keep primary source_refs on the
CURRENT original; earlier placement evidence is a dependency, not new testimony.

When later originals improve a saved event’s placement, draft the revised
placement with the new evidence. Leave identity selection to reconciliation
when the schema requires a null existing_id. When a follow-up adds activity details without new placement
evidence, carry forward its candidate location and temporal_estimate with their
authorized basis and confidence. Revise them when new evidence supports a
different estimate or contradicts the earlier guess. Keep the full period together so the host can match it to the same identity. Keep yearConfidenceScore aligned with
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
When a narrated sequence supplies a start age and durations, use them to revise
the affected periods together, including an already saved current residence.
Use stated anchors and durations first. Where a duration is missing, make a
context-specific provisional assumption, explain it in rationale and lower
confidence; there is no fixed study length or residence age band. Propagate the
result through the connected periods so an earlier residence ends around the
next move and the later residence starts around that same transition. Only an
explicitly current residence runs to the original capture year. Preserve stated
ages and dates separately from inferred, rounded period bounds. Revise existing
canonical events as well as new proposals; city labels are only their projection.
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
of memoir locale. Preserve explicitly narrated order in sourced before/after
relations even when temporal_estimate intervals overlap or share a boundary.
When the schema supports draft targets, label each related draft with a
unique ID such as `draft-1` and use `draft_id` for a target in this same output.
Reconciliation can add links to published events. A legacy schema can link a
supplied canonical event ID directly. Cite the contiguous
original passage establishing the sequence. Put the relation on the appropriate
new or updated event and retain supported order on later updates.
Unknown transition dates stay uncertain, and capture order alone supplies no
chronology. Person links use already established canonical
family identities; unresolved names do not create or identify a person.

For a current chat correction, draft the corrected stage, dates or location
with the original evidence. Reconciliation can recognize explicit author
correction wording. When the legacy schema permits correction, cite the whole
original statement and the target revision. The backend records actor, origin
and authority. Saved user overrides take precedence over model estimates.
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
