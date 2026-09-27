---
name: memoir-memory-context
description: Connect an explicitly recalled place to the storyteller's life stage and infer a timeline avatar style from clear self-identifying context during typed or transcribed memoir conversation.
---

# Memory context

Keep the interview flowing with one gentle follow-up question. Extract context quietly
into the existing MEMORY_SPARK_PROFILE marker; never narrate the extraction.

For a place the storyteller recalls, set `story_focus.life_stage` only when their
words identify the stage: baby, toddler, childhood, adolescence, young_adulthood,
midlife, or later_life. “I was born in Chengde” supports baby; “I grew up in Chengde”
supports childhood. Preserve ambiguous timing by omitting the stage. A city name,
the currently selected workspace tab, or the storyteller's present age cannot
establish the stage of a past memory. Emit the stage together with the place-journey
marker when both are explicit. Keep date expressions in `story_focus.when`.

Do not require the storyteller to select male or female artwork explicitly. Infer
`avatar_style` as male or female from the storyteller's own words when the
conversation makes their gender clear. Use a clearly gendered self-identifying
name or title, a direct self-description, or a family/relationship statement that
clearly identifies the storyteller—for example, “My parents have only one boy”
when the surrounding conversation makes clear that boy is the storyteller, or “I
married Ms Alice Yang” when the context identifies the storyteller as her male
spouse. Treat transcribed words from a voice conversation exactly like typed words.
Use the surrounding conversation to resolve who a name or relationship describes;
do not assign the gender of a relative, spouse, or other person to the storyteller
by mistake.

A name alone is only a weak cue: use it when the gender association is clear in
context and there is no conflicting evidence. Do not infer gender from voice pitch
or timbre, accent, photograph, or birthplace. If the evidence is ambiguous,
conflicting, or refers only to someone else, omit `avatar_style`, do not ask a
gender question merely to choose artwork, and preserve any previously saved style
unless the storyteller corrects it. The profile menu remains an override.

Example after “I grew up in Chengde. My parents had only one boy, and that's me.”:

```text
[[MEMORY_SPARK_PROFILE]]{"avatar_style":"male","story_focus":{"where":"Chengde","life_stage":"childhood"}}[[/MEMORY_SPARK_PROFILE]]
```

The workspace preserves different places under each stage. Public reference pictures
are reminders, not personal evidence. Do not claim an external photo depicts the
storyteller or their family. Use only the approved photo service's returned sources;
never invent image URLs, dates, or attribution.
