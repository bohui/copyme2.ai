

Focused place-journey recovery pass:
- The first extraction did not produce an accepted place journey for a clear place in the current storyteller message.
- Return one valid MEMORY_SPARK_PLACE_JOURNEY marker for every distinct, clear coarse geographic place named in the current message, in mention order.
- Do not map a private address, building, school, hospital, station, generic place, quoted/public-history-only place, or explicitly uncertain place; return an empty string for those.
- Ground every marker in the current message. Do not reuse a saved place merely because it is nearby or already in context.
