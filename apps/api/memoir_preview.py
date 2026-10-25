"""Free composer previews from immutable, authenticated narrator sources."""
import asyncio
import copy
import hashlib
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from pydantic import ValidationError


from .codex_runtime import CodexRuntime
from .codex_timeout_policy import COMPOSER_TIMEOUT, COMPOSER_DRAFT_TIMEOUT
from .conversation_text import original_conversation_text
from .recall import free_recall_rounds
from .stage_readiness import LIFE_STAGES
from .prompt_composition import render_prompt_artifact
from .prompt_artifact import prompt_path


logger = logging.getLogger(__name__)
# Drafting emits a complete structured manuscript. Its private job lease is
# refreshed per phase and lasts 900 seconds; collector budgets are separate.


def composer_timeout(phase):
    return COMPOSER_DRAFT_TIMEOUT if phase == 'draft' else COMPOSER_TIMEOUT


class LifetimeDraftPending(RuntimeError):
    """The governed collection awaits bounded canonical composition support."""


def lifetime_draft_head(storage, project_id):
    rpc=getattr(storage,'lifetime_rpc',None)
    return rpc('read_lifetime_private_draft_head',p_project_id=project_id) if callable(rpc) else None


SKILL = Path(__file__).resolve().parents[2] / 'skills/memoir-composer'


def composer_output_schema(phase):
    if phase not in {'prepare', 'draft', 'review'}:
        raise KeyError(phase)
    if phase == 'prepare':
        from .memory_events import extraction_schema
        shared = extraction_schema()
        return {'type': 'object', 'properties': {'event_id': {'type': 'string'}, 'context': {'type': 'string'},
            'source_refs': {'type': 'array', 'items': {'$ref': '#/$defs/EvidenceRef'}}},
            'required': ['event_id', 'context', 'source_refs'], 'additionalProperties': False,
            '$defs': {'EvidenceRef': shared['$defs']['EvidenceRef']}}
    if phase == 'draft':
        schema = json.loads((SKILL / 'schemas/draft.schema.json').read_text())
        for constant in (schema['properties']['schema_version'], schema['properties']['status'],
                         schema['properties']['counter']['properties']['algorithm']):
            constant['type'] = 'string'
    else:
        from .composer_review import Review
        return Review.model_json_schema()
    # Strict ChatGPT output requires every property. Unknown source offsets
    # remain nullable on the wire rather than forcing invented quote spans.
    ref = schema['$defs']['ref']
    for field in ('char_start', 'char_end'):
        ref['required'].append(field)
        ref['properties'][field]['type'] = ['integer', 'null']
    # Only transmit definitions reachable from the output. Source metadata
    # belongs to the input contract and includes backward-compatible fields.
    definitions = schema['$defs']
    used = set()
    def collect(value):
        if isinstance(value, dict):
            name = value.get('$ref', '').removeprefix('#/$defs/')
            if name in definitions and name not in used:
                used.add(name)
                collect(definitions[name])
            for key, child in value.items():
                if key != '$defs':
                    collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)
    collect(schema)
    schema['$defs'] = {name: value for name, value in definitions.items() if name in used}
    return schema


def normalize_composer_refs(value):
    """Restore omitted optional offsets for the composer skill's validators."""
    if isinstance(value, dict):
        if 'source_id' in value and 'version' in value:
            for field in ('char_start', 'char_end'):
                if field in value and value[field] is None:
                    value.pop(field)
        for child in value.values():
            normalize_composer_refs(child)
    elif isinstance(value, list):
        for child in value:
            normalize_composer_refs(child)
    return value


def normalize_canonical_actions(draft):
    """Choose a single action when a model emits update and carry-forward."""
    chapter_ids = {chapter.get('id') for chapter in draft.get('chapters', [])
                   if isinstance(chapter, dict) and chapter.get('id')}
    if chapter_ids:
        draft['carry_forward_chapter_ids'] = [chapter_id for chapter_id in draft.get('carry_forward_chapter_ids', [])
                                              if chapter_id not in chapter_ids]
    return draft


def normalize_new_chapter_revisions(request, draft):
    prior_ids = {prior['chapter']['id'] for prior in request['prior_state']['chapters']}
    for chapter in draft.get('chapters', []):
        if chapter.get('id') not in prior_ids:
            chapter['base_revision'] = 0
    return draft


def normalize_canonical_event_dispositions(draft):
    """Keep included-event dispositions aligned with the rendered placement.

    The model can mark an event as included while omitting it from every
    active chapter/storyline. Demoting that orphaned disposition is a safe
    metadata correction: it never changes evidence, IDs, or prose.
    """
    placed = set()
    if draft.get('kind') == 'sample_storyline':
        placed.update(draft.get('storyline', {}).get('event_ids', []))
    else:
        for chapter in draft.get('chapters', []):
            if isinstance(chapter, dict):
                placed.update(chapter.get('event_ids', []))
    for entry in draft.get('event_dispositions', []):
        if not isinstance(entry, dict) or entry.get('disposition') != 'included':
            continue
        if entry.get('event_id') in placed:
            continue
        entry['disposition'] = 'deferred'
        entry['chapter_ids'] = []
        reason = str(entry.get('reason') or '').strip()
        suffix = '事件未在当前章节中落位，暂缓纳入本次样章。'
        entry['reason'] = f'{reason} {suffix}'.strip()
    return draft


def composer_instructions(phase):
    if phase not in {"prepare", "draft", "review"}:
        raise KeyError(phase)
    return render_prompt_artifact(prompt_path(f'memoir/skills/memoir-composer/{phase}'))

def json_reply(text):
    text = text.strip()
    if text.startswith(('```json\n', '```\n')) and text.endswith('```'):
        text = text.split('\n', 1)[1][:-3].strip()
    result = json.loads(text)
    if not isinstance(result, dict):
        raise ValueError('The composer must return a JSON object')
    return result


async def skill_operation(operation, request, draft=None):
    # Feed private content over stdin, never shell arguments or shared temp files.
    program = '''
import {preparePlan, validateDraft, renderArtifacts} from './skills/memoir-composer/scripts/lib.mjs';
let input = ''; for await (const chunk of process.stdin) input += chunk;
const {operation, request, draft} = JSON.parse(input);
let result;
if (operation === 'plan') result = preparePlan(request);
else if (operation === 'validate') result = validateDraft(request, draft);
else result = renderArtifacts(request, draft);
process.stdout.write(JSON.stringify(result));
'''
    process = await asyncio.create_subprocess_exec(
        'node', '--input-type=module', '-e', program, cwd=SKILL.parents[1],
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(json.dumps({
            'operation': operation, 'request': request, 'draft': draft,
        }).encode()), timeout=30)
    except BaseException:
        process.kill()
        await process.wait()
        raise
    if process.returncode:
        raise RuntimeError('Memoir composer validation or rendering failed')
    return json.loads(stdout)


async def composer_call(runtime, storage, project_id, language, phase, packet):
    if not runtime.worker_url or not runtime.worker_secret:
        raise RuntimeError('Memoir composer is unavailable')
    if not getattr(runtime, 'lifetime_bounded', False):
        raise ValueError('A canonical composer lane is required')
    started = time.monotonic()
    outcome, worker_elapsed_ms = 'failed', -1
    try:
        from .lifetime_memory_composer import lane_model_budget
        from .lifetime_memory_lane_engine import build_bounded_lane_input, send_bounded_lane_request
        budget = lane_model_budget(composer=True)
        try:
            bounded = build_bounded_lane_input(runtime.lifetime_page, phase=phase, packet=packet, budget=budget)
        except ValidationError as error:
            issues = error.errors(include_input=False)
            if (phase != 'draft' or packet.get('candidate') is None or len(issues) != 1
                    or str(issues[0].get('ctx', {}).get('error')) !=
                    'Bounded lane instructions, packet, schema and framing exceed budget'):
                raise
            # Regenerate from unchanged originals when the failed draft fills the context.
            packet = {key: value for key, value in packet.items() if key not in {'candidate', 'validation', 'review', 'review_errors'}}
            bounded = build_bounded_lane_input(runtime.lifetime_page, phase=phase, packet=packet, budget=budget)
        worker_started = time.monotonic()
        try:
            result = await send_bounded_lane_request(worker_url=runtime.worker_url, worker_secret=runtime.worker_secret,
                bounded_lane=bounded, worker_transport=runtime.worker_transport,
                publisher=runtime.lane_publisher, timeout=composer_timeout(phase) + 15)
        finally:
            worker_elapsed_ms = int((time.monotonic() - worker_started) * 1000)
        from .lifetime_memory_lane_engine import lane_artifact_digest
        artifact = json_reply(result['reply'])
        if phase == 'draft':
            normalize_new_chapter_revisions(packet['request'], artifact)
        await runtime.lane_broker.rpc('record_lifetime_lane_output',
            p_lane_id=runtime.lifetime_page['lane_id'], p_token=runtime.lifetime_page['token'],
            p_page_number=runtime.lifetime_page['page_number'], p_phase=phase,
            p_digest=lane_artifact_digest(phase, artifact), p_page_digest=runtime.lifetime_page['page_digest'])
        outcome = 'completed'
        return normalize_composer_refs(artifact)
    finally:
        logger.info('memoir_preview canonical_page phase=%s page=%d elapsed_ms=%d worker_elapsed_ms=%d outcome=%s',
            phase, runtime.lifetime_page['page_number'], (time.monotonic() - started) * 1000,
            worker_elapsed_ms, outcome)


def source_snapshot(rows, project_id):
    metadata = {str(row['id']): row for row in rows if row.get('id')}
    sources = CodexRuntime._task_sources(metadata.values())
    snapshot = []
    for source in sources:
        row = metadata[source.id]
        stage = row.get('life_stage')
        stage = stage if stage in LIFE_STAGES else 'unplaced'
        order = int(row.get('source_sequence') or 0)
        # Runtime sequence numbers are nanoseconds; JSON/Node integers must
        # remain exact. Keep microsecond capture order, with IDs breaking ties.
        if order > 9007199254740991:
            order //= 1000
        if row.get('created_at'):
            order = int(datetime.fromisoformat(row['created_at'].replace('Z', '+00:00')).timestamp() * 1000000)
        text = original_conversation_text(source.content) if row.get('kind') == 'agent' else source.content
        order = max(order, 0)
        version = hashlib.sha256(json.dumps([text, stage, order], ensure_ascii=False).encode()).hexdigest()
        snapshot.append({
            'id': source.id, 'version': version,
            'project_id': project_id, 'kind': 'narrator_chat', 'author_role': 'storyteller',
            'text': text, 'status': 'active', 'allowed': True, 'derived_from': [],
            'life_stage': stage, 'source_order': order,
        })
    stage_order = {stage: index for index, stage in enumerate((*LIFE_STAGES, 'unplaced'))}
    return sorted(snapshot, key=lambda source: (stage_order[source['life_stage']], source['source_order'], source['id']))


def stage_source_ids(sources):
    return {stage: [source['id'] for source in sources if source.get('life_stage', 'unplaced') == stage]
            for stage in (*LIFE_STAGES, 'unplaced')
            if any(source.get('life_stage', 'unplaced') == stage for source in sources)}


def incremental_index_request(request, previous_request=None, overlap_source_ids=()):
    """Reuse valid index entries; send only evidence needed to update the rest."""
    previous_request = previous_request or {}
    versions = {s['id']:s['version'] for s in request['sources']}
    old_versions = {s['id']:s['version'] for s in previous_request.get('sources', [])}
    new_ids = [s['id'] for s in request['sources'] if s['id'] not in old_versions]
    changed_ids = [s['id'] for s in request['sources'] if s['id'] in old_versions and old_versions[s['id']] != s['version']]
    removed_ids = [id for id in old_versions if id not in versions]
    invalidated = {field:[] for field in ('periods','events')}
    for field in ('periods','events'):
        kept = []
        period_ids = {p['id'] for p in request['periods']}
        for item in previous_request.get(field, request[field]):
            valid = all(versions.get(ref['source_id']) == ref['version'] for ref in item['source_refs'])
            if field == 'events' and item.get('period_id') is not None:
                valid = valid and item['period_id'] in period_ids
            (kept if valid else invalidated[field]).append(copy.deepcopy(item))
        request[field] = kept
    affected_ids = {ref['source_id'] for items in invalidated.values() for item in items
                    for ref in item['source_refs'] if ref['source_id'] in versions}
    request['context'].update(new_source_ids=new_ids, changed_source_ids=changed_ids,
        removed_source_ids=removed_ids, overlap_source_ids=list(overlap_source_ids),
        affected_source_ids=[s['id'] for s in request['sources'] if s['id'] in affected_ids],
        stage_source_ids=stage_source_ids(request['sources']),
        # Retain canonical IDs for repair, without retaining deleted summaries.
        invalidated_index={field:[{k:item[k] for k in ('id','period_id') if k in item} for item in items]
                           for field, items in invalidated.items()},
        previous_index={field:copy.deepcopy(request[field]) for field in ('periods','events')})
    index_request = copy.deepcopy(request)
    index_ids = set(new_ids + changed_ids + list(overlap_source_ids)) | affected_ids
    index_request['sources'] = [s for s in request['sources'] if s['id'] in index_ids]
    index_request['context']['stage_source_ids'] = stage_source_ids(index_request['sources'])
    index_request['context']['original_source_manifest'] = [
        {'id':s['id'],'version':s['version'],'life_stage':s.get('life_stage','unplaced')} for s in request['sources']]
    return index_request


def incremental_model_request(request):
    """Build the bounded evidence packet used by an incremental composer call.

    The canonical request remains complete and is used for host-side planning,
    validation and persistence.  A ``new_context`` model call only needs the
    new/changed/affected evidence plus a small overlap; the prior manuscript
    and immutable source manifest carry the references for unchanged material.
    This avoids sending the full lifetime transcript to draft and review on
    every private checkpoint while retaining the full evidence boundary in the
    application.
    """
    context = request.get('context') or {}
    if context.get('lifetime_page', {}).get('coverage_scope') == 'canonical_message_batch':
        # The database already supplied a bounded delta and only its affected
        # prior writing. Further pruning would hide evidence needed for edits.
        return request
    if (request.get('trigger', {}).get('type') != 'new_context'
            or context.get('incremental_model_context') != 'compact'):
        return request
    source_ids = set()
    for field in ('new_source_ids', 'changed_source_ids', 'affected_source_ids', 'overlap_source_ids'):
        source_ids.update(str(value) for value in context.get(field, []))
    # A deletion has no current source to include.  Keep its canonical ID in
    # invalidated_index so the model can retire the old reference without
    # treating an absent source as permission to invent a replacement.
    if not source_ids:
        return request
    compact = copy.deepcopy(request)
    all_sources = list(request.get('sources', []))
    compact['sources'] = [source for source in all_sources if source.get('id') in source_ids]
    def references(item):
        return {
            ref.get('source_id')
            for ref in item.get('source_refs', [])
            if isinstance(ref, dict) and ref.get('source_id')
        }
    compact_events = [event for event in request.get('events', []) if references(event) & source_ids]
    compact_event_ids = {event.get('id') for event in compact_events}
    dirty_period_ids = {event.get('period_id') for event in compact_events if event.get('period_id')}
    compact_periods = [period for period in request.get('periods', [])
                       if period.get('id') in dirty_period_ids or references(period) & source_ids]
    changed_ids = set(source_ids)
    if context.get('canonical_event_index'):
        changed_ids = set(context.get('affected_source_ids', []))
    dirty_chapters = []
    carry_forward_chapters = []
    for prior in request.get('prior_state', {}).get('chapters', []):
        chapter = prior.get('chapter', {}) if isinstance(prior, dict) else {}
        chapter_ids = {
            ref.get('source_id')
            for ref in chapter.get('source_refs', [])
            if isinstance(ref, dict)
        }
        chapter_ids.update(
            ref.get('source_id')
            for block in chapter.get('blocks', [])
            if isinstance(block, dict)
            for ref in block.get('source_refs', [])
            if isinstance(ref, dict)
        )
        chapter_id = chapter.get('id')
        if not chapter_id:
            continue
        if chapter_ids & changed_ids:
            dirty_chapters.append(chapter_id)
        else:
            carry_forward_chapters.append(chapter_id)
    compact_context = dict(context)
    compact_context.update(
        incremental_model_context='compact',
        canonical_source_count=len(all_sources),
        selected_source_ids=[source.get('id') for source in compact['sources']],
        canonical_event_count=len(request.get('events', [])),
        canonical_period_count=len(request.get('periods', [])),
        dirty_event_ids=(context.get('dirty_event_ids', []) if context.get('canonical_event_index')
                         else [event.get('id') for event in compact_events if event.get('id')]),
        carry_forward_event_ids=[event.get('id') for event in request.get('events', [])
                                 if event.get('id') not in compact_event_ids],
        dirty_chapter_ids=dirty_chapters,
        carry_forward_chapter_ids=carry_forward_chapters,
        canonical_event_manifest=[
            {key: event.get(key) for key in ('id', 'period_id', 'status', 'narrative', 'source_refs')}
            for event in request.get('events', [])
        ],
        canonical_period_manifest=[
            {key: period.get(key) for key in ('id', 'order', 'source_refs')}
            for period in request.get('periods', [])
        ],
        canonical_source_manifest=[
            {key: source.get(key) for key in ('id', 'version', 'life_stage', 'source_order')}
            for source in all_sources
        ],
    )
    compact['events'] = compact_events
    compact['periods'] = compact_periods
    compact['context'] = compact_context
    return compact


def snapshot_key(sources, project_id, language):
    return hashlib.sha256(json.dumps({
        'sources': sources, 'project_id': project_id, 'language': language,
        'free_round_limit': free_recall_rounds(),
        'skill': [(name, (SKILL / name).read_text()) for name in [
            'SKILL.md', 'references/narrative-enrichment.md', 'references/editorial-and-length.md',
            'references/workflows.md',
            'references/editorial-review.prompt.md', 'schemas/request.schema.json',
            'schemas/draft.schema.json', 'scripts/lib.mjs',
        ]],
    }, sort_keys=True).encode()).hexdigest()


def reader_preview(bundle):
    """Project reader text from reviewed blocks without repeating its title."""
    preview = copy.deepcopy(bundle['preview'])
    manuscript = bundle.get('manuscript', {})
    chapter = (bundle.get('draft', {}).get('storyline')
               if preview.get('kind') == 'sample_storyline'
               else next(iter(manuscript.get('chapters', [])), None))
    if not chapter or not isinstance(chapter.get('blocks'), list):
        return preview
    blocks = chapter['blocks']
    first = 0
    title = preview.get('title', '').strip()
    while (first < len(blocks) and blocks[first].get('type') == 'heading'
           and blocks[first].get('text', '').strip() == title):
        first += 1
    preview['text'] = '\n\n'.join(block['text'] for block in blocks[first:] if block.get('text'))
    return preview


def cached_preview(rows, key):
    for row in rows:
        if row.get('kind') != 'memoir' or not any(
                path.startswith('memoir-preview:') for path in row.get('source_paths', [])):
            continue
        try:
            bundle = json.loads(row['content'])
        except (KeyError, ValueError, TypeError):
            continue
        if bundle.get('snapshot_key') == key:
            return reader_preview(bundle)
    return None


def previous_preview_request(rows, project_id, language):
    candidates = []
    for row in rows:
        if row.get('kind') != 'memoir' or f'memoir-preview:{project_id}' not in row.get('source_paths', []):
            continue
        try:
            request = json.loads(row['content'])['request']
            if request['project_id'] == project_id and request['target']['locale'] == language:
                candidates.append((row.get('created_at') or '', request))
        except (KeyError, ValueError, TypeError):
            continue
    return max(candidates, key=lambda item: item[0])[1] if candidates else None


def bind_index_sources(request):
    """Source versions come from the host registry, never model transcription."""
    request = copy.deepcopy(request)
    versions = {}
    for source in request['sources']:
        versions.setdefault(source['id'], set()).add(source['version'])
    for field in ('periods', 'events'):
        for entry in request[field]:
            for ref in entry['source_refs']:
                known = versions.get(ref['source_id'], set())
                if ref['version'] in known:
                    continue
                if len(known) != 1:
                    raise ValueError('The index contains an unknown or ambiguous source reference')
                ref['version'] = next(iter(known))
    return request


async def compose_candidate(request, runtime, storage, project_id, language, *, checkpoint, progress):
    from .composer_review import REVIEW_VERSION, review_requirements, review_errors
    # Old reviews lack complete prose/contribution witnesses. Keep their saved
    # draft, but obtain a current review before that checkpoint can authorize save.
    if not isinstance(checkpoint.get('review'), dict) or checkpoint['review'].get('contract_version') != REVIEW_VERSION:
        checkpoint.pop('review', None)
    if checkpoint.get('request'):
        request = checkpoint['request']
    if not request.get('context', {}).get('canonical_event_index'):
        raise ValueError('A canonical event index is required for composition')
    request = bind_index_sources(request)
    plan = await skill_operation('plan', request)
    if plan.get('status') == 'insufficient_context':
        return {'status': 'insufficient_context', 'preview': None}
    if not plan.get('ready'):
        raise RuntimeError('Memoir composer could not validate the source outline')
    checkpoint['request'] = request
    compact_request = incremental_model_request(request)
    compact_context = compact_request is not request
    packet = {'request': compact_request, 'plan': plan, **checkpoint.get('repair', {})}
    for attempt in range(3):
        await progress('drafting')
        if checkpoint.get('model_context_fallback') == 'full':
            packet['request'] = request
        draft = checkpoint.get('draft') or await composer_call(runtime, storage, project_id, language, 'draft', packet)
        if request.get('context', {}).get('canonical_event_index'):
            from .canonical_composer import restore_unchanged_sections
            draft = restore_unchanged_sections(request, draft)
            # These fields describe the immutable host request. Pinning them
            # after the model call prevents harmless stale-copy errors from
            # consuming a full composition lane attempt; prose and evidence
            # still go through the deterministic validator below.
            draft['input_snapshot_id'] = request['snapshot']['id']
            draft['input_fingerprint'] = plan['input_fingerprint']
            draft['expected_manuscript_revision'] = request['prior_state']['revision']
            draft['counter'] = plan['counter']
            normalize_new_chapter_revisions(request, draft)
            normalize_canonical_actions(draft)
            normalize_canonical_event_dispositions(draft)
        if request.get('context', {}).get('canonical_event_index'):
            from .canonical_composer import validate_canonical_candidate
            validation = await validate_canonical_candidate(request, draft)
        else:
            validation = await skill_operation('validate', request, draft)
        if not validation.get('ok'):
            logger.info('memoir_preview validation_failed codes=%s',
                        sorted({error.get('code', 'UNKNOWN') for error in validation.get('errors', [])}))
        review = None
        if validation.get('ok'):
            artifacts = await skill_operation('render', request, draft)
            manuscript = json.loads(artifacts['manuscript.json'])
            requirements = review_requirements(request, draft, manuscript)
            checkpoint['draft'] = draft
            await progress('reviewing')
            review_packet = {
                'request': packet['request'], 'candidate': draft, 'validation': validation,
                'requirements': requirements,
            }
            review = checkpoint.get('review') or await composer_call(
                runtime, storage, project_id, language, 'review', review_packet)
            errors = review_errors(review, requirements)
            if not errors:
                checkpoint['review'] = review
                break
            if compact_context and checkpoint.get('model_context_fallback') != 'full':
                # A compact packet is an optimization, never a quality gate.
                # One bounded full-context repair preserves the existing
                # three-attempt ceiling when a model cannot carry forward the
                # unchanged evidence correctly.
                checkpoint['model_context_fallback'] = 'full'
        elif compact_context and checkpoint.get('model_context_fallback') != 'full':
            checkpoint['model_context_fallback'] = 'full'
        checkpoint.pop('draft', None)
        checkpoint.pop('review', None)
        checkpoint['repair'] = {'candidate': draft, 'validation': validation, 'review': review,
            **({'review_errors': errors} if review is not None else {})}
        packet.pop('review_errors', None)
        packet.update(checkpoint['repair'])
        if compact_context and checkpoint.get('model_context_fallback') == 'full':
            packet['request'] = request
        await progress('drafting')
    else:
        raise RuntimeError('The sample needs another composition review; please retry')
    checkpoint.pop('repair', None)
    await progress('saving')
    chapter = (manuscript['chapters'][0] if draft['kind'] == 'sample_chapter' else draft['storyline'])
    preview = {'id': request['snapshot']['id'], 'kind': draft['kind'], 'title': chapter['title'],
        'text': '\n\n'.join(block['text'] for block in chapter['blocks'] if block['text']),
        'outline': [entry['title'] for entry in draft['outline']],
        'source_memory_ids': [source['id'] for source in request['sources']], 'locale': language}
    preview = reader_preview({'preview': preview, 'draft': draft, 'manuscript': manuscript})
    return {'status': 'ready', 'preview': preview, 'request': request, 'draft': draft,
            'validation': validation, 'review': review, 'markdown': artifacts['memoir.md'], 'manuscript': manuscript}
