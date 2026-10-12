"""Small versioned conversation preference, independent from life stage/access.

The identity adapter supplies an authorised project and accepted turn. Memory
checkpoint/identity migrations must preserve this envelope, not reconstruct it
from a generated summary. Reasons are public policy labels, never reasoning.
"""
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

Phase = Literal['comfort', 'explore', 'shape']
Action = Literal['comfort', 'explore', 'shape', 'automatic', 'pause', 'resume', 'skip', 'correction']
Reason = Literal['new_journey', 'saved_narration', 'narrator_choice', 'narration', 'pause', 'resume', 'skip', 'correction']


class PhaseState(BaseModel):
    model_config = ConfigDict(extra='forbid')
    schema_version: Literal[1] = 1
    phase: Phase = 'comfort'
    selection: Literal['automatic', 'explicit'] = 'automatic'
    preferred_phase: Phase | None = None
    paused: StrictBool = False
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
    elif action in ('pause', 'resume'):
        values.update(paused=action == 'pause', reason=action)
    elif action == 'correction':
        values.update(phase='explore', reason='correction')
    elif action == 'skip':
        values.update(reason='skip')
    elif proposal.phase == 'shape':
        raise ValueError('Shaping requires an explicit narrator choice')
    elif not current.paused and current.selection == 'automatic' and proposal.phase is not None:
        values.update(phase=proposal.phase, reason='narration')
    # Replays and proposals which cannot change effective policy are no-ops.
    if all(values[key] == getattr(current, key) for key in ('phase','preferred_phase','selection','paused')) and action != 'skip':
        return current
    values.update(revision=current.revision + 1, source_turn_id=source_turn_id)
    return PhaseState.model_validate(values)


# Complete control sentences only. Quoted/reported/negated language does
# not match. These portable regexes are repeated in SQL for defence in depth.
CONTROL_PATTERNS = (
    ('pause', r"(?:please |I want to |I would like to |let's |can we )?(?:pause|stop)(?: (?:the interview|for now))?(?: please)?|(?:请|我想|我们先)?(?:暂停|停止)(?:采访|一下)?|不想继续了|先不聊了|不要再问(?:我)?(?:了)?|今天就到这里|(?:please )?(?:stop asking(?: me)? questions|don't ask(?: me)? (?:any )?more questions|do not ask(?: me)? (?:any )?more questions)"),
    ('resume', r"(?:please |I want to |let's |can we )?(?:resume|continue the interview)(?: please)?|(?:请|我想)?(?:恢复采访|继续采访)"),
    ('comfort', r"(?:please )?(?:keep talking|keep it gentle|let's take it slowly)|(?:请)?(?:轻松聊聊|慢慢聊|随便聊聊)"),
    ('explore', r"(?:please )?(?:explore my memories|let's explore|let's get straight into it)|(?:请)?(?:深入回忆|直接开始回忆|探索回忆)"),
    ('shape', r"(?:please |I want to |can we )?(?:shape my story|organize my story|organise my story|help me (?:shape|organize|organise|review) my story)|(?:请|我想)?(?:整理我的故事|帮我整理故事|回顾我的故事)"),
    ('automatic', r"(?:please )?(?:use automatic guidance|return to automatic guidance)|(?:请)?(?:恢复自动引导|自动引导)"),
    ('skip', r"(?:please |can we )?(?:skip(?: this question)?|try another topic|change (?:the )?topic)|(?:请)?(?:跳过(?:这个问题)?|换个话题)"),
)


def explicit_action(text):
    import re
    # Keep attribution scope across sentence/newline boundaries. A mixed
    # quoted narrative is ambiguous; do not persist another speaker's control.
    if re.search(r'["“”「」『』`]|\b(?:said|says|told|asked)\b|(?:说|說|告诉|告訴)[：:]?', text or '', re.I):
        return None
    selected = None
    for sentence in re.split(r'[.!?。！？\n]', (text or '').strip()):
        candidates = [sentence.strip()]
        # A direct first-person trailing request after a disclosure is intent;
        # quoted/reported clauses cannot acquire that authority.
        if not re.search(r'["“”‘’「」『』]|(?:he|she|they) said|[他她]说', sentence, re.I):
            candidates.extend(part.strip() for part in re.split(r'[,，]', sentence)[1:]
                              if re.match(r'\s*(?:I want to |I would like to |我想)', part, re.I))
        for candidate in candidates:
            for action, pattern in CONTROL_PATTERNS:
                if re.fullmatch(pattern, candidate, re.I):
                    selected = action
                    break
    return selected
