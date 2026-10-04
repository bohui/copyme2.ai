"""Deterministic context-volume heuristic, independent of composer quality."""
import re
from .conversation_text import original_conversation_text

LIFE_STAGES = ('baby', 'toddler', 'childhood', 'adolescence', 'young_adulthood', 'midlife', 'later_life')
HAN = re.compile(r'[\u3400-\u4dbf\u4e00-\u9fff\U00020000-\U0002fa1f]')
WORDS = re.compile(r"[^\W_]+(?:['’\-][^\W_]+)*", re.UNICODE)


def word_equivalents(text):
    # Each Han character is one equivalent; remaining Unicode word/number
    # tokens count once (including contractions and hyphenated words).
    # Punctuation, whitespace and emoji contribute nothing.
    return len(HAN.findall(text)) + len(WORDS.findall(HAN.sub(' ', text)))


def narrator_response(row):
    if row.get('kind') != 'agent':
        return ''
    content = row.get('content') or ''
    if not content.startswith('Storyteller: '):
        return ''
    question, separator, answer = content[len('Storyteller: '):].partition('\nMemory Spark: ')
    return original_conversation_text(question).strip() if separator and answer.strip() else ''


def readiness(words):
    words = max(0, words)
    percent = words / 10 if words <= 300 else 30 + min(words-300, 700) * 20 / 700
    return {'word_equivalents': words, 'percent': round(min(percent, 50), 1),
            'color': 'red' if words < 300 else 'amber' if words < 1000 else 'green'}


def stage_readiness(rows, project_id):
    latest = {}
    for row in rows:
        if row.get('id') and row.get('project_id') == project_id:
            latest[row['id']] = row
    counts = dict.fromkeys(LIFE_STAGES, 0)
    for row in latest.values():
        stage = row.get('life_stage')
        if stage in counts:
            counts[stage] += word_equivalents(narrator_response(row))
    return {stage: readiness(words) for stage, words in counts.items()}
