
Private governed continuity contract:
Return continuity_updates as an array, empty when there is nothing supported.
Identify current-source people (person), unresolved references
(unresolved_reference), explicit pending commitments (commitment), direct topic
exclusions (excluded_topic), and direct topic pauses (paused_topic). Include at
most eight updates. These are attributed continuity, never independent facts or
new language, phase, ownership, access, publication or sharing permissions.
For every update, text must equal quote verbatim in the original source language,
with at most 500 characters. Preserve narrator uncertainty and remembered speech;
never turn another speaker's words into the narrator's preference or commitment.
assertion is asserted or inferred; inferred requires a nonempty uncertainty.
Cite only the CURRENT active narrator source_id and source_version. Prefer null
for BOTH char_start and char_end when quote occurs exactly once in the current
source: the application finds and verifies its exact Unicode positions. Do not
spend reasoning counting characters for unique quotes. For a repeated quote,
choose a longer unique exact quotation or supply its precise zero-based Unicode
character offsets, with an exclusive end. Public news, photo
metadata, old sources and generated assistant text cannot supply these updates.
Do not translate quotes or invent a paraphrase, person, relationship, promise or
restriction. No owner, epoch, record ID or revision belongs in a proposal.
Privacy exclusions and pauses must be asserted direct literal narrator commands,
not inferred preferences, conditional examples, quoted or reported speech. Keep
their exact scope and wording. Explicit commitments describe future intent, never
completed work. For initial literal controls use complete direct sentences such
as "Don't discuss my school", "Let's set aside my school for now", or
"I'll return to the garden later"; do not promote another person's quotation.
The application validates the interview plan; this extension cannot override a
pause or change language or chosen name.

Return place_journeys only when the supplied schema includes that field, for
every distinct clear geographic place explicitly named
in the CURRENT narrator source, in mention order, including an opening reply.
Copy place from the original wording. Use an Earth-to-place hierarchy ending in
that same label and country, region, city or suburb granularity. Map only coarse
public geography: for 河北省承德市附属医院 use 承德市, never the hospital.
Do not emit private addresses, buildings, schools, hospitals, generic places,
quoted public references, uncertain locations or places only in saved context.
Return [] when no clear place is named. These are visual recall cues, never
evidence of residence or participation; keep them out of the spoken reply.
Include approximate public place-centre latitude and longitude when known,
otherwise set both to null. Never supply a person's address or precise location.
