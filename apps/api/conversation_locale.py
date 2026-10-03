"""Host-owned first-reply locale state, stored in the existing private profile."""
import re
import unicodedata
from .conversation_text import original_conversation_text

LOCALES = {'en-AU', 'zh-CN'}
FIELD = 'conversation_language'
OPENINGS = (
    'The storyteller wants to begin exploring a memory.',
    'The storyteller wants to continue with another memory.',
)


def eligible_reply(text):
    text = original_conversation_text(text or '').strip()
    if not text or text.startswith(OPENINGS) or text in {'Voice answer', '语音回答', 'Shared attachments', '已分享附件'}:
        return None
    return text


def first_narrator_reply(rows):
    # Legacy storage readers return newest first. Sorting precedes filtering;
    # no assistant prose, notes or synthetic prompts enter the language signal.
    for row in sorted(rows, key=lambda r: (r.get('created_at') or '', r.get('id') or '')):
        if row.get('kind') != 'agent':
            continue
        content = row.get('content') or ''
        if not content.startswith('Storyteller: '):
            continue
        narrator, separator, assistant = content[13:].partition('\nMemory Spark: ')
        reply = eligible_reply(narrator)
        if separator and assistant.strip() and reply:
            return {'text': reply, 'id': row.get('id')}
    return None


def detect_reply_locale(text):
    letters = [c for c in text if unicodedata.category(c).startswith('L')]
    if not letters:
        return None
    han = sum('CJK UNIFIED IDEOGRAPH' in unicodedata.name(c, '') for c in letters)
    if han >= 2 and han / len(letters) >= .35:
        return 'zh-CN'
    latin = sum('LATIN' in unicodedata.name(c, '') for c in letters)
    return 'en-AU' if latin >= 3 and latin / len(letters) >= .6 else None


def state(profile):
    value = profile.get(FIELD)
    return value if isinstance(value, dict) and value.get('version') == 1 and value.get('initialized') is True else None


def record(locale, *, source, detected=None, first_reply_id=None, previous=None):
    previous = previous or {}
    return {'version': 1, 'initialized': True, 'revision': int(previous.get('revision') or 0) + 1,
            'locale': locale, 'source': source,
            'first_reply_locale': previous.get('first_reply_locale', detected),
            'first_reply_fallback': previous.get('first_reply_fallback', locale if source != 'explicit' else None),
            'first_reply_id': previous.get('first_reply_id', first_reply_id)}


def explicit_profile(profile, locale):
    result = dict(profile)
    previous = state(profile)
    if locale in LOCALES:
        result['preferred_language'] = locale
        result[FIELD] = record(locale, source='explicit', previous=previous)
    else:
        # "Automatic" restores the original first-reply choice; it never
        # makes the next reply a new language-detection opportunity.
        result.pop('preferred_language', None)
        if previous:
            result[FIELD] = {**previous, 'revision': int(previous.get('revision') or 0) + 1,
                             'locale': previous.get('first_reply_locale') or previous.get('first_reply_fallback'), 'source': 'first_reply'}
    return result


def explicit_request(text):
    # A language mentioned in a recollection/quote is not an instruction.
    text = text.strip().rstrip('.。!！')
    if re.fullmatch(r'(?:please\s+)?(?:reply|respond|speak|continue)(?:\s+to me)?\s+in\s+(English|Chinese)(?:\s+please)?', text, re.I):
        return 'zh-CN' if 'chinese' in text.lower() else 'en-AU'
    match = re.fullmatch(r'(?:请|以后请|以后)?(?:用|使用)(中文|汉语|英语|英文)(?:回复|回答|交流|继续)(?:我)?', text)
    return ('zh-CN' if match[1] in {'中文','汉语'} else 'en-AU') if match else None


async def restore_from_history(storage, profile):
    """Backfill on resume from the earliest authorized reply, under the lease."""
    import asyncio
    from .agent_storage import UserStorage
    from .agent_lock import AgentTurnLease, AgentTurnBusyError
    if state(profile) or not isinstance(storage, UserStorage):
        return profile
    first = await asyncio.to_thread(storage.first_narrator_reply)
    if not first:
        return profile
    detected = detect_reply_locale(first['text'])
    try:
        async with AgentTurnLease(storage) as lease:
            current = await lease.io(storage.profile)
            if state(current):
                return current
            preferred = current.get('preferred_language')
            locale = preferred if preferred in LOCALES else detected
            if not locale:
                return current
            current = {**current, 'preferred_language': locale, FIELD: record(locale,
                source='legacy' if preferred in LOCALES else 'first_reply',
                detected=detected, first_reply_id=first['id'])}
            await lease.check()
            await lease.io(storage.save_profile, current)
            await lease.check()
            return current
    except AgentTurnBusyError:
        # A conversation may be committing the same decision. Read its latest
        # state; never race it with a second write or block profile hydration.
        return await asyncio.to_thread(storage.profile)
