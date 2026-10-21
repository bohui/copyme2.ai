# memoir-place-journey: canonical two-lane extraction

Run the place-journey workflow within the same bounded timeline extraction pass.
Return geographic cues in the required `place_journeys` JSON array, not as
chat text or control markers. An empty array means this source has no clear
place cue; do not omit the field.

Use only places explicitly named in the current narrator source. For each
distinct clear country, region, city, suburb, town or named administrative
district, copy the place label in the source script and give its containing
geographic hierarchy from literal `Earth` to that same label. Preserve mention
order. A qualifier is part of its descendant's hierarchy, not a separate cue:
`河北省承德市附属医院` yields `承德市` with hierarchy
`["Earth", "中国", "河北省", "承德市"]`. Hospitals, schools, streets, compounds,
generic locations, prior profile places and public reference locations do not
create cues. Treat 大石庙 as a possible administrative town name, including
承德市双桥区的大石庙镇, rather than assuming it names a temple. Preserve the
source label: a bare 大石庙 stays 大石庙; 大石庙镇 stays 大石庙镇. Use a containing
hierarchy only when reliably resolved. If the intended place is uncertain or
conflicts with the narrator's other details, omit only that cue and add one
prepared_questions entry with requires_confirmation=true and its exact source
quote. A proposed location belongs in the clarification as a possibility until
the narrator confirms it. Keep extracting the other clear places.

Use granularity `country`, `region`, `city` or `suburb`; towns and named urban
districts use `suburb`. Set both latitude and longitude to approximate public
administrative centres when reliably known, otherwise set both to null. Never
infer a person's address or treat a map cue as biographical evidence.

Place assertions are per cue: distinguish narrator experience from reported speech, negation, hypotheticals and uncertainty. An unrelated uncertain town must not suppress a clear place. Include a broad region as an independent cue only when the narrator gives it independent significance, rather than as an address qualifier.

For each place, return research=null unless its accepted source supports a bounded historical research window. Otherwise return research with year_start/year_end (1800–2100, width at most 15 years), anchor_year (exact supported year or null), basis (explicit_period or birth_decade), and an exact quote with zero-based char_start/char_end in the current source. Bind dates to this place and person, not a nearby place or relative. For the narrator's birth year a decade window may be used solely as a public reference search cue; it is not an event date or a residence assertion. Preserve date uncertainty by leaving research null when no safe window is supported.

Research quote offsets are absolute in the accepted original source. For a bounded source window, its char_start is the base offset; do not reset offsets to zero at each window.
