"""Place proposals are repaired before the canonical SQL commit boundary."""
from copy import deepcopy

import pytest

from apps.api.conversation_attribution import validate_attribution
from test_conversation_attribution import Conversation, empty, episode, reference
from test_background_profile_workflow import database
from test_lifetime_memory_postgres import sql, event_database, private_database, attachment_database  # noqa: F401


@pytest.mark.parametrize('hierarchy', [
    ['Earth', '中国', '四川省', '成都市'],
    ['地球', '中国', '四川省', '成都'],
])
def test_noncanonical_event_place_cannot_pass_python_then_fail_sql(hierarchy):
    text = '小时候，我在成都学拉小提琴，那是在1978年。'
    ref = dict(source_id='source', version=1, quote=text, char_start=None, char_end=None)
    event = dict(kind='event', title='在成都学习小提琴', source_refs=[ref])
    raw = dict(events=[event], event_places=[dict(event_index=0, role='setting',
        place=dict(place='成都', hierarchy=hierarchy, granularity='city'), source_ref=ref)])
    page = {'source':dict(id='source', version=1, text=text, char_start=0)}
    accepted = deepcopy([event])
    accepted[0]['source_refs'][0].update(char_start=0, char_end=len(text))
    with pytest.raises(ValueError, match='Event place hierarchy'):
        validate_attribution(raw, page, accepted)


def test_place_hierarchy_repairs_same_source_before_sql_commit(sql, tmp_path, monkeypatch):
    attempts = []
    text = '小时候，我在成都学拉小提琴，那是在1978年。'
    def extract(packet):
        attempts.append(deepcopy(packet))
        label = '成都市' if len(attempts) == 1 else '成都'
        return {**empty(packet), 'events':[episode(packet, text, title='在成都学习小提琴')],
            'event_places':[dict(event_index=0, role='setting',
                place=dict(place='成都', hierarchy=['Earth', '中国', '四川省', label], granularity='city'),
                source_ref=reference(packet, text))]}
    conversation = Conversation(sql, tmp_path, monkeypatch, extract)
    with conversation.client:
        accepted = conversation.say(text)
        conversation.drain()
        assert len(attempts) == 2
        assert attempts[1]['retry_reason'] == 'PLACE_HIERARCHY'
        assert attempts[0]['sources'] == attempts[1]['sources']
        result = conversation.attribution(accepted['accepted_source_id'])
        assert result['complete'] and result['resolved']
        place = result['items'][0]['event']['places'][0]['place']
        assert place['place'] == place['hierarchy'][-1] == '成都'
        assert place['hierarchy'][0] == 'Earth'


def test_place_hierarchy_guidance_is_scoped_to_that_repair():
    from apps.api.lifetime_memory_lane_engine import lane_contract
    from test_lifetime_composer_capacity import page
    from test_lifetime_memory_lane_engine import fence_for
    current = page(text='小时候，我在成都学拉小提琴，那是在1978年。')
    current['two_lane'] = dict(schema_version=1, task_version='two-lane-v1', execution_generation=1,
        phase_revision=0, work_mode='extract', reply_contract='reply-v2')
    current['attribution_context'] = dict(schema_version=1, decision='extract', reason='new_testimony', delivered_event=None)
    fence = fence_for(current)
    normal_instructions, normal = lane_contract('extract', fence.locale, two_lane=True, fence=fence)
    _, unrelated = lane_contract('extract', fence.locale, two_lane=True, fence=fence, retry_reason='DATE_NUMERIC')
    repair_instructions, repair = lane_contract('extract', fence.locale, two_lane=True, fence=fence, retry_reason='PLACE_HIERARCHY')
    guidance = repair['$defs']['CoarsePlace']['properties']['hierarchy'].pop('description')
    assert 'must exactly equal' in guidance and 'place field' in guidance
    assert normal_instructions == repair_instructions
    assert normal == unrelated == repair
