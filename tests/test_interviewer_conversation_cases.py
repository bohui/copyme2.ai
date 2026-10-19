"""Real-prefix builders cannot leak later answers or mislabel gate fixtures."""
from copy import deepcopy

from scripts import memoir_skill_eval_suite as suite
from scripts.interviewer_conversation_cases import conversation_cases


def test_prefixes_are_exact_and_counterfactuals_are_separate():
    template = suite.plan(case=['memoir-interviewer/grounded-question/zh-CN'])['items'][0]
    sources = [dict(id='s'+str(n), version=1, sequence=n, project_id='selected-project',
        status='active', text=text, language='zh-CN', kind='narrator_chat')
        for n, text in enumerate(['小时候我和朋友玩。', '我们坐车去河边。'], 1)]
    turns = [dict(source_id=s['id'], collector=dict(reply='您还记得什么？')) for s in sources]
    before = deepcopy((sources, turns, template))
    rows = conversation_cases(template, sources, turns)
    originals = [row for row in rows if not row['origin']['synthetic']]
    assert originals[0]['task']['context']['recent_dialogue'] == []
    history = originals[1]['task']['context']['recent_dialogue']
    assert len(history) == 1 and history[0]['narrator'] == sources[0]['text']
    assert history[0]['assistant_is_testimony'] is False
    assert originals[1]['task']['source']['text'] == sources[1]['text']
    assert len({row['id'] for row in rows}) == len(rows)
    probes = {row['case']: row for row in rows if row['origin']['synthetic']}
    assert probes['ready-transition']['task']['context']['breadth_checkpoint']['suggested_stage'] == 'adolescence'
    assert probes['below-gate']['task']['context']['breadth_checkpoint'] is None
    assert probes['ready-pause']['gold']['facts']['question'] is False
    for row in rows:
        request = suite.packet(row)
        assert 'gold' not in request['input'] and 'required' not in request['input']
    assert (sources, turns, template) == before
