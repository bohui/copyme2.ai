---
name: memoir-memory-context
description: Connect an explicitly recalled place to the storyteller's life stage and capture an explicitly requested timeline avatar style during typed or transcribed memoir conversation.
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

Capture `avatar_style` as male or female only when the storyteller explicitly
requests that illustration style or explicitly identifies that gender for their
own timeline. Spoken words transcribed from voice use the same rule as typed words.
Do not infer gender from a name, pitch, accent, photograph, or birthplace. Omit an
unknown preference; do not ask a gender question merely to choose artwork. The
profile menu lets the storyteller change the artwork at any time.

Example after “I grew up in Chengde; use the female timeline pictures”:

```text
[[MEMORY_SPARK_PROFILE]]{"avatar_style":"female","story_focus":{"where":"Chengde","life_stage":"childhood"}}[[/MEMORY_SPARK_PROFILE]]
```

The workspace preserves different places under each stage. Public reference pictures
are reminders, not personal evidence. Do not claim an external photo depicts the
storyteller or their family. Use only the approved photo service's returned sources;
never invent image URLs, dates, or attribution.
