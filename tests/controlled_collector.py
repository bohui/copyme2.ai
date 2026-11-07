"""Synthetic provider output for native orchestration tests, never quality evidence."""

import json
import httpx


def worker_reply(request, result):
    """Honor worker framing even for a JSON caller awaiting early acknowledgement."""
    body = json.loads(request.content)
    if (body.get('bounded_lane') or {}).get('phase') == 'extract':
        from controlled_skill_harness import complete_timing_hints
        try:
            output = json.loads(result['reply'])
        except (TypeError, ValueError):
            pass
        else:
            result = {**result,'reply':json.dumps(complete_timing_hints(output))}
    if request.headers.get('accept') == 'application/x-ndjson':
        events = [{'type': 'text_delta', 'text': result['reply']},
                  {'type': 'provider_complete', 'data': result},
                  {'type': 'result', 'data': result}]
        return httpx.Response(200, headers={'Content-Type': 'application/x-ndjson'},
                              content=''.join(json.dumps(event) + '\n' for event in events))
    return httpx.Response(200, json=result)


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
