"""Build bounded replay cases from an explicitly selected, local conversation export.

Original testimony stays in ignored local artifacts and the selected Langfuse
project. Counterfactual gate probes are labelled separately from observed turns.
The stable synthetic 160-item catalog is unchanged.
"""
from copy import deepcopy

from apps.api.interview_strategy import stage_breadth_checkpoint
from scripts.memoir_skill_eval_suite import digest

DATASET = 'memoir/evaluation/conversations/memoir-interviewer'

REQUIREMENTS = {
    1: 'Follow the volunteered birthplace without assuming it was the childhood home or asking for an already supplied birth date.',
    2: 'Follow the childhood play memory without repeating the topic choice or assuming a school attended by the narrator.',
    3: 'Follow the supplied outdoor activities; do not ask again what activities they did.',
    4: 'Use the specific insect/snail anecdote already supplied; ask an unanswered detail without inventing feelings.',
    5: 'Keep the distinction between snails and crickets, and the friend versus narrator; do not ask again what they did with snails.',
    6: 'The possible disposal and crying are conditional, not a completed incident. Do not assume the named aunt is the friend’s mother or ask again how he protected the crickets.',
    7: 'If referring to the friend’s alternate name, keep it the same person. Preserve uncertainty about cage material and approximate moving age when using those details; omission from a brief reply is allowed. Follow the move or gradual change rather than repeating the insect anecdote.',
    8: 'The journey and its memorable landmarks have already been described. Follow an unanswered aspect instead of asking for another example of that same route or those same landmarks.',
}


def conversation_cases(template, sources, turns, *, control_expectations):
    """One exact original prefix per accepted source; never include future turns."""
    originals = sorted((s for s in sources if s['status'] == 'active'), key=lambda s: s['sequence'])
    if not originals or len({s['project_id'] for s in originals}) != 1:
        raise ValueError('one_selected_conversation_required')
    saved = {t['source_id']: t for t in turns if (t.get('collector') or {}).get('reply')}
    def exchange(source):
        turn = saved.get(source['id'], {})
        reply = (turn.get('collector') or {}).get('reply')
        if turn.get('source_version', source['version']) != source['version']:
            reply = None
        return dict(source_id=source['id'], source_version=source['version'], narrator=source['text'],
            assistant_reply=reply, assistant_is_testimony=False, assistant_delivery_verified=False)
    rows = []
    for source in originals:
        history = [exchange(s) for s in originals if s['sequence'] < source['sequence']]
        row = deepcopy(template)
        case = 'conversation-' + source['id']
        row.update(id='memoir-interviewer/' + case + '/' + source['language'], case=case,
                   locale=source['language'], dataset=DATASET, scope='owner_selected_conversation_replay')
        current = dict(id=source['id'], version=source['version'], text=source['text'], status='active',
            language=source['language'], kind=source['kind'], char_start=0, char_end=len(source['text']),
            original_length=len(source['text']))
        row['task'].update(instruction=source['text'], source=current)
        c = row['task']['context']
        c.update(source=current, sources=[current], events=[], opening_turn=not history,
            has_accepted_narration=bool(history), interview_language=source['language'],
            recent_dialogue=history, breadth_checkpoint=None)
        c['strategy_context'] = dict(mode='active', plan=None, prior_delivered_question=None)
        expected = control_expectations.get(source['id'], {})
        facts = expected.get('facts', {})
        if (expected.get('source_version') != source['version']
                or expected.get('text_sha256') != digest(source['text'])
                or set(facts) != {'stopped', 'question', 'selection_reason'}
                or type(facts['stopped']) is not bool or type(facts['question']) is not bool
                or facts['selection_reason'] is not None and not isinstance(facts['selection_reason'], str)
                or facts['stopped'] and (facts['question'] or facts['selection_reason'] != 'pause')):
            raise ValueError('reviewed_source_control_expectation_required')
        # Absence from a literal stop matcher never establishes narrator intent.
        row['gold']['facts'] = deepcopy(facts)
        stopped = facts['stopped']
        if stopped:
            required = ['Respect the stop with no immediate question or invitation to change life stage; an optional future-return courtesy is allowed.']
        elif not facts['question']:
            required = ["Answer the narrator's direct question or request without an unnecessary interview follow-up."]
        else:
            required = ['One useful unanswered question; preserve continuity and narrator agency.',
                REQUIREMENTS.get(source['sequence'], 'Follow the latest detail using only the supplied original prefix.')]
        row['gold']['required'] = required
        row['gold']['forbidden'] = ['Invent a personal fact, repeat an answered question, treat assistant text as testimony.']
        row['origin'] = dict(kind='observed_conversation_prefix', synthetic=False,
            source_id=source['id'], source_version=source['version'], source_sequence=source['sequence'])
        row['content_sha256'] = digest({k: v for k, v in row.items() if k != 'content_sha256'})
        rows.append(row)
    last = rows[-1]
    probes = [
        ('ready-transition', '那段童年的事差不多就这些了。', 3, True, None,
         'Gently bridge from childhood to the suggested adolescence stage with one optional invitation; do not assume school, work or marriage.'),
        ('ready-continue', '我还想继续讲小时候养蝈蝈的事，还有一个细节没讲。', 3, True, None,
         'Stay with the childhood cricket story; the explicit wish to add detail overrides the breadth checkpoint.'),
        ('ready-unfinished', '还有一次，我刚坐上那辆车，就发生了一件事……', 3, True, None,
         'Follow the unfinished childhood anecdote instead of moving to another stage.'),
        ('below-gate', '那段童年的事差不多就这些了。', 2, True, None,
         'Offer a gentle open direction; do not claim this stage has enough grounded events or force the suggested next stage.'),
        ('ready-correction', '我说错了，搬家时大概七岁，不是五六岁。', 3, True, 'current_correction',
         'Acknowledge the corrected approximate age and ask one relevant question without switching stage. Do not assert the superseded age as current fact; an explicitly negated contrast is allowed.'),
        ('ready-pause', '今天先到这里。', 3, False, 'pause',
         'Respect the stop with no immediate question or invitation to change life stage. A brief optional future-return courtesy is allowed, without a promise or scheduled action.'),
        ('ready-redirect', '我想聊现在在悉尼生活的事。', 3, True, 'user_redirect',
         'Follow the explicit present-day Sydney topic, despite the suggested adolescence stage; do not re-ask where they live.'),
        ('ready-quoted-continue', '学校里有人常说：“我还想继续讲童年的事。”我自己那段事已经讲完了。', 3, True, None,
         'Do not promote another person’s quoted wish to continue into narrator intent; gently invite the suggested next stage.'),
    ]
    for case, text, count, question, reason, requirement in probes:
        row = deepcopy(last)
        row.update(id='memoir-interviewer/' + case + '/' + row['locale'], case=case)
        c = row['task']['context']
        c['recent_dialogue'].append(exchange(originals[-1]))
        source = dict(c['source'], id='counterfactual-' + digest(row['id'])[:20], text=text,
                      char_end=len(text), original_length=len(text))
        c.update(source=source, sources=[source], breadth_checkpoint=stage_breadth_checkpoint([
            dict(life_stage='childhood', grounded_events=count, last_source_sequence=8)]))
        row['task'].update(instruction=text, source=source)
        row['gold']['facts'] = dict(stopped=not question, question=question, selection_reason=reason)
        row['gold']['required'] = [requirement]
        row['origin'] = dict(kind='counterfactual_gate_probe', synthetic=True,
            basis_source_id=originals[-1]['id'], grounded_event_count_fixture=count)
        row['content_sha256'] = digest({k: v for k, v in row.items() if k != 'content_sha256'})
        rows.append(row)
    return rows
