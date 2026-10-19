"""Leading language commands remain distinct from quoted or narrated speech."""
import pytest

from apps.api.conversation_locale import explicit_request


@pytest.mark.parametrize('text,expected',[
    ('Please reply in Chinese from now on. 我想聊上学的事。','zh-CN'),
    ('Please respond to me in English from now on please. 我还记得那条路。','en-AU'),
    ('reply in Chinese from now on! I remember school.','zh-CN'),
    ('接下来请用英语回答。I want to talk about school.','en-AU'),
    ('接下来用中文交流。我想继续聊花园。','zh-CN'),
    ('请接下来用中文。我不记得姐姐那天说了什么。','zh-CN'),
    ('以后请使用英文回复我。I remember the garden.','en-AU'),
    ('Please continue in English. I remember the classroom.','en-AU'),
    ('请用中文回答。','zh-CN'),
])
def test_leading_language_command_with_following_testimony(text,expected):
    assert explicit_request(text)==expected


@pytest.mark.parametrize('text',[
    '"Please reply in Chinese from now on." My mother said that in class.',
    '“接下来请用英语回答。”那是老师说的。',
    '母亲说“接下来请用英语回答。”我记得那堂课。',
    'We replied in Chinese from then on. I remember school.',
    'Please reply in English class. That is what the teacher said.',
    'Please reply in Chinese from now on at school. My teacher said that.',
    '接下来请用英语回答这道题。老师就是这样对我说的。',
    '请用中文这两个字命名我的照片。',
    'I remember school. Please reply in Chinese from now on.',
    '我记得那堂课。接下来请用英语回答。',
])
def test_quotes_recollections_and_nonleading_requests_do_not_change_language(text):
    assert explicit_request(text) is None
