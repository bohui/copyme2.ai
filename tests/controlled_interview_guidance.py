"""Adapt existing controlled question fixtures to the independent skill boundary."""
from apps.api.interview_guidance import validate_guidance_result


def from_legacy_questions(packet, by_source, *, strategy=None):
    questions, signals = [], {}
    for source in packet['guidance_context']['source_windows']:
        for raw in by_source.get(source['id'], []):
            question = dict(raw, source_id=source['id'], source_version=source['version'],
                trigger=raw.get('trigger') or ('clarification' if raw.get('requires_confirmation') else 'follow_up'),
                historical_clue_id=raw.get('historical_clue_id'), bridge=raw.get('bridge',''))
            questions.append(question)
            signals.setdefault(question['trigger'], dict(kind=question['trigger'],
                source_refs=[dict(source_id=source['id'], version=source['version'],quote=raw['quote'])],
                detail_question_ids=[],recall_limit_quote=None))
        if questions:
            break
    raw = dict(signals=list(signals.values()),prepared_questions=questions,
        acknowledgement_guidance=None,strategy_proposal=dict(strategy=strategy,
            objective='clarify_order' if strategy == 'shape' else 'follow_story',focus_event_ids=[]) if strategy else None)
    return validate_guidance_result(raw, packet)


def select_news(context, **changes):
    """A fixed Lane B relevance decision, separate from merely ready research."""
    from test_historical_news import ready_context
    from apps.api.historical_news import HISTORICAL_INVITATIONS
    context.update(ready_context(), **changes)
    question,bridge=HISTORICAL_INVITATIONS.get(context.get('interview_language'),HISTORICAL_INVITATIONS['en-AU'])
    for clue in context['historical_news']['clues']:
        context.setdefault('prepared_questions',[]).append(dict(id=clue['id'],question=question,topic='public context',
            quote='A narrator context anchor',source_id='context',source_version=1,char_start=0,char_end=25,
            trigger='historical_news',historical_clue_id=clue['id'],bridge=bridge,scope='broader',requires_confirmation=False))
    return context
