

Focused family-tree recovery pass:
- The first extraction did not produce an accepted family-tree update. Re-read only the current storyteller message and the saved Family document.
- Return only one MEMORY_SPARK_FAMILY_TREE marker when the current message explicitly adds a person, person detail, family title, relationship, or correction; otherwise return an empty string.
- Do not let a profile, place, or timeline fact suppress an explicit family-tree item, and do not invent a relationship.
- Kinship titles and explicit shorthand such as `my father`, `my mother`, `my parent`, `my sister`, `my brother`, `my partner`, `my child`, `Mum`, `Mom`, `Dad`, `Gran`, or `Grandma`, as well as any grandparent detail, are explicit family-tree items even when a similar person already exists in the saved document. Preserve the title and current-turn detail in a person introduction; use an existing_id only when the saved context clearly identifies the same person. Never skip the marker just because the turn also contains an author-timeline event.
- For a current message such as `At about three, I followed my father to the docks`, emit a family marker for the explicit father/parent item and a separate timeline marker is handled by the other pass.
- For a current message such as `Mum grew mint beside the laundry`, emit a family marker for Mum with that grounded introduction; do not treat the shorthand as an unneeded duplicate of `parents`.
