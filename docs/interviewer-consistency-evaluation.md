# Interviewer continuity and stage breadth

The interviewer regression covers acknowledgement-only replies to pacing and
correction, and a negated alternative being proposed as asserted person
continuity. The selector's schema and validator now require the current-intent
reason and a follow-up question for a redirect, correction or pacing request.
A real direct question can still receive an answer without an interview question;
reported or quoted questions do not relax that constraint. Stop remains dominant.
The output schema retains a pause alternative even when the literal matcher finds
a correction or pacing request; the validator never forces a question over an
explicit stopped outcome. Common English and Chinese stop instructions are also
recognised before those overrides.

The interview context includes at most seven stage-coverage counts. A distinct
active canonical event counts only when it has a title, primary/stage evidence
from a current active original, no stale source dependencies and no source
exclusion. Raw turn counts and unplaced events do not advance this checkpoint.
Three events in the most recently evidenced stage permit one optional invitation
to another stage with less coverage. Later stages are suggested first, then
earlier gaps. This is an interview breadth heuristic, not a quality score, a
declaration that a stage is complete, or permission to compose/publish a memoir.

The shared interviewer guidance asks for a brief natural bridge and an optional
question. Explicit continuation, an unfinished anecdote, a correction, the user's
own question, redirect, distress or stop takes priority. It also protects
alternate names, uncertainty, conditional events and already answered questions.
Both the compact collector and strategy selector consume this shared guidance.

`scripts/interviewer_conversation_cases.py` builds one exact prefix per active
source from an explicitly selected local export, plus eight labelled
counterfactual probes. The observed prefixes contain no future turns. Saved
replies are optional: an accepted original remains in later prefixes when its
response failed or was never saved. Every observed source requires an independently
reviewed control expectation (stopped, question, selection reason), bound to its
version and text hash. Missing or stale labels fail case creation; the production
literal intent matcher never generates gold. This permits indirect departures
such as needing to leave for an appointment to have valid stop gold. Stops and
direct answers have their own requirements instead of story-follow-up gold.
Saved assistant replies are context, not personal testimony or verified delivery
receipts. The additional dataset is
`memoir/evaluation/conversations/memoir-interviewer`; it is separate from the
stable synthetic 160-item catalog, and records private-data and origin metadata.
Raw conversation exports and hosted experiment artifacts stay in ignored `var/`.
Sending real excerpts to model/judge providers needs the owner's disclosure
approval; storing the requested dataset does not itself execute an evaluation.

Prompt Markdown is reviewed in Git before publication. Candidate evaluations
must identify draft source hashes and must not reuse old numeric versions for
changed content. Runtime receipt validation remains enabled. After merge to
`main`, the normal publisher creates real changed versions and refreshes receipts;
only then can normal runtime/pin checks pass for the changed prompt sources.
