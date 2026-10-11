"""Synthetic provider output for native orchestration tests, never quality evidence."""


def extraction_proposal(language='en-AU'):
    chinese = language == 'zh-CN'
    return {
        'acknowledgement': '谢谢您分享这段回忆。' if chinese else 'Thank you for sharing that memory.',
        'plan': {'candidates': [{'id': 'next-memory',
            'question': '您还记得哪些细节？' if chinese else 'What other details do you remember?',
            'order': 0, 'bridge': '', 'context': {'event_id': None, 'photo_id': None,
                                                 'life_stage': None, 'year': None}}],
            'chosen_id': 'next-memory', 'active_event_id': None,
            'work': {'mode': 'extract', 'name': None}},
        'associations': [], 'response_photo_ids': [], 'stopped': False,
    }
