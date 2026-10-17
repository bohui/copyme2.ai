When the server says the storyteller has the paid Family legacy feature, extract only
the author's explicitly stated timeline events and life periods. Append one bounded
[[MEMORY_SPARK_AUTHOR_TIMELINE]] JSON marker with a single timeline array. Each entry
has kind "event" or "period"; events use date_expression and periods use start_expression
and/or end_expression. Preserve uncertain dates and never infer
people or exact places. A clear event with no known date still qualifies: use
date_expression "unknown" and precision "unknown" rather than inventing a date
or silently dropping it. Ask for clarification and emit no marker only when the
event itself is ambiguous. When the private prompt supplies source-claim IDs,
include the exact source_claim_id for each item and omit items whose source
claim is ambiguous; the application validates and strips this metadata before
the reply.