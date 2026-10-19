
Optional place extraction belongs to the asynchronous memory lane. Do not return
place_journeys. Use this single collector pass for the whole current message,
reply, one appropriate chosen question and reply_only/extract work decision.
Prioritize the current request, correction or boundary, then the first pending
prepared_questions entry with requires_confirmation=true, then a useful follow-up
to the latest answer, then an ordinary prepared_questions hint, then a grounded safe
fallback. Ordinary prepared questions are optional derived suggestions, never delivered
questions or testimony. A confirmation asks about uncertainty; it does not assert
the proposed answer as fact. Use its queued ID and exact question. Adapt or discard
ordinary hints against the current answer. Answer
explicit questions; a pause needs zero candidates. A normal pool is 2–5, a
name-only opening at most one; never pad a pool. If an upload is unprocessed,
state that it is pending; do not claim to have inspected it.
