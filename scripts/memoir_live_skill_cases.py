"""Synthetic cases and independent checks for isolated live skill calls.

These are contract probes, not authorization to persist application artifacts.
Deterministic skills are probed for instruction adherence, not rerouted in production.
"""
from copy import deepcopy
from pathlib import Path
from apps.api.prompt_artifact import load_prompt_artifact, prompt_path

from apps.api.background_profile import PROFILE_FIELDS, profile_contract, profile_packet, validate_profile
from apps.api.family_context import extract_family_tree_context
from apps.api.lifetime_memory_lane_engine import EXTRACTION_WINDOW_CONTRACT
from apps.api.memory_events import extraction_instructions, extraction_schema, validate_extraction
from apps.api.place_groups import resolve_place_groups
from apps.api.place_journey import extract_place_journeys

ROOT = Path(__file__).resolve().parents[1]


def eval_fragment(name):
    return load_prompt_artifact(prompt_path(f'memoir/evaluation/live-skills/{name}'))


def object_schema(properties):
    return dict(type='object', properties=properties, required=list(properties), additionalProperties=False)


def skill_prompt(name, *references):
    directory = ROOT / 'skills' / name
    return '\n\n'.join(load_prompt_artifact(directory / file) for file in ('SKILL.md', *references))


def source(locale):
    text = ('I grew up in Sydney. My father repaired bicycles in our shed.' if locale == 'en-AU'
            else '我小时候住在成都。父亲在院子里修自行车。')
    return dict(id='synthetic-source-' + locale, version=1, project_id='isolated-skill-test',
                status='active', kind='narrator_chat', author_role='storyteller', sequence=1, text=text)


def composer_job(locale):
    original = source(locale)
    ref = dict(source_id=original['id'], version=1, quote=original['text'],
               char_start=0, char_end=len(original['text']))
    event = dict(id='synthetic-event-' + locale, revision=1, kind='event', status='active',
                 life_stage='childhood', title='Bicycles in our shed' if locale == 'en-AU' else '院子里的自行车',
                 source_refs=[ref])
    return dict(project_id=original['project_id'], locale=locale, base_revision=0, policy_epoch=0,
                coverage_round=5, sources=[original], events=[event], previous=None,
                source_manifest=[dict(id=original['id'], version=1)],
                event_manifest=[dict(id=event['id'], revision=1)])


def progressive_page(locale, previous=None):
    from uuid import UUID
    from apps.api.lifetime_memory_contracts import PinnedContinuity
    english = ['As a child in Sydney, I repaired bicycles with my father.',
        'At school, Ms Vale taught me to read maps.', 'We repaired bicycles in our shed.',
        'Father kept the bicycle tools in a blue tin.', 'On Saturdays I helped Father repair bicycles.']
    chinese = ['小时候在成都，我和父亲一起修自行车。', '在学校，王老师教我看地图。',
        '我们在院子里修自行车。', '父亲把修自行车的工具放在蓝色铁盒里。', '每个星期六我帮父亲修自行车。']
    new_en = ['Father also taught me to patch a punctured tyre.', 'We used a rubber patch and glue.',
        'Thank you.', 'I practised patching tyres beside Father.', 'Yes, that is what I remember.']
    new_zh = ['父亲还教我给扎破的轮胎补胎。', '我们用橡胶补片和胶水。', '谢谢。', '我在父亲身边练习补胎。', '对，我记得就是这样。']
    texts = english if locale == 'en-AU' else chinese
    sources = [dict(id=str(UUID(int=100+i)), project_id='isolated-progressive', version=1, sequence=i+1,
        text=t, char_start=0, char_end=len(t), original_length=len(t), kind='narrator_chat', language=locale,
        author_role='storyteller', status='active') for i, t in enumerate(texts)]
    def ref(s):
        return dict(source_id=s['id'], version=1, quote=s['text'], char_start=0, char_end=len(s['text']))
    events = [dict(id=str(UUID(int=200+i)), revision=1, kind='event', status='active', life_stage='childhood', temporal={},
        title=('Bicycle repairs with Father' if i == 0 else 'Map reading at school') if locale == 'en-AU' else ('和父亲修自行车' if i == 0 else '在学校看地图'),
        source_refs=[ref(s) for j,s in enumerate(sources) if (j != 1 if i == 0 else j == 1)]) for i in range(2)]
    messages = sources
    if previous:
        messages = [{**sources[0], 'id':str(UUID(int=300+i)), 'sequence':i+6,
            'text':t, 'char_end':len(t), 'original_length':len(t)} for i,t in enumerate(new_en if locale=='en-AU' else new_zh)]
        sources = [*sources,*messages]
        events[0]['revision'] = 2
        events[0]['source_refs'] += [ref(messages[i]) for i in (0,1,3)]
    return dict(protocol='lifetime_composer_pages',schema_version=1,lane_id=str(UUID(int=1)),token=str(UUID(int=2)),
        snapshot_id=str(UUID(int=4 if previous else 3)),user_id=str(UUID(int=5)),project_id='isolated-progressive',conversation_id=str(UUID(int=6)),
        skill='composer',locale=locale,policy_epoch=1,preference_revision=0,source_high_water=10 if previous else 5,event_high_water=3 if previous else 2,
        page_number=0,root_digest='a'*64,page_digest='b'*64,input_digest='c'*64,complete=False,coverage_round=10 if previous else 5,base_revision=1 if previous else 0,
        preferences=PinnedContinuity(preference_revision=0,language=locale).model_dump(mode='json'),source=sources[0],partition=events[0],events=[],
        batch=dict(schema_version=1,starting_after=5 if previous else 0,through_source=10 if previous else 5,next_offset=100000,
            cursor=[3 if previous else 2,events[-1]['id'],'last-ref'],sources=sources,events=events,new_messages=messages,previous=previous,previous_summary=None))


def profile_cases():
    """Admitted bounded pages, not proof of host scheduling or persistence."""
    rows = []

    def add(label, text, expected, evidence, *, target, sequence, targets=PROFILE_FIELDS,
            reference=None, start=0, kind='narrator_chat'):
        page = dict(project_id='isolated-profile-test', source=dict(
            id='synthetic-profile-' + label, version=2, project_id='isolated-profile-test',
            status='active', author_role='storyteller', kind=kind, sequence=sequence,
            text=text, char_start=start, char_end=start + len(text), original_length=start + len(text)),
            profile_context=dict(work_mode='extract', revision=3, target_round=target,
                                 targets=list(targets), reference=reference or {}))
        instructions, schema = profile_contract(page)
        rows.append(dict(id='memory-profile-' + label, skill='memoir-memory-context',
            instructions=instructions, schema=schema, input=profile_packet(page), page=page,
            expected=expected, evidence=evidence, validator='profile',
            scope='admitted checkpoint page; proposal semantics only, no schedule or saved-profile certification'))

    add('checkpoint-en-AU',
        'My name is Alex. I was born in 1960 in Hobart. I grew up in Launceston. I am a man. Now I live in Sydney.',
        dict(name='Alex', birth_year=1960, birth_place='Hobart', childhood_place='Launceston', avatar_style='male'),
        dict(name='My name is Alex.', birth_year='I was born in 1960 in Hobart.',
             birth_place='I was born in 1960 in Hobart.', childhood_place='I grew up in Launceston.',
             avatar_style='I am a man.'), target=5, sequence=2,
        targets=[field for field in PROFILE_FIELDS if field != 'birth_date_expression'],
        reference={'birth_date_expression': '', 'authority': {'birth_date_expression': 'explicit'}})
    add('checkpoint-zh-CN',
        '🌱 我的名字是小梅。我出生于1960年前后，出生地是成都。我在昆明长大。我是一名女性。现在我住在悉尼。',
        dict(name='小梅', birth_date_expression='1960年前后', birth_place='成都', childhood_place='昆明', avatar_style='female'),
        dict(name='我的名字是小梅。', birth_date_expression='我出生于1960年前后', birth_place='出生地是成都',
             childhood_place='我在昆明长大。', avatar_style='我是一名女性。'), target=10, sequence=7,
        targets=[field for field in PROFILE_FIELDS if field != 'birth_year'], start=140,
        reference={'birth_year': None, 'authority': {'birth_year': 'explicit'}}, kind='narrator_transcript')
    add('manual-reference',
        'My name is Robin. I was born in 1971 in Perth. I grew up in Fremantle. My wife is a woman.',
        dict(childhood_place='Fremantle'), dict(childhood_place='I grew up in Fremantle.'),
        target=20, sequence=12, targets=['childhood_place', 'avatar_style'], reference={
            'name': 'Alex', 'birth_year': None, 'birth_place': 'Hobart',
            'authority': {'name': 'explicit', 'birth_year': 'explicit', 'birth_place': 'explicit'}})
    add('correction', 'I said 1961 before, but that was a mistake. I was born in 1962.',
        dict(birth_year=1962), dict(birth_year='I said 1961 before, but that was a mistake. I was born in 1962.'),
        target=30, sequence=24, targets=['birth_year'], reference={
            'birth_year': 1961, 'authority': {'birth_year': 'inferred'},
            'provenance': {'birth_year': [dict(source_id='prior-source', version=1,
                quote='I was born in 1961.', char_start=0, char_end=19)]}})
    add('other-people',
        'My father was born in 1930 in Perth. My sister said, "I am a woman named Mei." '
        'A book character says, "I grew up in Hobart." My spouse is a woman. '
        'The photograph shows a man. Please change the interface to Chinese.',
        {}, {}, target=1, sequence=1)
    add('reference-is-not-testimony', 'Thank you.', {}, {}, target=5, sequence=4,
        reference={'name': 'Alex', 'birth_place': 'Hobart', 'avatar_style': 'female',
                   'authority': {'name': 'inferred', 'birth_place': 'inferred', 'avatar_style': 'explicit'}},
        targets=[field for field in PROFILE_FIELDS if field != 'avatar_style'])
    add('conflicting-avatar',
        'I might describe myself as a man or as a woman; neither description is settled.',
        {}, {}, target=10, sequence=8, targets=['avatar_style'])
    return rows


def validate_profile_case(case, value):
    """Check original-window citations independently of host normalization."""
    from jsonschema import Draft202012Validator

    Draft202012Validator(case['schema']).validate(value)
    original = case['input']['source']
    for change in value['profile_patch']:
        for ref in change['source_refs']:
            start, end = ref['char_start'], ref['char_end']
            if (ref['source_id'] != original['id'] or ref['version'] != original['version']
                    or type(start) is not int or type(end) is not int
                    or not 0 <= start < end <= len(original['text'])
                    or original['text'][start:end] != ref['quote']):
                raise ValueError('profile_original_window_evidence')
        anchor = case['evidence'].get(change['field'])
        if not anchor or not any(anchor in ref['quote'] for ref in change['source_refs']):
            raise ValueError('profile_fact_evidence')
    validated = validate_profile(value, case['page'])
    actual = {change['field']: change['value'] for change in validated['profile_patch']}
    if actual != case['expected']:
        raise ValueError('profile_semantic_mismatch')


def interviewer_cases():
    from apps.api.interview_strategy import strategy_instructions
    from apps.api.lifetime_memory_continuity import (
        GOVERNED_CONTINUITY_INSTRUCTIONS, governed_collector_schema,
    )
    from apps.api.prompt_composition import render_prompt_artifact

    examples = [
        ('comfort-entry', 'comfort', 'I would like to talk about my childhood.', '我想聊聊小时候的故事。', None),
        ('explore-memory', 'explore', 'Father and I repaired bicycles in our shed.', '我和父亲在院子里修自行车。', None),
        ('shape-order', 'shape', 'I started school before we moved to Perth.', '我先上了学，后来我们搬到了成都。', None),
        ('pause', 'comfort', 'Not today. Stop here.', '今天先到这里。', 'pause'),
        ('redirect', 'explore', "Let’s talk about my garden.", '我想聊我的花园。', 'user_redirect'),
        ('correction', 'shape', 'I meant 1962, not 1961.', '我说错了，是1962年，不是1961年。', 'current_correction'),
        ('photo-only', 'explore', '', '', None),
        ('quoted-control', 'explore', 'Father said, "Stop here." Then I repaired a bicycle.', '父亲说：“今天先到这里。”后来我修了一辆自行车。', None),
    ]
    rows = []
    for locale in ('en-AU', 'zh-CN'):
        for family, strategy, english, chinese, reason in examples:
            text = english if locale == 'en-AU' else chinese
            source = dict(id=f'interviewer-{family}-{locale}', version=1, status='active', text=text) if text else None
            context = dict(source=source, sources=[source] if source else [], events=[], photos=[],
                photo_context=[], strategy_selector=True, two_lane_memory=True,
                interview_language=locale, opening_turn=family == 'comfort-entry',
                has_accepted_narration=bool(source), strategy_context={'mode': 'active', 'plan': None})
            if family == 'photo-only':
                context['photo_context'] = [dict(photo_id='reference:synthetic-garden', kind='public_reference',
                    title='A garden reference', provenance='public_reference')]
            instructions = (strategy_instructions(strategy) + '\n' + render_prompt_artifact(
                prompt_path(f'memoir/skills/memoir-interviewer/language/{locale}')) + '\n' + GOVERNED_CONTINUITY_INSTRUCTIONS)
            rows.append(dict(id=f'interviewer-{family}-{locale}', skill='memoir-interviewer',
                locale=locale, case_family=family, instructions=instructions, input=context,
                schema=governed_collector_schema(context), validator='interviewer',
                expected=dict(question=family != 'pause', selection_reason=reason),
                scope='isolated foreground proposal; no saved-turn or delivery certification'))
    return rows


def cases():
    rows = profile_cases()
    rows.extend(interviewer_cases())
    for locale in ('en-AU', 'zh-CN'):
        original = source(locale)
        rows.extend([
            dict(id='timeline-evidence-' + locale, skill='memoir-author-timeline',
                 instructions=extraction_instructions() + '\n' + EXTRACTION_WINDOW_CONTRACT,
                 schema=extraction_schema(), input={'sources': [original], 'saved_events': []},
                 original=original, validator='extraction'),
        ])
    rows.append(dict(id='family-explicit-mother', skill='memoir-family-tree', schema=None,
        instructions=skill_prompt('memoir-family-tree'),
        input={'fixture_scope': 'isolated contract test; no entitlement or persistence claim',
               'family_enabled': True, 'saved_people': [],
               'storyteller_message': 'My mother is named Mei. She repaired bicycles in our shed.'},
        validator='family'))
    rows.append(dict(id='journey-two-places', skill='memoir-place-journey', schema=None,
        instructions=skill_prompt('memoir-place-journey'),
        input={'storyteller_message': 'I moved from Sydney to Perth. I used to walk beside the river.'},
        validator='journey'))
    places = [dict(place='Sydney', hierarchy=['Earth', 'Australia', 'New South Wales', 'Sydney'],
                   granularity='city', latitude=-33.87, longitude=151.21),
              dict(place='Chatswood', hierarchy=['Earth', 'Australia', 'New South Wales', 'Sydney', 'Chatswood'],
                   granularity='suburb', latitude=-33.797, longitude=151.183)]
    rows.append(dict(id='groups-independent-child-pin', skill='memoir-place-groups',
        instructions='', schema=None, input={'places': places},
        expected={'city_groups': 1, 'independent_pins': 2}, validator='grouping',
        execution='deterministic', scope='actual production grouping; no skill model invocation'))
    rows.append(dict(id='story-game-missing-authority', skill='memoir-story-game',
        instructions=skill_prompt('memoir-story-game', 'references/runtime-contract.md') + eval_fragment('story-game'),
        schema=object_schema({'generation_permitted': {'type': 'boolean'}, 'game_generated': {'type': 'boolean'},
                              'invent_author_approval': {'type': 'boolean'}}),
        input={'phase': 'shape', 'manuscript_status': 'draft', 'completion_receipt': None,
               'adaptation_consent': None, 'game_runtime_bindings': True},
        expected=dict(generation_permitted=False, game_generated=False, invent_author_approval=False),
        validator='equal', scope='negative admission probe; successful generation/publication is evaluated separately'))
    rows.append(dict(id='historical-reject-unverified-lead', skill='memoir-historical-news-research',
        instructions=skill_prompt('memoir-historical-news-research', 'references/contract.md') + eval_fragment('historical-lead'),
        schema=object_schema({'verified_clues': {'type': 'integer'}, 'creates_memory_event': {'type': 'boolean'},
                              'private_name_in_query': {'type': 'boolean'}}),
        input={'native_search_receipt': None, 'inspected_page': None,
               'unverified_model_lead': 'A festival occurred in Sydney in 2000.',
               'private_narrator_name': 'Synthetic Person'},
        expected=dict(verified_clues=0, creates_memory_event=False, private_name_in_query=False),
        validator='equal', scope='negative provenance probe; successful native discovery is checked separately'))
    rows.append(dict(id='photo-reject-unverified-lead', skill='memoir-place-photo-research',
        instructions=skill_prompt('memoir-place-photo-research') + eval_fragment('photo-lead'),
        schema=object_schema({'capture_period': {'type': 'string'}, 'verified_photos': {'type': 'integer'},
                              'download_permitted': {'type': 'boolean'}}),
        input={'request': 'Find pictures of Sydney.', 'previous_memoir_topic': 'Childhood in the 1980s',
               'native_search_receipt': None, 'inspected_source_page': None, 'rights_evidence': None,
               'unverified_model_description': 'A street photograph taken in 1983.'},
        expected=dict(capture_period='present_day', verified_photos=0, download_permitted=False),
        validator='equal', scope='negative provenance probe; successful native discovery is checked separately'))
    return rows


def validate_case(case, value):
    kind = case['validator']
    if kind == 'grouping':
        observed = dict(city_groups=len({place['city_key'] for place in value['places']}),
                        independent_pins=sum(place['pin'] is not None for place in value['places']))
        if observed != case['expected']:
            raise ValueError('grouping_membership_or_pin_coverage')
    elif kind == 'interviewer':
        from apps.api.lifetime_memory_continuity import validate_governed_collector_result
        result = validate_governed_collector_result(value, case['input'])
        outcome = result['strategy_outcome']
        if bool(outcome['question_delivered']) != case['expected']['question']:
            raise ValueError('interviewer_question_disposition')
        if case['expected']['selection_reason'] and outcome['selection_reason'] != case['expected']['selection_reason']:
            raise ValueError('interviewer_current_intent')
        if not case['input'].get('source') and result.get('associations'):
            raise ValueError('photo_is_not_narrator_testimony')
    elif kind == 'equal':
        if value != case['expected']:
            raise ValueError('semantic_mismatch')
    elif kind == 'profile':
        validate_profile_case(case, value)
    elif kind == 'extraction':
        events = validate_extraction(value, [case['original']], [])
        if not events or not any(e.get('life_stage') == 'childhood' for e in events):
            raise ValueError('missing_grounded_childhood_event')
        if any(e.get('person_ids') for e in events):
            raise ValueError('invented_person_identity')
        for event in events:
            for ref in event['source_refs']:
                if 'bicycl' not in ref['quote'].lower() and '自行车' not in ref['quote']:
                    continue
                return
        raise ValueError('lost_source_fact')
    elif kind == 'family':
        _, tree = extract_family_tree_context(value)
        if not tree or not any(p['name'] == 'Mei' and p.get('family_title') == 'mother'
                               and 'bicycl' in p.get('introduction', '').lower() for p in tree['people']):
            raise ValueError('missing_grounded_mother')
    elif kind == 'journey':
        _, journeys = extract_place_journeys(value)
        if [p['place'] for p in journeys] != ['Sydney', 'Perth']:
            raise ValueError('place_coverage_or_grounding')
    else:
        raise ValueError('unknown_validator')
