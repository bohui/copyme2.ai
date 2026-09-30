# Editorial policy and measurable length

## 1. Voice

Write as the storyteller, not as a generic motivational biographer. Preserve their diction, sense of humour and perspective. Smooth transcription disfluency and avoid repetitive question-and-answer formatting unless requested. Choose concrete source-supported details over elaborate adjectives.

Do not make an ordinary event more dramatic by adding dialogue, weather, embarrassment, courage, happiness, destiny or moral growth. A warm memoir can contain uncertainty, grief, frustration and unresolved relationships. The user's goal is a peaceful and fulfilling process, not compulsory cheerful prose.

No universal formula requires a dramatic opening, struggle, success and a life lesson in every chapter. A small coherent memory can have a simple ending.

## 2. Meaningful titles

A title should identify a memorable event, place, object or change found in the evidence. Avoid repetitive labels such as “My Journey, Part 1” when a real detail is available. Do not manufacture specifics for a better title.

Titles can be gently editorial without adding facts. “My First Wages” requires evidence of first wages. “The Red Door” requires that the door was red. “A New Beginning” should not assert an emotional interpretation absent from the speaker. Store the title's source anchors or keep it clearly general, such as “The Years I Remember”.

## 3. Chronology and facts

Remembered event date is distinct from chat, upload or recording date. Preserve approximate years, decades and before/after relationships. Do not silently translate a lunar date into a Gregorian date. The library helpers enforce the supplied period order, not historical truth; the agent and reviewer must verify how that order was obtained.

Use family testimony with attribution. Do not infer a person's name, relationship, gender, age, ethnicity, health or political views from a photo. A family relationship glossary is a source of candidate spellings and established links, not permission to resolve every “uncle” automatically.

Keep original evidence available by ID and immutable version. Generated memory summaries and previous chapter prose are navigation aids; they are not independent support for themselves.

## 4. Photos

Use only registered assets allowed for the target audience and medium. Captions must preserve uncertain identity/date/place. A generic descriptive caption may be used without implying an event. File upload date is not photo capture date.

The prototype renderer intentionally emits photo slots so the host can resolve real assets under current access. It never fetches an image from an arbitrary URL. Image metadata in synthetic fixtures is illustrative; no actual family photograph is included in the package.

External historical media must be explicitly identified as context, not a personal photograph. Rights to embed in an app do not automatically imply download or print rights. This skill does not generate new historical pictures or search online for substitutes.

## 5. The chapter ceiling

**Required policy: every chapter is at most 7,000 counted words.** Equality is allowed; 7,001 fails. No target length must be reached. A recommended working ceiling of 6,000 leaves space for later editing, captions and translation.

The counter is `intl-segmenter-wordlike-v1`:

```js
let words = 0;
for (const item of new Intl.Segmenter(locale, {granularity: 'word'})
  .segment(text.normalize('NFC'))) {
  if (item.isWordLike) words++;
}
```

This uses the runtime's language-aware segmentation rather than splitting on spaces. English apostrophes, compounds and Chinese word boundaries follow ICU's segmentation; they need not match Microsoft Word or a human linguist exactly. The deployment's selected algorithm is the contractual measure for this limit.

Chinese is counted as segmented word-like units, **not** as whitespace-separated strings, model tokens or automatically as 7,000 Han characters. The report includes character counts as a second measure. A separate Chinese-character cap can be added later only as an explicit product policy, not by silently changing the user's word limit.

Count every authored, reader-facing chapter field: title, subtitle/period label, headings, paragraphs, quotes, image captions, credits, alternative text (conservatively even if not printed), historical context and editorial notes. Do not count IDs, source registry text, tool metadata or a private source summary as chapter prose. Do not render that private metadata as an uncounted appendix.

One combined bilingual chapter counts both languages. Separate translated editions have their own independent chapter validations. An outline-only overview is not a loophole: its storyline plus outline titles also stay under 7,000 words.

The root book title is limited by the validator to 40 word-like units so an enormous title cannot be used as extra narrative. This is a formatting safeguard, not a memoir-length target.

## 6. Counter reproducibility

The utilities require Node.js with full `Intl.Segmenter` support; there are no npm dependencies. This bundle was tested on Node `v22.16.0`, ICU `77.1`. That describes the test environment, **not a recommendation to pin an old security patch in production**. Choose a supported patched runtime, regenerate the synthetic fixtures once, and pin that deployed image's Node/ICU versions.

The prepared plan returns `counter` metadata. Copy it into candidate output; do not invent it. Validation rejects a candidate counted on a different runtime. After a runtime upgrade, rerun tests and review counts before accepting new or previously near-limit chapters. Existing approved bytes remain archived; a new release still needs current validation.

Source quote matching uses the original string and Unicode code-point offsets. It does not use word-counter normalisation. Do not use JavaScript UTF-16 offsets as though they were code-point offsets.

## 7. Overflow repair order

First remove repeated accounts, repetitive openings and conclusions. Next condense secondary details while retaining the core episode. Then reorganise paragraphs and reduce unnecessary context sidebars. If the material still needs more room, propose a chronological split with stable lineage and meaningful titles.

Never truncate a string at the limit, remove important attribution to save words, fabricate a shorter exact quote, push details into unreadably small captions, or append unlimited “extra memories” after the chapter. Deferred events remain in source storage and the event-disposition ledger for later use.

For protected prose, the skill supplies a proposal and flags the oversized active chapter; it cannot silently publish a shorter replacement. Structural or access restrictions are enforced by the host before any release.

## 8. Review checklist

Check narrative coherence, chronology, source support, quoted wording, uncertainty, family contribution attribution, duplicate anecdotes, caption identity/date accuracy, translation consistency, privacy, media capabilities and measured length. Check that the wording sounds like this storyteller rather than the default style of the model.

The automatic validator checks deterministic constraints only. Its success means the candidate can enter editorial review; it does not certify factual truth, legal permission, model quality or publication readiness.
