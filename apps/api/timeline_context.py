"""Authorized conversation excerpts and placement dependencies for Lane B."""
from copy import deepcopy

CONFIDENCE_THRESHOLD = 0.85


def context_sources(context):
    context = context or {}
    rounds = context.get('conversation_history', [])
    if not isinstance(rounds, list) or len(rounds) > 20:
        raise ValueError('Timeline context requires at most twenty prior rounds')
    sources = [item['source'] for item in rounds if item.get('source')]
    sources.extend((context.get('last_event') or {}).get('original_passages', []))
    return sources


def placement_links(events):
    """Only sufficiently supported model placements become saved map links."""
    links = []
    for index, event in enumerate(events):
        location = event.get('location')
        if location and not event.get('candidate_ids') and (event.get('locationConfidenceScore') or 0) >= CONFIDENCE_THRESHOLD:
            ref = next((ref for ref in event.get('location_basis', []) if location['place'] in ref['quote']), None)
            if ref:
                links.append(dict(event_index=index, role='setting', place=deepcopy(location), source_ref=deepcopy(ref)))
    return links
