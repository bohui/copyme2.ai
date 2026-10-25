"""Controlled review witnesses for structural replays, never semantic evidence."""
from copy import deepcopy


def controlled_review(packet, *, findings=()):
    requirements = packet['requirements']
    checks = [{**deepcopy(unit), 'verdict': 'supported',
        'explanation': 'Controlled supported-prose fixture.'} for unit in requirements['prose']]
    contributions = []
    for original in requirements['contributions']:
        ref = original['source_ref']
        unit = next((unit for unit in requirements['prose'] if any(
            r['source_id'] == ref['source_id'] and str(r['version']) == str(ref['version'])
            and r['char_start'] < ref['char_end'] and r['char_end'] > ref['char_start']
            for r in unit['source_refs'])), None)
        contributions.append({**deepcopy(original), 'disposition': 'represented' if unit else 'deferred',
            'prose': [{key: unit[key] for key in ('section_id', 'field', 'excerpt')}] if unit else [],
            'reason': 'Controlled representation fixture.' if unit else 'Outside this controlled sample.'})
    return dict(contract_version=2, ready_for_user_review=True, publication_approved=False,
        findings=deepcopy(list(findings)), prose_checks=checks, contributions=contributions)


def controlled_section_review(claim, sections):
    units = []
    for section in sections:
        for container, names in [('block', ('text', 'caption', 'alt')), ('heading', ('title', 'subtitle'))]:
            for field in names:
                if section.get(container, {}).get(field):
                    units.append(dict(section_id=section['id'], field=field, excerpt=section[container][field],
                        source_refs=[{**ref, 'version': str(ref['version'])} for ref in section['source_refs']]))
    originals = {}
    for event in claim.get('batch', {}).get('events', [claim['partition']]):
        for ref in event['source_refs']:
            normalized = {key: str(value) if key == 'version' else value
                for key, value in ref.items() if key in ('source_id', 'version', 'char_start', 'char_end')}
            originals[tuple(normalized.values())] = dict(source_ref=normalized, quote=ref['quote'])
    return controlled_review(dict(requirements=dict(prose=units, contributions=list(originals.values()))))
