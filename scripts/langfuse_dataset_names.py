"""One target path connects prompts, datasets and evaluation rules."""
import hashlib
import json
import re

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
SKILL_TARGETS = {
    'memoir-interviewer': 'memoir/agents/mira/reply',
    'memoir-background-agent': 'memoir/agents/atlas/skill-selection',
    'memoir-author-timeline': 'memoir/skills/author-timeline/extract',
    'memoir-composer': 'memoir/workflows/composer-checkpoints',
    'memoir-family-tree': 'memoir/skills/family-tree/extract',
    'memoir-memory-context': 'memoir/skills/memory-context/profile',
    'memoir-place-journey': 'memoir/skills/place-journey/extract',
    'memoir-place-groups': 'memoir/skills/place-groups/group',
    'memoir-place-photo-research': 'memoir/skills/place-photo-research/discovery',
    'memoir-historical-news-research': 'memoir/skills/historical-news-research/discovery',
    'memoir-story-game': 'memoir/workflows/story-game-adaptation',
}


def target_dataset(target, category='golden', suite='core'):
    parts = target.split('/')
    if (category not in CATEGORIES or len(parts) < 3 or parts[0] != 'memoir'
            or parts[1] not in {'agents', 'skills', 'workflows', 'evaluators', 'probes'}
            or any(not re.fullmatch(r'[a-z0-9][a-z0-9-]*', p) for p in [*parts[2:], suite])):
        raise ValueError('Invalid Memoir evaluation target or dataset path segment')
    return f'{target}/{category}/{suite}'


def dataset_target(name):
    parts = name.split('/')
    if len(parts) < 5 or parts[-2] not in CATEGORIES:
        raise ValueError('Dataset must end with category/suite')
    target = '/'.join(parts[:-2])
    if target_dataset(target, parts[-2], parts[-1]) != name:
        raise ValueError('Invalid dataset target')
    return target


def evaluation_rule(name, metric):
    dataset_target(name)
    if not re.fullmatch(r'[a-z][a-z0-9-]*', metric):
        raise ValueError('Invalid evaluation metric')
    return f'{name}/{metric}'


def owner_target(owner, task):
    if owner == 'memoir-mira':
        return f'memoir/agents/mira/{task}'
    if owner == 'memoir-atlas':
        return f'memoir/agents/atlas/{task}'
    if owner == 'memoir-workflows':
        return 'memoir/workflows/' + {'integration': 'source-to-private-draft',
            'skill-contracts': 'multi-skill-regression', 'skill-delivery': 'multi-skill-delivery'}[task]
    if owner == 'memoir-judges':
        return 'memoir/workflows/judge-calibration'
    for skill, (known_owner, known_task) in SKILL_TASKS.items():
        if (owner, task) == (known_owner, known_task):
            return SKILL_TARGETS[skill]
    if owner.startswith('memoir-'):
        return f'memoir/skills/{owner.removeprefix("memoir-")}/{task}'
    raise ValueError('Unknown Memoir dataset owner')


def dataset_name(category, owner, task, suite='core'):
    if any(not re.fullmatch(r'[a-z0-9][a-z0-9-]*', p) for p in (owner, task)):
        raise ValueError('Invalid Memoir dataset category or path segment')
    return target_dataset(owner_target(owner, task), category, suite)


def skill_dataset(skill, suite='core'):
    return target_dataset(SKILL_TARGETS[skill], suite=suite)


def judge_name(skill):
    target = SKILL_TARGETS[skill].removeprefix('memoir/')
    metric = 'interview-quality' if skill == 'memoir-interviewer' else 'quality'
    return f'memoir/evaluators/{target}/{metric}'


def calibration_dataset(skill, suite='core'):
    return target_dataset(judge_name(skill), 'calibration', suite)


def admission_dataset(skill, suite='core'):
    return target_dataset('memoir/workflows/' + skill.removeprefix('memoir-') + '-admission', suite=suite)


def delivery_target(item):
    skill = item['skill']
    if item.get('kind') == 'live_contract':
        return {'memoir-composer': 'memoir/skills/composer/draft',
            'memoir-family-tree': 'memoir/skills/family-tree/extract',
            'memoir-story-game': 'memoir/skills/story-game/brief'}.get(skill, SKILL_TARGETS[skill])
    return SKILL_TARGETS[skill]


WORKFLOWS = target_dataset('memoir/workflows/source-to-private-draft')
CALIBRATION = target_dataset('memoir/workflows/judge-calibration', 'calibration')
CONVERSATIONS = target_dataset(SKILL_TARGETS['memoir-interviewer'], suite='conversations')
SEMANTIC_TASKS = {
    'bilingual-consistency': 'memoir/workflows/bilingual-reply-parity',
    'chapter-continuity': SKILL_TARGETS['memoir-composer'],
    'temporal-placement': SKILL_TARGETS['memoir-author-timeline'],
    'event-grounding': SKILL_TARGETS['memoir-author-timeline'],
}


def dataset_items_digest(items):
    values = [{k: v for k, v in item.items() if k != 'datasetName'} for item in items]
    values.sort(key=lambda item: item['id'])
    return hashlib.sha256(json.dumps(values, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def semantic_dataset(task, *, legacy=False):
    return target_dataset(SEMANTIC_TASKS[task], suite=task + ('-20261008-v1' if legacy else ''))


def canonical_dataset_name(name):
    """Classify historical aggregates honestly; the migration splits their active cases."""
    try:
        dataset_target(name)
        return name
    except ValueError:
        pass
    match = re.fullmatch(r'memoir/(golden|safety|relevance|stress|calibration)/([a-z0-9-]+)/([a-z0-9-]+)/([a-z0-9-]+)', name)
    if match:
        category, owner, task, suite = match.groups()
        if suite.startswith('bilingual-consistency'):
            return target_dataset(SEMANTIC_TASKS['bilingual-consistency'], category, suite)
        if owner == 'memoir-workflows' and task == 'skill-contracts':
            suite = 'contracts-' + suite
        return dataset_name(category, owner, task, suite)
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
        target = {'lane-a': SKILL_TARGETS['memoir-interviewer'],
            'lane-b': SKILL_TARGETS['memoir-background-agent'],
            'skills': 'memoir/workflows/multi-skill-regression'}[match[1]]
        suite = ('contracts-' if match[1] == 'skills' else '') + 'campaign-' + match[2]
        return target_dataset(target, suite=suite)
    match = re.fullmatch(r'memoir/(evaluation|archive/v2|evaluation/v2)/(skill-triggers|skill-deliveries)', name)
    if match:
        target = 'memoir/workflows/' + ('skill-admission' if match[2] == 'skill-triggers' else 'multi-skill-delivery')
        return target_dataset(target, suite='core' if match[1] == 'evaluation' else 'v2')
    match = re.fullmatch(r'memoir/(evaluation|issue6/20261008-v1)/(bilingual-consistency|chapter-continuity|temporal-placement|event-grounding)', name)
    if match:
        return semantic_dataset(match[2], legacy=match[1] != 'evaluation')
    raise ValueError('Unclassified dataset: ' + name)
