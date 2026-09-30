# Trigger selection and progressive composition

## 1. Default free-preview routing

The default heuristic counts **distinct, eligible narrative events** per source-grounded period. Counts of messages, photographs, assistant summaries and duplicate memory records must not inflate it. Generic profile fields such as a birth year do not by themselves constitute a narrative period.

```text
No eligible personal event:
    insufficient_context

At least three represented, grounded periods
and no single period contains 65% or more of placed events:
    sample_storyline

Otherwise:
    sample_chapter, focused on the richest coherent period
```

The 65% threshold is an editorial default, not a scientifically validated maturity or quality score. Equal event counts do not mean equal narrative value. Verify whether the chosen result really matches the material. If a human requests a different supported preview, record an explicit supported preview preference in the host-supplied policy; do not invent events to satisfy the heuristic.

With two periods, the automatic default is a focused sample chapter. An explicitly selected `policy.preview_preference: sample_storyline` can request a partial two-period overview; the host must record that user/editor preference. It still requires at least two grounded periods. `sample_chapter` can explicitly request a focused excerpt. Leave the preference as `auto` for normal event routing. With only unplaced events, a coherent undated sample is acceptable, but do not claim an exact chronological location.

### Focused example

Five free rounds discuss a childhood courtyard, a shared bedroom, a food tradition and several memories from the same neighbourhood. The result is a sample chapter with a distinctive title. There is no fabricated school/work/migration outline just to fill the rest of a life.

### Broad example

Five rounds establish childhood in one town, first work in another period and a later move to Australia. The result is a short narrative overview plus proposed chapter titles in chronological order. The overview is not five disconnected chat summaries. It is also not a full chapter for every period with invented details.

### Thin context

If only one supported sentence is available, keep it short. Preserve the free source export. The product may provide a reviewable note and invite another detail later; the composer cannot force an extra paid session, secretly add a trial allowance or pretend a full preview was created.

## 2. Formal composition readiness

Three conditions matter: current authorisation, explicit readiness/creation request, and sufficient material for at least one honest chapter. “Enough material” has no minimum word count. The narrator may prefer a short book with one episode. Gaps can remain gaps.

A conversation such as “I think that is most of my story; please turn it into a memoir” is a user request. The host records its confirmation reference. A model estimate such as “coverage is 82%” is not. Neither is a disconnected client, long silence or an exhausted subscription.

Do not conflate composition with publication. Formal composition creates a whole **draft**, after which the user can correct names, select photographs, approve an edition and separately approve print proofs.

## 3. Chapter planning before drafting

Create an event table with canonical event IDs, personal evidence, approximate timing, place/person associations and media references. Resolve duplicate events, not just identical sentences. Repeated discussions of the same factory job should enrich one event rather than look like five jobs.

Build a chronological order from explicit dates and before/after relationships. Overlapping uncertain intervals do not imply a precise order. Keep that uncertainty in period labels; choose a readable provisional sequence with a review note rather than invent dates. Any ordering cycle becomes a review issue.

Group events by coherent transition, not a predetermined life-stage template. The seven-stage life navigator can remain a UI index while the actual book has four, nine or another justified number of chapters.

Each outline entry should answer: what period is covered, what makes this stretch meaningful, which events support it, what title fits, which photographs might help, and whether the draft can be written now. Titles must not imply unsupported events or emotions. A plain accurate title is preferable to a memorable invented one.

The sample and formal plans share stable chapter IDs where the scope is genuinely the same. A renamed title retains its ID. A merged or split scope needs explicit lineage and event reassignment. Do not renumber every identifier when an earlier memory arrives; change display order only.

## 4. Progressive update strategy

Persist a source/version inventory and dependency graph. A high-water chat cursor alone misses edited older messages, corrected transcripts, revoked photos, changed captions and consent withdrawals.

| New input | Expected edit |
|---|---|
| Extra detail about the same event | Integrate into its existing paragraph; remove redundant phrasing |
| A distinct event in an existing period | Add a relevant paragraph/section; reconsider weaker repetitive detail |
| An earlier or later life period | Propose a new chronologically placed chapter when supported |
| Confirmed name/date correction | Update affected text, headings, captions, summary and timeline; invalidate translated descendants |
| Contradictory family account | Preserve attribution/uncertainty; flag a review choice rather than choosing a silent winner |
| New photograph | Resolve asset, rights and caption evidence; place near its event without rewriting unrelated chapters |
| Source/media revocation | Stop reuse, mark dependent outputs ineligible, and request safe revision/review |
| Approved chapter affected | Retain the approved bytes and save a replacement proposal against the exact revision |
| No relevant change | Reuse prior result or unchanged revisions; do not invent enrichment |

A correction is not automatically superior merely because it is newer. The host must identify a correction decision or supersession. Independent conflicting accounts remain separately attributed. AI drafts never supersede originals.

### At the word ceiling

Use the source/event index as the archive, not the chapter. When new material arrives near 7,000 words, first remove duplication, shorten tangential transitions and combine repetitive accounts. If distinct episodes still deserve full treatment, propose a meaningful chronological split. Put omitted-but-preserved events in `deferred` dispositions with reasons. Never dump all overflow into an oversized notes section.

### Example of growth without sprawl

Round 1: a short childhood chapter from three details.
Round 2: integrate a new school journey and one personal photograph.
Round 3: a date correction replaces earlier uncertainty after confirmation.
Round 4: extensive material about leaving home justifies a second chapter rather than pushing the first beyond its limit.

A later chapter can be shorter than its earlier revision if editing makes it clearer while preserving the important account. Word count is not a completion score.

## 5. Summaries and cross-skill memory

Separate three outputs:

1. Source summary: compact, evidence-linked facts and uncertainty for retrieval.
2. Editorial plan: chronological outline, chapter purpose and source assignments.
3. Reader manuscript: enjoyable prose with technical provenance stored separately.

Do not place tool instructions, unresolved debug notes or internal confidence scores in the memoir. Do not erase uncertainty when compressing a summary. A derived memory without original sources is a lead to retrieve, not an authorised fact.

The summary should be refreshed incrementally from originals and explicit accepted corrections. It may point to detail in the source registry instead of carrying every sentence. All items retain origin and actor so a contributor's account is not mistaken for the storyteller's recollection.

## 6. Optional interview feedback

Return a small queue of specific questions tied to real gaps, for example a missing name or whether a photograph belongs to a particular event. Prioritise questions that would materially improve accuracy, placement or clarity. Respect muted topics and avoid leading premises.

Full composition should not be held hostage to optional questions. Provide a readable version with uncertainty or omission where possible. The user-facing completion message may offer one optional question, while the rest remain in the application's queue.

## 7. Review and publication separation

Deterministic validation is necessary, not sufficient. It confirms reference resolution and exact quotation, but cannot tell whether “I always loved the factory” is supported merely because it cites a sentence about working there. A separate evidence-to-prose check must flag invented feelings, motives, chronology and relationships.

When review finds an unsupported detail, remove it or ask for clarification; do not search external history to retrofit support for a personal memory. Rights and access failures cannot be fixed by narrator approval alone.

Chapter review, edition approval and print proof approval are distinct application actions. A formal draft label must never be interpreted as approval for printing.
