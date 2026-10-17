

Timeline source-claim association contract:
- The source claims below are private routing metadata. For every author-timeline item, include `source_claim_id` with the exact claim id that supports that item.
- Do not infer a claim id from a title synonym, a shared noun, or a shared date. If one item cannot be associated with exactly one source claim, omit that item instead of guessing.
- Keep timeline items in source-claim order. Never use the recording instruction itself as the source claim for an event. The application strips this private field before persistence.
