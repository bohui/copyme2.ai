# Memoir craft assessment v1

This is an **offline manual assessment guide**, added after the October 25 live
comparison. It is not a model prompt, automated literary scorer, runtime review
schema or authority to publish. Its synthetic calibration labels are agent
authored and await independent semantic review. No new model or judge ran.

Assess the writing the author chose to make, using authorized originals, the
complete supplied passage and the author's stated scope, language and voice.
Grade the handling of available material, never the author's life, honesty,
trauma, willingness to disclose or worthiness as a subject.

## Two separate decisions

First record the existing hard gates: current consent/privacy/ownership,
source-grounded facts and relationships, attribution, uncertainty, source
versions and exact references, protected writing, bounded repair and successful
durable save/readback. A fluent passage still fails if it invents or contradicts
testimony. An unavailable gate is unresolved, not passed. Craft cannot clear a
failed gate, approve publication, or establish persistence.

Then assess craft. Supported arrangement, pacing, compression, transitions,
rhythm and clearly figurative language may improve prose without adding events.
Do not add dialogue, sensory observations, motives, emotions, diagnoses,
admissions, hindsight, causation, forgiveness or redemption for a higher score.
An optional interview suggestion is not new testimony or permission to rewrite.

## Stage and applicability

Record the checkpoint, intended output, author-selected scope (focused thread or
whole life), language, narrative viewpoint and any boundaries before scoring.

| Context | Appropriate expectations |
| --- | --- |
| Early checkpoint or thin originals | A faithful, readable passage or useful fragment. No completed arc, adult hindsight or forced lesson. |
| Focused sample/chapter | Coherence around the selected episode/thread, with scene or summary suited to the available evidence. |
| Whole-life memoir in progress | Coherent selection and links across periods. Do not impose a single theme or discard history to manufacture one. |
| Complete selected arc | Assess a transition only if that arc and the author's testimony actually support one. An unresolved ending is legitimate. |
| Childhood viewpoint | Preserve what the child knew/felt. Adult reflection is applicable only where the author supplies and wants that perspective. |

Each criterion receives `applicable`, `not_applicable` or
`insufficient_evidence`, with a reason. Use `not_applicable` for a stage/scope or
explicit author boundary; use `insufficient_evidence` when the desired judgment
cannot be supported by the available material. Both have a null score, not zero.
Do not infer a low score from absent disclosure or missing life experiences.
Where welcome, suggest one optional, non-leading follow-up; respect a refusal
without repeating the request. If material already exists, prefer an editorial
suggestion to an unnecessary interview question.

## Anchored craft scores

Use integer scores 0–3 **only for applicable criteria**. These anchors describe
the passage, not the person. No aggregate, weighting or passing total is used.

| Criterion | 0 | 1 | 2 | 3 |
| --- | --- | --- | --- | --- |
| Focus and structure | Arrangement obscures the author's chosen scope despite available links. | Relevant material is present but loosely ordered. | Selection and transitions sustain the chosen thread or whole-life sequence. | A distinctive structure deepens that chosen scope without narrowing or distorting it. |
| Scene craft and pacing | Available action/details are arranged so unclearly that the episode is difficult to follow. | Accurate but mostly list-like or unevenly paced. | Supported action/detail, scene and summary form a readable progression. | Precise, economical scene/summary choices create texture and tension from the evidence alone. |
| Distinctive author voice | Available authorial meaning/register is flattened or overwritten. | Readable but generic relative to supplied voice. | Vocabulary, rhythm, humour/formality and language fit this author. | A sustained, particular voice shapes the telling while preserving the author's meaning. |
| Supported vulnerability | The prose obscures or sensationalizes self-reflection the author chose to include. | Chosen self-reflection is acknowledged but handled mechanically. | Voluntary mistakes, limits or mixed feelings are treated candidly and proportionately. | Their treatment adds nuance without self-exoneration, punishment or pressure for more disclosure. |
| Retrospective reflection | The author's supplied distinction between experience and later understanding is obscured. | Supplied hindsight is appended without a useful connection. | Experience and explicitly supplied later perspective illuminate each other. | Their interplay adds layered meaning while retaining uncertainty and viewpoint boundaries. |
| Supported transformation | Available before/after material is arranged so its supported relationship is obscured. | A supplied change is reported but thinly connected. | An evidenced change, continuity or unresolved tension is clearly developed. | The supported arc has an earned, nuanced shape without a compulsory wiser self or redemption. |
| Reader resonance | Presentation obscures the available stakes or relationships. | The situation is understandable but its supported significance is distant. | Concrete, personal stakes make the experience accessible to another reader. | Particular details invite reflection beyond the episode without asserting a universal moral. |
| Fairness and contextualized attribution | Presentation flattens available perspectives or obscures who knows/claims what. | Attribution is accurate but available context is handled thinly. | Actions, reported experience and unknown motives are distinguished with proportionate context. | Complex or unresolved relationships remain legible without invented motives, forced sympathy or false equivalence. |

Fidelity failures are recorded as hard failures before these anchors. For
example, invented dialogue is not merely a low scene score. On a failed passage,
optional craft observations are diagnostic only and cannot become acceptance.

## Specific interpretation boundaries

- A narrow thematic thread is one valid author choice. A deliberately whole-life
  account may earn strong focus through selection, continuity and structure.
- Scene craft does not require dialogue or sensory description. Summary can be
  the best form for sparse evidence. A remembered paraphrase stays attributed;
  words supplied as recollection do not become independently verified verbatim
  historical speech. Exact quotation requires the supplied words and truthful
  framing of their provenance.
- Plain, restrained, regional or translated language can be a distinctive voice.
  Do not reward homogenized literary English over the author's chosen register.
- Vulnerability is voluntary. Do not demand an admission, discredit an account
  because the author is a victim, or invent a flaw to make a narrator seem fair.
- Reflection must come from the author. Do not infer an adult diagnosis,
  hindsight, lesson or motive from a childhood episode.
- Transformation is not mandatory at an early checkpoint, in an unfinished
  account or where the author chooses an unresolved ending. Continuity is not
  evidence of personal failure.
- Resonance comes from intelligible particulars and stakes; it does not require
  a universal truth, therapeutic conclusion or reader identification claim.
- Fairness does not sanitize abuse, excuse harm, require forgiveness or demand
  equal blame. State supported actions clearly; preserve attributed perspectives
  and uncertainty about motives. Context cannot be invented to soften a person.

## Assessment record and confidence

Keep a separate craft sidecar; do not add these fields to runtime `Review` JSON.
For a complete assessment include all eight criteria, each with:

- criterion ID and applicability; score 0–3 or null;
- exact reader-prose excerpts and exact original-source excerpts with their
  source IDs, versions and spans; for a missing feature, identify the relevant
  supplied span and describe the absence rather than inventing an excerpt;
- a short explanation tied to the criterion's anchor;
- confidence `high`, `medium` or `low`, and its basis;
- an optional editorial suggestion or author-welcomed interview follow-up.

High confidence requires a directly inspectable match and adequate relevant
context. Medium reflects a defensible judgment with limited context or a
language/register ambiguity. Low means the evidence is thin or the observation
needs another reader; do not use low confidence to certify a disputed fact.
An absent passage/source remains insufficient evidence regardless of confidence.
Excerpts establish what was reviewed, not automatic entailment or literary merit.

Bind the sidecar to rubric ID `memoir-craft-v1`, assessment type (human/agent/
controlled fixture), reviewer identity/version, locale, stage, author intent,
source manifest, input/output hashes and application/SQL receipt identities.
Record hard-gate outcomes separately. A complete report lists each criterion,
its evidence and uncertainty; it does not infer an overall quality pass from an
average or count of strong criteria. A weak craft observation is advisory and
must not itself cause invented material, mandatory disclosure or endless repair.

## Calibration, tests and comparison provenance

[Synthetic cases](../tests/evaluation/memoir_composer_craft_cases.json) contain
positive, weak-but-faithful, unsupported-but-fluent and policy-pending examples
in English and Chinese. Each targets named dimensions; these targeted examples
are not complete eight-criterion assessments or live scores. Labels are
provisional calibration material, not human-reviewed truth or an independent
entailment oracle. Independent review should inspect both the source and draft.

[Canonical seam tests](../tests/test_composer_craft.py) inject controlled reviews
to check that editorial weakness remains advisory, high craft cannot clear a
negative semantic verdict or privacy hold, and accepted prose stays unchanged.
They do not claim to detect invented facts or score craft without a reviewer.
Existing real PostgreSQL/worker tests retain the durable hard-gate coverage.

Offline validation for this addition: 15 targeted calibration replays passed;
the combined craft/review/legacy-refresh/composer-evaluation cohort passed 64
tests (26 unrelated evaluation cases deselected), with supervised cleanup
verified. Provider outputs were controlled fixtures. The runtime files are
unchanged from independently reviewed `9809236`; these checks are not a fresh
live run or a claim of automated literary judgment.

The managed automated composer judge, application prompts, runtime schema and
PR #133's two source files are unchanged. Its existing generic quality score
does **not** establish acceptance under this new manual rubric. Wiring a scored
automated judge would be a separate reviewed managed-prompt/contract change;
its publication and any paid judgments are not authorized here.

Keep the original live comparison, frozen inputs, transcripts and receipts
immutable. This rubric was added after that comparison; any assessment of those
old outputs must be a separately versioned **retrospective** sidecar applied to
both arms, with unchanged source/output hashes and blinded arm labels where
practical. It cannot retroactively become the original predeclared acceptance
rubric or erase the original failed/censored rows. Before an authorized new run,
freeze this rubric and stage/applicability rules for both arms and record its
hash alongside the existing scenario/route provenance. Judge-only green cannot
replace durable application evidence or independent semantic review. No renewed
live calls, judge spending, merge, publication or serving activation is implied.
