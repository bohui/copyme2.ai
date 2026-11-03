"""Stable dataset folders: category, owner, task, then suite."""
import re
import hashlib
import json


CATEGORIES = {'golden', 'safety', 'relevance', 'stress', 'calibration'}
SKILL_TASKS = {
    'memoir-interviewer': ('memoir-mira', 'reply'),
    'memoir-author-timeline': ('memoir-author-timeline', 'extract'),
    'memoir-composer': ('memoir-composer', 'compose'),
    'memoir-family-tree': ('memoir-family-tree', 'extract'),
    'memoir-memory-context': ('memoir-memory-context', 'profile'),
    'memoir-place-journey': ('memoir-place-journey', 'extract'),
    'memoir-place-groups': ('memoir-place-groups', 'group'),
    'memoir-place-photo-research': ('memoir-place-photo-research', 'discovery'),
    'memoir-historical-news-research': ('memoir-historical-news-research', 'discovery'),
    'memoir-story-game': ('memoir-story-game', 'generate'),
}


def dataset_name(category, owner, task, suite='core'):
    if category not in CATEGORIES or any(not re.fullmatch(r'[a-z0-9][a-z0-9-]*', part)
            for part in (owner, task, suite)):
        raise ValueError('Invalid Memoir dataset category or path segment')
    return f'memoir/{category}/{owner}/{task}/{suite}'


def skill_dataset(skill):
    owner, task = SKILL_TASKS[skill]
    return dataset_name('golden', owner, task)


WORKFLOWS = dataset_name('golden', 'memoir-workflows', 'integration')
CALIBRATION = dataset_name('calibration', 'memoir-judges', 'quality')
CONVERSATIONS = dataset_name('golden', 'memoir-mira', 'reply', 'conversations')
SEMANTIC_TASKS = {
    'bilingual-consistency': ('memoir-mira', 'reply'),
    'chapter-continuity': ('memoir-composer', 'compose'),
    'temporal-placement': ('memoir-author-timeline', 'extract'),
    'event-grounding': ('memoir-author-timeline', 'extract'),
}


def dataset_items_digest(items):
    """Only the displayed dataset name changes during an in-place rename."""
    values = [{k: v for k, v in item.items() if k != 'datasetName'} for item in items]
    values.sort(key=lambda item: item['id'])
    return hashlib.sha256(json.dumps(values, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def semantic_dataset(task, *, legacy=False):
    owner, action = SEMANTIC_TASKS[task]
    return dataset_name('golden', owner, action, task + ('-20261008-v1' if legacy else ''))


def canonical_dataset_name(name):
    """Move known names without changing dataset or item identity."""
    if re.fullmatch(r'memoir/(golden|safety|relevance|stress|calibration)/[a-z0-9-]+/[a-z0-9-]+/[a-z0-9-]+', name):
        return name
    if name == 'memoir/evaluation/conversations/memoir-interviewer':
        return CONVERSATIONS
    if name == 'memoir/evaluation/workflows':
        return WORKFLOWS
    if name == 'memoir/evaluation/judge-calibration':
        return CALIBRATION
    prefix = 'memoir/evaluation/skills/'
    if name.startswith(prefix):
        return skill_dataset(name.removeprefix(prefix))
    match = re.fullmatch(r'memoir/evaluation/v4/(lane-a|lane-b|skills)/([0-9a-f]+)', name)
    if match:
        owner, task = {'lane-a': ('memoir-mira', 'reply'),
            'lane-b': ('memoir-atlas', 'skill-selection'),
            'skills': ('memoir-workflows', 'skill-contracts')}[match[1]]
        return dataset_name('golden', owner, task, 'campaign-' + match[2])
    match = re.fullmatch(r'memoir/(evaluation|archive/v2|evaluation/v2)/(skill-triggers|skill-deliveries)', name)
    if match:
        owner, task = ('memoir-atlas', 'skill-selection') if match[2] == 'skill-triggers' else ('memoir-workflows', 'skill-delivery')
        return dataset_name('golden', owner, task, 'core' if match[1] == 'evaluation' else 'v2')
    match = re.fullmatch(r'memoir/(evaluation|issue6/20261008-v1)/(bilingual-consistency|chapter-continuity|temporal-placement|event-grounding)', name)
    if match:
        return semantic_dataset(match[2], legacy=match[1] != 'evaluation')
    raise ValueError('Unclassified dataset: ' + name)
