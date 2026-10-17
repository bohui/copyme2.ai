

Focused author-timeline recovery pass:
- The first extraction did not produce an accepted author-timeline update. Re-read only the current storyteller message.
- Return only one MEMORY_SPARK_AUTHOR_TIMELINE marker when the message explicitly adds or corrects an author event or life period; otherwise return an empty string.
- Birth, childhood, age, season, move, work, care, visit, and correction statements are eligible even without a calendar date. Use date_expression `unknown` and precision `unknown` when needed; never let a profile or place fact suppress a clear event.
