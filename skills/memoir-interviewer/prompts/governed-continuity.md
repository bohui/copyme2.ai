
Private governed continuity contract:
Return continuity_updates, [] if none, at most eight. Kinds are person,
unresolved_reference, commitment, excluded_topic or paused_topic.
Cite only the CURRENT active narrator source_id and source_version. text and quote
must be the same exact original-language quotation, at most 500 characters.
Preserve speaker attribution and uncertainty: asserted or inferred; inferred
requires nonempty uncertainty. Do not paraphrase or translate a quotation.
For 我叫小林, text=quote="我叫小林"; the extracted name 小林 alone is not that quote.
For a unique quote, use null for BOTH char_start and char_end; the application
finds the Unicode span. For repeated text, choose a longer unique quote or supply
exact zero-based Unicode offsets with exclusive end. Do not count unique quotes.
Old sources, assistant replies, public news and photo metadata cannot support
updates. No owner, epoch, record ID or revision belongs in a proposal.
A commitment is explicit future intent, not completed work. Privacy exclusions
and pauses must be asserted direct literal narrator commands, never inferred,
conditional, quoted or reported speech. Preserve the complete scope and wording;
another speaker's words cannot become narrator preferences or permissions.
These updates grant no access, language, strategy, publication or sharing authority.

Return place_journeys only when the supplied schema includes that field.
Use each distinct clear CURRENT geographic place in mention order, with an
Earth-to-place hierarchy ending in its original label and coarse country, region,
city or suburb granularity. For 河北省承德市附属医院 use 承德市, not the hospital.
No private addresses, buildings, schools, hospitals, generic/uncertain locations,
old context or public-reference quotations. A place cue is not residence or
participation. Approximate public place-centre coordinates may be supplied when
known; otherwise both are null. Return [] when no clear place is named.
