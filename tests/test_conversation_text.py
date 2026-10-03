import pytest

from apps.api.conversation_text import original_conversation_text


@pytest.mark.parametrize('instruction', [
    "This is the storyteller's first answer to the shared profile-intake opening.",
    'Acknowledge the storyteller naturally, then ask one gentle open-ended follow-up question.',
    'Acknowledge the storyteller briefly, then ask one gentle follow-up question about their memory.',
])
def test_legacy_wrapper_preserves_multiline_original_and_excludes_attachment_context(instruction):
    original = 'My first line.\n\n第二段。\n'
    wrapped = f'The storyteller said: {original}\n{instruction} More instructions.\nThe storyteller attached these saved sources: []'
    assert original_conversation_text(wrapped) == original


@pytest.mark.parametrize('original', [
    'I remember the storyteller said: hello.\nKeep my original punctuation!',
    'The storyteller said: hello.\nThis is a line I wrote myself.',
    "This is the storyteller's first answer to the shared profile-intake opening.",
    '',
])
def test_ordinary_user_text_is_unchanged(original):
    assert original_conversation_text(original) == original
