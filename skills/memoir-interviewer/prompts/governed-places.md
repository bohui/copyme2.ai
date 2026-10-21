Return place_journeys for every distinct clear geographic place explicitly named
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

Place assertions are per cue: distinguish narrator experience from reported speech, negation, hypotheticals and uncertainty. An unrelated uncertain town must not suppress a clear place. Include a broad region as an independent cue only when the narrator gives it independent significance, rather than as an address qualifier.

For each place, return research=null unless its accepted source supports a bounded historical research window. Otherwise return research with year_start/year_end (1800–2100, width at most 15 years), anchor_year (exact supported year or null), basis (explicit_period or birth_decade), and an exact quote with zero-based char_start/char_end in the current source. Bind dates to this place and person, not a nearby place or relative. For the narrator's birth year a decade window may be used solely as a public reference search cue; it is not an event date or a residence assertion. Preserve date uncertainty by leaving research null when no safe window is supported.

Research quote offsets are absolute in the accepted original source. For a bounded source window, its char_start is the base offset; do not reset offsets to zero at each window.
