"""Offline contract checks only; never authenticates, generates, saves or delivers a game."""
import argparse
import hashlib
import json
import re
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[1]
MAX_BYTES = 2 * 1024 * 1024
SCHEMAS = {name: json.loads((ROOT / 'schemas' / f'{name}.schema.json').read_text())
           for name in ('request', 'candidate', 'game')}
REGISTRY = Registry().with_resources(
    (schema['$id'], Resource.from_contents(schema)) for schema in SCHEMAS.values())


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def text_digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def candidate_digest(candidate):
    return digest({key: value for key, value in candidate.items() if key != 'review'})


def idempotency_key(request):
    """Logical dependency key; a changed lease still invalidates the candidate digest."""
    return digest({key: value for key, value in request.items() if key != 'job'})


def schema_valid(name, value):
    return Draft202012Validator(SCHEMAS[name], registry=REGISTRY).is_valid(value)


def _unique(records, key):
    return len({item[key] for item in records}) == len(records)


def _grant(permission, subject, epoch):
    return (permission is not None and permission['subject_id'] == subject
            and permission['policy_epoch'] == epoch)


def admission_errors(request):
    """Validate supplied assertions; the host must independently authenticate them."""
    if not schema_valid('request', request):
        return ['REQUEST_SCHEMA']
    r = request
    errors = []
    if r['phase']['phase'] != 'shape':
        errors.append('SHAPE_REQUIRED')
    m = r['manuscript']
    if m['kind'] != 'formal_memoir':
        errors.append('FORMAL_MANUSCRIPT_REQUIRED')
    if (m['digest'] != digest(m['chapters'])
            or any(ch['digest'] != text_digest(ch['text']) for ch in m['chapters'])):
        errors.append('MANUSCRIPT_DIGEST')
    if r['source_manifest_digest'] != digest(r['evidence']):
        errors.append('SOURCE_MANIFEST_DIGEST')
    for records in (m['chapters'], r['people'], r['evidence'], r['approved_lines']):
        if not _unique(records, 'id'):
            errors.append('DUPLICATE_SERVER_ID')
    if not _unique(r['assets'], 'key'):
        errors.append('DUPLICATE_ASSET_KEY')
    completion = r['completion']
    binding = {'manuscript_id': m['id'], 'manuscript_revision': m['revision'],
               'manuscript_digest': m['digest']}
    if completion is None:
        errors.append('COMPLETION_AUTHORITY_REQUIRED')
    else:
        if any(completion[key] != value for key, value in binding.items()):
            errors.append('COMPLETION_BINDING')
        expected = [{key: ch[key] for key in ('id', 'revision', 'digest')} for ch in m['chapters']]
        if completion['chapter_coverage'] != expected:
            errors.append('COMPLETION_COVERAGE')
        if (not completion['validation_passed'] or completion['pending_count']
                or completion['blocking_count']
                or completion['source_manifest_digest'] != r['source_manifest_digest']):
            errors.append('COMPLETION_VALIDATION')
    consent = r['consent']
    if consent is None:
        errors.append('ADAPTATION_CONSENT_REQUIRED')
    elif (consent['status'] != 'active' or consent['policy_epoch'] != r['policy_epoch']
          or any(consent[key] != value for key, value in binding.items())):
        errors.append('ADAPTATION_CONSENT_INVALID')

    chapters = {ch['id']: ch for ch in m['chapters']}
    evidence = {item['id']: item for item in r['evidence']}
    for source in r['evidence']:
        if (source['status'] != 'active' or source['adaptation_allowed'] is not True
                or source['role'] not in ('narrator', 'explicit_confirmation')
                or source['chapter_id'] not in chapters):
            errors.append('EVIDENCE_PERMISSION_OR_LINEAGE')
    people = {person['id']: person for person in r['people']}
    approved = {line['id']: line for line in r['approved_lines']}
    for person in people.values():
        if not person['adaptation_allowed']:
            errors.append('PERSON_PERMISSION')
        if person['age_category'] != 'adult' and not _grant(
                person['specific_permission'], person['id'], r['policy_epoch']):
            errors.append('PERSON_SPECIFIC_PERMISSION')
        if person['alias_line_id'] not in approved:
            errors.append('PERSON_ALIAS')
    for line in approved.values():
        if not set(line['person_ids']).issubset(people):
            errors.append('LINE_PERSON_REFERENCE')
        if line['npc_person_id'] is not None and (
                line['npc_person_id'] not in people or line['npc_person_id'] not in line['person_ids']):
            errors.append('LINE_NPC_REFERENCE')
        if line['sensitive'] and not _grant(line['specific_permission'], line['id'], r['policy_epoch']):
            errors.append('SENSITIVE_PERMISSION')
        ref = line['manuscript']
        chapter = chapters.get(ref['chapter_id'])
        if (chapter is None or chapter['revision'] != ref['revision']
                or not 0 <= ref['start'] < ref['end'] <= len(chapter['text'])):
            errors.append('MANUSCRIPT_SPAN')
        elif line['mode'] == 'quote' and line['text'] != chapter['text'][ref['start']:ref['end']]:
            errors.append('MANUSCRIPT_QUOTE')
        for source_ref in line['evidence']:
            source = evidence.get(source_ref['evidence_id'])
            if (source is None or source['version'] != source_ref['version']
                    or source['chapter_id'] != ref['chapter_id']
                    or source['status'] != 'active' or not source['adaptation_allowed']
                    or source['role'] not in ('narrator', 'explicit_confirmation')):
                errors.append('EVIDENCE_PERMISSION_OR_LINEAGE')
            elif not 0 <= source_ref['start'] < source_ref['end'] <= len(source['text']):
                errors.append('EVIDENCE_SPAN')
            elif line['mode'] == 'quote' and line['text'] != source['text'][source_ref['start']:source_ref['end']]:
                errors.append('EVIDENCE_QUOTE')
    return sorted(set(errors))


def _server_ids(value):
    """Collect identifiers, not prose, from the server-only authority envelope."""
    found = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if (key == 'id' or key.endswith('_id')) and isinstance(item, str):
                found.add(item)
            elif key.endswith('_ids') and isinstance(item, list):
                found.update(entry for entry in item if isinstance(entry, str))
            found.update(_server_ids(item))
    elif isinstance(value, list):
        for item in value:
            found.update(_server_ids(item))
    return found


def game_errors(request, candidate):
    g = candidate['game']
    errors = []
    texts = {item['id']: item['text'] for item in g['texts']}
    scenes = {scene['id']: scene for scene in g['scenes']}
    npcs = {npc['id']: npc for npc in g['npcs']}
    ids = [g['package_id'], g['protagonist']['id']] + [item['id'] for records in
           (g['texts'], g['scenes'], g['npcs']) for item in records]
    if len(set(ids)) != len(ids):
        errors.append('DUPLICATE_BROWSER_ID')
    if set(ids) & (_server_ids(request) | _server_ids(candidate['review'])):
        errors.append('CANONICAL_ID_LEAK')
    url_pattern = r'(?:[a-z][a-z0-9+.-]*://|//|www\.|\b(?:https?|ftp|file|data|javascript|vbscript|blob|mailto|tel|sms|wss?):)'
    if any(re.search(url_pattern, text, re.I) for text in texts.values()):
        errors.append('URL_OR_SCHEME_IN_TEXT')
    used_texts = {g['title_text_id'], g['protagonist']['alias_text_id']}
    used_assets = {g['protagonist']['asset_key']}
    for scene in scenes.values():
        used_texts.add(scene['title_text_id'])
        used_assets.add(scene['asset_key'])
        if scene['spawn_x'] > scene['width']:
            errors.append('SPAWN_BOUNDS')
        for side, opposite in (('left', 'right'), ('right', 'left')):
            edge = scene[side]
            if edge is None:
                continue
            target = scenes.get(edge['scene_id'])
            if target is None or target['id'] == scene['id']:
                errors.append('SCENE_REFERENCE')
            elif (edge['spawn_x'] > target['width'] or target[opposite] is None
                  or target[opposite]['scene_id'] != scene['id']):
                errors.append('SCENE_CONTINUITY')
    reached, pending = set(), [g['start_scene_id']]
    while pending:
        key = pending.pop()
        if key in reached or key not in scenes:
            continue
        reached.add(key)
        pending.extend(scenes[key][side]['scene_id'] for side in ('left', 'right')
                       if scenes[key][side] is not None)
    if reached != set(scenes):
        errors.append('DISCONNECTED_SCENES')
    for npc in npcs.values():
        used_texts.update([npc['alias_text_id'], *npc['dialogue_text_ids']])
        used_assets.add(npc['asset_key'])
        if npc['scene_id'] not in scenes or npc['x'] > scenes[npc['scene_id']]['width']:
            errors.append('NPC_BOUNDS')
    if used_texts != set(texts):
        errors.append('TEXT_REFERENCE_OR_HIDDEN_TEXT')
    if not used_assets.issubset({asset['key'] for asset in request['assets']}):
        errors.append('ASSET_NOT_ALLOWLISTED')

    lines = {line['id']: line for line in request['approved_lines']}
    grounding = {item['text_id']: item['approved_line_id'] for item in candidate['grounding']}
    if set(grounding) != set(texts) or not _unique(candidate['grounding'], 'text_id'):
        errors.append('GROUNDING_COVERAGE')
    for key, line_id in grounding.items():
        if line_id not in lines or key not in texts or lines[line_id]['text'] != texts[key]:
            errors.append('UNAPPROVED_TEXT')
    identities = {item['npc_id']: item['person_id'] for item in candidate['identities']}
    people = {person['id']: person for person in request['people']}
    if (set(identities) != set(npcs) or not _unique(candidate['identities'], 'npc_id')
            or not _unique(candidate['identities'], 'person_id')):
        errors.append('IDENTITY_COVERAGE')
    for key, person_id in identities.items():
        if person_id not in people or key not in npcs:
            errors.append('UNKNOWN_PERSON')
        elif grounding.get(npcs[key]['alias_text_id']) != people[person_id]['alias_line_id']:
            errors.append('NPC_ALIAS_BINDING')
        else:
            for text_id in npcs[key]['dialogue_text_ids']:
                line = lines.get(grounding.get(text_id))
                if line is None or line['npc_person_id'] != person_id:
                    errors.append('NPC_DIALOGUE_BINDING')
    return sorted(set(errors))


def validate(request, candidate, current_request=None):
    """Return codes only. A valid result is an offline check, never a delivery grant."""
    errors = admission_errors(request)
    if not schema_valid('candidate', candidate):
        errors.append('CANDIDATE_SCHEMA')
    if errors:
        return {'status': 'blocked', 'codes': sorted(set(errors))}
    if current_request is None:
        errors.append('CURRENT_AUTHORITY_REQUIRED')
    else:
        errors.extend(admission_errors(current_request))
        if digest(current_request) != digest(request):
            errors.append('STALE_AUTHORITY_OR_FENCE')
    if candidate['request_digest'] != digest(request):
        errors.append('REQUEST_BINDING')
    review = candidate['review']
    if review is None:
        errors.append('AUTHOR_REVIEW_REQUIRED')
    elif (review['candidate_digest'] != candidate_digest(candidate)
          or review['reviewer_actor_id'] != request['actor_id']):
        errors.append('AUTHOR_REVIEW_BINDING')
    errors.extend(game_errors(request, candidate))
    return {'status': 'blocked' if errors else 'valid_offline', 'codes': sorted(set(errors))}


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def load_json(path):
    with Path(path).open('rb') as stream:
        data = stream.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError('input too large')
    return json.loads(data, object_pairs_hook=_pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError('non-finite JSON')))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', required=True)
    parser.add_argument('--candidate', required=True)
    parser.add_argument('--current-request')
    args = parser.parse_args()
    try:
        result = validate(load_json(args.request), load_json(args.candidate),
                          load_json(args.current_request) if args.current_request else None)
    except (OSError, ValueError, RecursionError):
        result = {'status': 'blocked', 'codes': ['INVALID_INPUT']}
    print(json.dumps(result))
    return 0 if result['status'] == 'valid_offline' else 1


if __name__ == '__main__':
    raise SystemExit(main())
