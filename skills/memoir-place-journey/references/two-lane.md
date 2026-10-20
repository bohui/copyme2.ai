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
