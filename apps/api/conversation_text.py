"""Recover visible user text from the browser's legacy instruction wrapper."""


def original_conversation_text(text: str) -> str:
    prefix = 'The storyteller said: '
    if not text.startswith(prefix):
        return text
    boundaries = [text.find('\n' + instruction, len(prefix)) for instruction in (
        "This is the storyteller's first answer to the shared profile-intake opening.",
        'Acknowledge the storyteller naturally, then ask one gentle open-ended follow-up question.',
        'Acknowledge the storyteller briefly, then ask one gentle follow-up question about their memory.',
    )]
    boundaries = [index for index in boundaries if index >= 0]
    # Require a known wrapper and instruction boundary; ordinary messages,
    # including multiline text and quoted instructions, stay untouched.
    return text[len(prefix):min(boundaries)] if boundaries else text
