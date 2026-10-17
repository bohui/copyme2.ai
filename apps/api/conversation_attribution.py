"""Quotation and attribution patterns shared by current-intent guards."""

# Mask quotes across line/sentence boundaries, preserving a completed sentence
# so a subsequent direct request still belongs to the current narrator.
QUOTED_SENTENCE_PATTERN = r'"[^"]*[.!?。！？]\s*"|“[^”]*[.!?。！？]\s*”|‘(?:[^’]|’(?=\w)|(?<=\w)’(?=[ \t]+\w))*[.!?。！？]\s*’|「[^」]*[.!?。！？]\s*」|『[^』]*[.!?。！？]\s*』|`[^`]*[.!?。！？]\s*`'
QUOTED_PATTERN = r'"[^"]*(?:"|$)|“[^”]*(?:”|$)|‘(?:[^’]|’(?=\w)|(?<=\w)’(?=[ \t]+\w))*(?:’(?!\w|[ \t]+\w)|$)|「[^」]*(?:」|$)|『[^』]*(?:』|$)|`[^`]*(?:`|$)'
# Word/possessive apostrophes stay inside a quoted span. A sentence-ending
# quote can close next to Chinese text, which does not require a space.
QUOTED_SENTENCE_PATTERN += r"|(?<!\w)'(?:[^']|'(?=\w)|(?<=\w)'(?=[ \t]+\w))*[.!?。！？]\s*'"
QUOTED_PATTERN += r"|(?<!\w)'(?:[^']|'(?=\w)|(?<=\w)'(?=[ \t]+\w))*(?:'(?!\w|[ \t]+\w)|$)"
ATTRIBUTION_PATTERN = r'\b(?:said|says|told|asked)\b|(?:说|說|告诉|告訴)'
