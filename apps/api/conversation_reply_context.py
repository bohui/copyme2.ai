"""Native speaker history and one shared evidence table for interview context."""
from copy import deepcopy

from .lifetime_memory_context import serialize_packet


def _span(value):
    source = value.get('source_id', value.get('id'))
    if not source or 'version' not in value:
        return None
    text = value.get('original', value.get('text', value.get('quote')))
    start = value.get('char_start', 0)
    end = value.get('char_end', start + len(text) if text is not None else None)
    if end is None:
        return None
    return dict(source_id=str(source), version=value['version'], char_start=start, char_end=end)


def evidence_key(ref):
    return ':'.join(str(ref[key]) for key in ('source_id', 'version', 'char_start', 'char_end'))


def conversation_context(view, known_sources=None):
    """Keep narrator testimony separate from application-supplied reference data."""
    current = view['current']
    originals = [entry['narrator'] for entry in [*view.get('dialogue', []), current]]
    turns = []
    narrated = dict(known_sources or {})
    user_ids = {entry['narrator']['source_id'] for entry in [*view.get('dialogue', []), current]}
    assistant_turns = {}
    for entry in [*view.get('dialogue', []), current]:
        narrator = entry['narrator']
        narrated[f"{narrator['source_id']}:{narrator['version']}"] = (entry['sequence'], narrator)
        if entry is not current:
            turns.append((entry['sequence'], 0, 'user', narrator['original']))
            if entry.get('assistant'):
                turns.append((entry['sequence'], 1, 'assistant', entry['assistant']['text']))
                assistant_turns[entry['sequence']] = entry['assistant']['text']
    # Delivered question records also bridge a cold start at a host checkpoint.
    for pair in view.get('context', {}).get('recent_dialogue', []):
        question, answer = pair.get('question') or {}, pair.get('response') or {}
        if question.get('role') != 'assistant' or question.get('delivered') is not True:
            continue
        text = question.get('text')
        sequence = question.get('sequence', answer.get('sequence', current['sequence']) - 1)
        if text and text not in assistant_turns.get(sequence, ''):
            turns.append((sequence, 1, 'assistant', text))
        if (answer.get('role') == 'user' and answer.get('complete') is True and answer.get('text')
                and answer.get('id') not in user_ids):
            sequence = answer.get('sequence', current['sequence'] - 1)
            turns.append((sequence, 0, 'user', answer['text']))
            user_ids.add(answer.get('id'))
            if ref := _span(answer):
                originals.append(answer)
                narrated[f"{ref['source_id']}:{ref['version']}"] = (sequence, ref)
    history = [dict(role=role, content=text) for _, _, role, text in sorted(turns, key=lambda row: row[:2])]
    evidence = {}
    def reference(value):
        ref = _span(value)
        if ref is None:
            return None
        text = value.get('original', value.get('text', value.get('quote')))
        key = evidence_key(ref)
        record = dict(ref, role='storyteller')
        known = narrated.get(f"{ref['source_id']}:{ref['version']}")
        if known and known[1].get('char_start', 0) <= ref['char_start'] and known[1]['char_end'] >= ref['char_end']:
            record['conversation_sequence'] = known[0]
        elif text is not None:
            record['text'] = text
        if key not in evidence or 'text' in record:
            evidence[key] = record
        return ref
    for entry in [*originals, *view.get('original_evidence', [])]:
        reference(entry)
    preferences = {key: deepcopy(value) for key, value in view.get('preferences', {}).items()
        if key in {'chosen_name', 'language', 'excluded_topics', 'paused_topics', 'unresolved_references'}}
    preferences['continuity_complete'] = view.get('preferences', {}).get('known_continuity_complete', True)
    continuity = {}
    for item in view.get('preferences', {}).get('known_continuity', []):
        if item['kind'] in {'paused_topic', 'excluded_topic', 'active_question'}:
            continue
        data = deepcopy(item['data'])
        originals = data.pop('source_refs', [])
        refs = [ref for value in originals if (ref := reference(value))]
        if any(value.get('quote') == data.get('text') for value in originals):
            data.pop('text', None)
        data.pop('schema_version', None)
        continuity[item['record_id']] = dict(kind=item['kind'], data=data, source_refs=refs)
    events, deliveries = {}, {}
    for index, delivery in enumerate(view.get('background_deliveries', [])):
        if delivery.get('skill') == 'memoir-author-timeline':
            for event in delivery.get('events', []):
                refs = {}
                for value in [*event.get('original_passages', []), *event.get('source_refs', [])]:
                    if ref := reference(value):
                        refs[evidence_key(ref)] = ref
                events[event['id']] = {key: deepcopy(value) for key, value in event.items()
                    if key not in {'original_passages', 'source_refs'} and not key.endswith('_retrieval')}
                events[event['id']]['source_refs'] = list(refs.values())
        else:
            deliveries[delivery.get('skill', str(index))] = deepcopy(delivery)
    # A full original already supplies its contained excerpts; keep only their references.
    for key, record in list(evidence.items()):
        if any(other_key != key and other['source_id'] == record['source_id']
                and other['version'] == record['version'] and other['char_start'] <= record['char_start']
                and other['char_end'] >= record['char_end'] and 'text' in other
                for other_key, other in evidence.items()):
            del evidence[key]
    context = {key: deepcopy(value) for key, value in view.get('context', {}).items() if key != 'recent_dialogue'}
    brief = {key: deepcopy(value) for key, value in view.get('brief', {}).items()
        if key not in {'last_delivered_question'} and value not in (None, [], {})}
    entities = dict(preferences={'current': preferences}, context={'current': context},
        brief={'current': brief}, continuity=continuity, evidence=evidence, events=events,
        deliveries=deliveries)
    # This changes at the suffix each turn, never inside earlier conversation items.
    entities['turn'] = {'current': dict(reply_language=view.get('reply_language'),
        reply_contract=view.get('reply_contract'), sequence=current['sequence'],
        source_id=current['narrator']['source_id'], version=current['narrator']['version'])}
    return entities, history


def context_update(entities, previous=None):
    previous = previous or {}
    updates, removed = {}, {}
    for group in sorted(entities.keys() | previous.keys()):
        current, before = entities.get(group, {}), previous.get(group, {})
        changed = {key: value for key, value in current.items() if before.get(key) != value}
        if changed:
            updates[group] = changed
        missing = sorted(before.keys() - current.keys())
        if missing:
            removed[group] = missing
    return serialize_packet(dict(memoir_context=dict(origin='application', narrator_message=False,
        updates=updates, removed=removed)))


def native_messages(view, prompt=''):
    instructions = [dict(type='input_text', text=view['instructions'])]
    if prompt:
        instructions.append(dict(type='input_text', text=prompt))
    context, history = conversation_context(view)
    return [dict(role='developer', content=instructions),
        dict(role='user', content=context_update(context)), *history,
        dict(role='user', content=view['current']['narrator']['original'])]
