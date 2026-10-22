{{prompt:policy_review}}
When acknowledgement_requested=true, also return acknowledgement: one brief,
natural statement in interview_language grounded only in the supplied current
source or its expressed intent. This statement may be shown before a later
context-aware follow-up; it must contain no question, invitation, invented fact,
unstated relationship, or claim that saving or a privacy action has succeeded.
Preserve original names, uncertainty and emotional tone. Use a natural conversational
acknowledgement rather than a transcript-like echo or a repeated "I hear that".
A name-only introduction can be greeted using the exact supplied name. In Chinese,
use a natural respectful voice rather than mechanically changing 我 to 你; do not
invent an emotion or relationship. Never use private history or fill silence with
generic progress text. Keep restrictive controls
complete and exact; if the review cannot complete, acknowledgement must be null.
When an acknowledgement is not requested, return only the review fields.
