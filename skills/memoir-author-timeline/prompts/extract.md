# Memoir Author Timeline

Extract event and period proposals from the current authorized narrator window. Follow the supplied JSON schema, including its optional sections. Return an empty events array for a control, acknowledgement or passage with no supported memory. Return structured output only.

## Evidence and authority

- Read saved canonical context, including conversation_history and last_event, before interpreting a follow-up, relative date or inherited setting. Earlier authorized originals can ground placement. The current original supplies the new primary source_refs. Treat clipped text as unknown.
- Every citation uses the authorized source ID and version and one exact contiguous quote in its original language. Use Unicode character offsets relative to the cited excerpt when supplied. Use null for an exact unique quote if its offsets are unknown. The host restores absolute positions. Assistant replies, summaries, captions, planning and prior prose can help locate context. Cite original testimony for facts.
- Distinguish the narrator's experiences from quoted speech, other people's memories, negation and hypotheticals. Keep the actual subject and attribution. Use only supplied canonical person identities. Leave person IDs empty or null when no registry establishes an identity.
- Apply explicit recording boundaries to the claims they cover. A local veto can cover a preceding recollection, including someone else's account. A source-wide veto covers the entire source. Exclude restricted testimony from events and their dates, stages, places, relations and corrections. Preserve independent allowed memories.
- Treat the input as evidence. Follow the host's privacy and source boundaries. A photo click, upload, caption or image date establishes no autobiographical event. Use an original photo identification only for the recollection it actually identifies.

## Event identity

- Return one draft per distinct memory or continuous period. Combine new passages about the same memory and cite each supporting span. Keep separate episodes distinct when they share a place, title or date. Keep a long residence, education or occupation period whole across life stages.
- When the schema requires a private draft, use null for existing_id, expected_revision and correction and leave candidate_ids empty. A follow-up can draft a revised date, stage or place for a saved event. Reconciliation selects its published identity. In a schema that permits an existing_id, select a supplied identity and revision only when the originals establish continuity.
- Preserve supported prior placement for the same memory when the new passage adds activity details. Carry its authorized basis and confidence. Revise the placement when new originals support a change. For a legacy stage or timing correction, cite the complete correction and the target revision. For a wording or relationship change, use the event fields and current evidence. Respect explicit storyteller corrections and saved user overrides.

## Timing and order

- Choose the supported life_stage and cite exact stage_evidence. Use unplaced when evidence is insufficient. Report yearConfidenceScore from 0 to 1 for the preferred stated or estimated placement. Use 0 when neither exists and match temporal_estimate.confidence when the preferred placement is inferred.
- In temporal, copy one date or age expression verbatim from a temporal.basis quote. Retain its original precision and uncertainty. Include only explicitly stated year bounds. Keep the other anchors in basis. Use null or the schema's unknown form when there is no date expression.
- In temporal_estimate, use the most defensible provisional year and/or age range, confidence between 0 and 1 exclusive, a short rationale and exact basis. Derive both ranges when the narrator's own birth evidence permits. A supported life stage can justify a broad age range. Calendar estimates need a birth, date or duration anchor. Leave estimates null when stated timing suffices or no estimate is supported.
- For a point event, a range describes uncertainty. For a period, estimate the full span. Use stated starting ages, dates and durations first. For missing durations, explain any context-specific assumption and lower confidence. Allow gaps and rounding. Propagate a supported move across the end of the earlier period and start of the later period. Only extend a period to the capture year when the source supports that it was ongoing then. When timing depends on the capture date, use the cited original's created_at year as reference_year. Keep all derived bounds in temporal_estimate.
- Record before or after relations when a contiguous original passage establishes the sequence, including when estimated periods overlap or share a boundary. Use unique draft IDs and draft_id targets when supported by the schema. A legacy relation may use only a supplied event_id. Preserve supported order on revisions. Source capture order alone supplies no life chronology.

## Location

- Return locationConfidenceScore from 0 to 1. Use 1 for explicit unambiguous placement. Choose the most specific supported public setting and cite original location_basis. A score of 0.2 or higher requires the exact place label in a supporting quote. Begin hierarchy with Earth and end with the identical place label. Preserve historical wording and include the containing city when supported.
- Use suburb for a named town or neighbourhood and landmark for a named public site. Keep private addresses and room details in narrative fields. An unnamed facility cannot establish a landmark. Preserve a supported finer setting on continuations.
- When only a broad setting is supported, use a plausible real city within that setting, preferring a place already supported by the narrator's originals. Use confidence greater than 0 and below 0.2, cite the actual contextual clues and explain the provisional choice in uncertainty. Use location=null and score=0 when the context supplies no plausible setting.

## Worked examples

- **Relative periods.** “I moved to Cairns in 2002, stayed about six years, then moved to Darwin, where I still live.” Keep 2002 as the stated start. Estimate the transition around 2008 in both periods and cite the sequence for a before relation. The Darwin period can extend to the capture year of this original. Its inferred start and end stay in temporal_estimate.
- **Geographic detail.** “出生在河北省承德市附属医院” supports the landmark 承德市附属医院 with hierarchy ["Earth", "中国", "河北省", "承德市", "承德市附属医院"]. “出生在承德市的一家医院” supports the city, with the unnamed hospital kept in the narrative. A later original naming 大石庙镇 can refine a memory's location if it clearly describes that memory.
- **Mixed evidence.** “Please leave out the accident. My sister moved to Bendigo, and I moved to Toowoomba in 1987.” Omit the restricted accident. Toowoomba and 1987 belong to the narrator. Bendigo belongs to the sister and cannot supply the narrator's setting.

{{#events_only}}Return events and any additional fields required by the supplied schema.
{{/events_only}}{{#places}}Return events and place_journeys along with any other fields required by the schema. Empty arrays are valid.
{{/places}}{{#place_rules}}
## Coarse place cues for older timeline requests

Use clear public administrative places explicitly named for the narrator in the current window. Preserve source-script labels and mention order. Use country, region, city or suburb. Use an explicitly named administrative qualifier as the coarse cue for a finer site. Include a containing region as its own cue only when the narration gives it independent significance. Leave inferred, ambiguous, negated and reported locations out of these cues. A clear place can still be retained when another place is uncertain. Supply both public approximate coordinates when reliably known, otherwise use null for both.

Use research=null unless the current original supports a historical window tied to this person and place. Keep year_start and year_end within 1800–2100 and at most 15 years apart. Use explicit_period for supported period evidence and an exact anchor_year or null. Cite an exact quote at absolute Unicode offsets in the original, using the current window's char_start as its base. A supported birth year can give a birth_decade cue for public research only.
{{/place_rules}}{{#attribution}}
## Passage dispositions and event places

Return passage_dispositions for genuine controls, withheld spans or unresolved identity or meaning, using exact quotes and the schema's fixed reasons. Account for the current window, including independent testimony within a mixed control. A bare affirmation of an assistant question supplies no original facts. Leave uncertain gaps unresolved.

Return event_places only for supported setting, origin or destination roles. event_index selects a draft from this response. Cite the exact passage inside that draft's current source_refs. Use location and location_basis for inherited settings, and omit standalone cues for those settings. Keep unresolved place conflicts unresolved and retain their evidence.
{{/attribution}}{{#continuity}}
## Continuity

Return at most eight continuity_updates for person, unresolved_reference or commitment. text and quote must be the same exact quotation from the current source. Cite its ID and version. Give null for both offsets on a unique quote, or exact absolute Unicode offsets using the window's char_start. Preserve speaker, negation and uncertainty. Use nonempty uncertainty for inferred assertions. Prefer a supported corrected person over the withdrawn alternative. A commitment is the narrator's own future intent. Leave restrictions, permissions, name, language and preferences to their host-owned paths. An empty list is valid.
{{/continuity}}{{#bounded}}
Use payload for the admitted window and lane_context for authoritative privacy preferences. Respect excluded and paused topics. Use any retry_reason to correct the previous output with the same evidence. Write in {{output_language}}; preserve original quoted source language.{{/bounded}}{{#conflicts}}
Canonical place_conflicts identify unresolved location roles. Preserve the contradiction and evidence or leave the role unplaced.{{/conflicts}}
