from apps.api.stage_readiness import readiness, stage_readiness, word_equivalents


def row(id, words, stage='childhood', **changes):
    return {'id':id, 'kind':'agent', 'project_id':'p', 'life_stage':stage,
            'content':'Storyteller: ' + 'memory ' * words + '\nMemory Spark: ' + 'invention ' * 2000, **changes}


def test_requested_boundaries_and_cap():
    assert readiness(100) == {'word_equivalents':100,'percent':10.0,'color':'red'}
    assert readiness(300) == {'word_equivalents':300,'percent':30.0,'color':'amber'}
    assert readiness(650)['percent'] == 40
    assert readiness(999)['color'] == 'amber'
    assert readiness(1000) == {'word_equivalents':1000,'percent':50.0,'color':'green'}
    assert readiness(5000)['percent'] == 50


def test_language_aware_units_ignore_punctuation_emoji_and_instructions():
    assert word_equivalents("我住在苏州。I remember mother's well-loved garden. 1960 🙂") == 11
    wrapped = row('a', 0, content="Storyteller: The storyteller said: 我记得花园\nAcknowledge the storyteller naturally, then ask one gentle open-ended follow-up question.\nMemory Spark: assistant words")
    assert stage_readiness([wrapped],'p')['childhood']['word_equivalents'] == 5


def test_retries_edits_deletes_reassignment_and_project_scope():
    initial = row('a',100)
    assert stage_readiness([initial,initial],'p')['childhood']['percent'] == 10
    edited = row('a',300,stage='midlife')
    result = stage_readiness([initial,edited,row('b',1000,project_id='other'),row('c',1000,kind='tool')],'p')
    assert result['childhood']['word_equivalents'] == 0
    assert result['midlife']['percent'] == 30
    assert stage_readiness([],'p')['midlife']['percent'] == 0
    assert stage_readiness([row('d',100,content='Storyteller: unfinished')],'p')['childhood']['word_equivalents'] == 0
