"""Small versioned conversation preference, independent from life stage/access.

The identity adapter supplies an authorised project and accepted turn. Memory
checkpoint/identity migrations must preserve this envelope, not reconstruct it
from a generated summary. Reasons are public policy labels, never reasoning.
"""
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, model_validator

Phase = Literal['comfort', 'explore', 'shape']
Action = Literal['comfort', 'explore', 'shape', 'automatic', 'skip']
Reason = Literal['new_journey', 'saved_narration', 'narrator_choice', 'narration', 'skip']


class PhaseState(BaseModel):
    model_config = ConfigDict(extra='forbid')
    schema_version: Literal[1] = 1
    phase: Phase = 'comfort'
    selection: Literal['automatic', 'explicit'] = 'automatic'
    preferred_phase: Phase | None = None
    revision: int = Field(default=0, ge=0, strict=True)
    reason: Reason = 'new_journey'
    source_turn_id: UUID | None = None


    @model_validator(mode='after')
    def coherent_selection(self):
        if (self.selection == 'explicit') != (self.preferred_phase is not None):
            raise ValueError('Explicit selection requires a preferred phase')
        return self


class PhaseProposal(BaseModel):
    model_config = ConfigDict(extra='forbid')
    phase: Phase | None = None
    action: Action | None = None


def resolve_phase(state, proposal, *, source_turn_id=None, has_narration=False, expected_revision=None):
    """Resolve validated intent; persistence independently fences revision/turn.

    Callers establish explicit intent from a dedicated control or the current
    narrator message. Model-proposed automatic shape is never sufficient.
    """
    current = PhaseState.model_validate(state) if state is not None else PhaseState(
        phase='explore' if has_narration else 'comfort',
        reason='saved_narration' if has_narration else 'new_journey')
    proposal = PhaseProposal.model_validate(proposal)
    if expected_revision is not None and expected_revision != current.revision:
        return current
    action = proposal.action
    values = current.model_dump()
    if action in ('comfort', 'explore', 'shape'):
        values.update(phase=action, preferred_phase=action, selection='explicit', reason='narrator_choice')
    elif action == 'automatic':
        values.update(phase='explore' if has_narration else 'comfort', preferred_phase=None,
                      selection='automatic', reason='narrator_choice')
    elif action == 'skip':
        values.update(reason='skip')
    elif proposal.phase == 'shape':
        raise ValueError('Shaping requires an explicit narrator choice')
    elif current.selection == 'automatic' and current.phase == 'comfort' and proposal.phase == 'explore':
        # Narration can move guidance forward; returning to comfort is a
        # narrator choice. A correction must not restart a returning journey.
        values.update(phase='explore', reason='narration')
    # Replays and proposals which cannot change effective policy are no-ops.
    if all(values[key] == getattr(current, key) for key in ('phase','preferred_phase','selection')) and action != 'skip':
        return current
    values.update(revision=current.revision + 1, source_turn_id=source_turn_id)
    return PhaseState.model_validate(values)


# Complete control sentences only. These portable regexes and attribution
# rules are repeated in SQL for defence in depth.
CONTROL_PATTERNS = (
    ('comfort', r"(?:please )?(?:keep talking|keep it gentle|let's take it slowly)|(?:请)?(?:轻松聊聊|慢慢聊|随便聊聊|继续聊聊)"),
    ('explore', r"(?:please )?(?:explore my memories|explore a memory|let's explore|let's get straight into it)|(?:请)?(?:深入回忆|直接开始回忆|探索回忆|聊聊一段回忆)"),
    ('shape', r"(?:please |I want to |can we )?(?:shape my story|organize my story|organise my story|help me (?:shape|organize|organise|review) my story)|(?:请|我想)?(?:整理我的故事|帮我整理故事|回顾我的故事)"),
    ('automatic', r"(?:please )?(?:use automatic guidance|return to automatic guidance)|(?:请)?(?:恢复自动引导|自动引导)"),
    ('skip', r"(?:please |can we )?(?:skip(?: this question)?|try another topic|change (?:the )?topic)|(?:请)?(?:跳过(?:这个问题)?|换个话题)"),
)

# Mask quotes across line/sentence boundaries, preserving a completed sentence
# so a subsequent direct request still belongs to the current narrator.
QUOTED_SENTENCE_PATTERN = r'"[^"]*[.!?。！？]\s*"|“[^”]*[.!?。！？]\s*”|‘(?:[^’]|’(?=\w)|(?<=\w)’(?=[ \t]+\w))*[.!?。！？]\s*’|「[^」]*[.!?。！？]\s*」|『[^』]*[.!?。！？]\s*』|`[^`]*[.!?。！？]\s*`'
QUOTED_PATTERN = r'"[^"]*(?:"|$)|“[^”]*(?:”|$)|‘(?:[^’]|’(?=\w)|(?<=\w)’(?=[ \t]+\w))*(?:’(?!\w|[ \t]+\w)|$)|「[^」]*(?:」|$)|『[^』]*(?:』|$)|`[^`]*(?:`|$)'
# Word/possessive apostrophes stay inside a quoted span. A sentence-ending
# quote can close next to Chinese text, which does not require a space.
QUOTED_SENTENCE_PATTERN += r"|(?<!\w)'(?:[^']|'(?=\w)|(?<=\w)'(?=[ \t]+\w))*[.!?。！？]\s*'"
QUOTED_PATTERN += r"|(?<!\w)'(?:[^']|'(?=\w)|(?<=\w)'(?=[ \t]+\w))*(?:'(?!\w|[ \t]+\w)|$)"
ATTRIBUTION_PATTERN = r'\b(?:said|says|told|asked)\b|(?:说|說|告诉|告訴)'


def explicit_action(text):
    import re
    masked = re.sub(QUOTED_SENTENCE_PATTERN, '[quoted].', text or '')
    masked = re.sub(QUOTED_PATTERN, '[quoted]', masked)
    # A time such as 12:30 is narration, not a reported-speech introduction.
    masked = re.sub(r'(?<=\d)\s*[:：]\s*(?=\d)', ' ', masked)
    selected = None
    for paragraph in re.split(r'\n\s*\n', masked.strip()):
        reported = False
        for line in paragraph.split('\n'):
            if reported:
                continue
            sentences = re.split(r'[.!?。！？]', line)
            for sentence in sentences:
                # Closed quotes bound their attribution. Unquoted report
                # introductions (including objects such as "told me:") do not.
                tail = sentence.rsplit('[quoted]', 1)[-1]
                if re.search(r'(?:' + ATTRIBUTION_PATTERN + r')[^:：]*[:：]', tail, re.I):
                    reported = True
                if reported:
                    continue
                candidates = [sentence.strip()]
                if not re.search(ATTRIBUTION_PATTERN + r'|\[quoted\]', sentence, re.I):
                    candidates.extend(part.strip() for part in re.split(r'[,，]', sentence)[1:]
                                      if re.match(r'\s*(?:I want to |I would like to |我想)', part, re.I))
                for candidate in candidates:
                    for action, pattern in CONTROL_PATTERNS:
                        if re.fullmatch(pattern, candidate, re.I):
                            selected = action
                            break
            # An unfinished attributed clause continues on the next line,
            # including comma/"that" introductions. A blank paragraph ends it.
            if re.search(ATTRIBUTION_PATTERN, sentences[-1].rsplit('[quoted]', 1)[-1], re.I):
                reported = True
    return selected
