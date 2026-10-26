#!/usr/bin/env python3
"""Inspect the retained Higgsfield backup example; the app defaults to NovelToGame."""
import argparse
from contextlib import nullcontext
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def run(output, settings, *, resume=False, selection=None):
    import httpx
    from apps.api.memoir_story_game import load_story_game_skill
    from apps.api.prompt_artifact import load_prompt_artifact, prompt_path
    from apps.api.model_request import instruction_manifest, manifest_metadata
    from apps.api.story_game_runtime import game_ui
    from apps.api.story_game_selection import ScenePool, GameBrief, validate_pool, validate_brief, public_scenes
    from apps.api.story_game_webpage import validate_webpage
    from apps.api.llm_tracing import trace_llm_call, update_llm_trace, _get_client

    fixture = json.loads((ROOT / 'skills/memoir-story-game/tests/fixtures/age-eight.json').read_text())
    assert fixture['fixture_scope'] == 'fictional full age-eight benchmark'
    packet = fixture['input']
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    receipts = {}

    def save(name, value):
        (output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')

    save('input.json', fixture)
    with httpx.Client(trust_env=False, timeout=180) as client:
        def call(phase, payload, model, schema_type):
            instructions = load_story_game_skill() + '\n\n' + load_prompt_artifact(prompt_path(
                'memoir/skills/memoir-story-game/' + ('proposal' if phase == 'scenes' else 'brief')))
            schema = schema_type.model_json_schema()
            manifest = instruction_manifest(instructions, schema, variant='story-game-' + phase)
            request = dict(model=model, instructions=instructions, input=json.dumps(payload, ensure_ascii=False),
                store=False, max_output_tokens=32768 if phase == 'scenes' else 16384,
                reasoning={'effort': 'max'},
                metadata={'generation_name': 'age-eight-story-game-' + phase, **manifest_metadata(manifest)},
                text={'format': {'type': 'json_schema', 'name': 'memoir_game_' + phase,
                                 'strict': True, 'schema': schema}})
            cached = resume and (output / (phase + '-response.json')).is_file()
            if cached:
                previous = json.loads((output / (phase + '-request.json')).read_text())
                assert all(previous[key] == request[key] for key in ('model', 'instructions', 'input', 'text', 'max_output_tokens'))
            else:
                save(phase + '-request.json', request)
            started = time.monotonic()
            print(json.dumps({'phase': phase, 'status': 'started', 'requested_model': model}), flush=True)
            context = nullcontext(None) if cached else trace_llm_call('story.game.example.' + phase, model,
                input_summary=payload, metadata={'prompt_manifest': manifest, 'synthetic': True})
            with context as trace:
                if cached:
                    result = json.loads((output / (phase + '-response.json')).read_text())
                else:
                    response = client.post(settings['MEMORY_SPARK_LLM_BASE_URL'].rstrip('/') + '/responses',
                        headers={'Authorization': 'Bearer ' + settings['MEMORY_SPARK_LLM_API_KEY']}, json=request)
                    response.raise_for_status()
                    assert settings['MEMORY_SPARK_LLM_API_KEY'].encode() not in response.content
                    result = response.json()
                    save(phase + '-response.json', result)
                if result.get('status') != 'completed' or not result.get('id') or not result.get('model'):
                    raise ValueError('incomplete_game_response')
                text = ''.join(part.get('text', '') for item in result.get('output', []) if item.get('type') == 'message'
                    for part in item.get('content', []) if part.get('type') == 'output_text')
                value = schema_type.model_validate_json(text).model_dump(mode='json')
                receipts[phase] = dict(status='completed', response_id=result['id'], model=result['model'],
                    requested_model=model, duration_seconds=None if cached else round(time.monotonic() - started, 3),
                    reused_live_response=bool(cached),
                    usage=result.get('usage'), prompt_manifest=manifest)
                update_llm_trace(trace, output=value, metadata=receipts[phase])
                save(phase + '.json', value)
                save('receipts.json', receipts)
                print(json.dumps({'phase': phase, **{k: receipts[phase][k] for k in
                    ('status', 'model', 'duration_seconds')}}), flush=True)
                return value

        pool = call('scenes', packet, 'gpt-6.1-sol', ScenePool)
        pool = validate_pool(packet, pool)
        stages = {e['id']: e.get('life_stage') or 'unplaced' for e in packet['timeline']}
        for i, scene in enumerate(pool['scenes']):
            scene.update(id=f'scene-{i+1}', life_stage=stages[scene['event_ids'][0]])
        pool_digest = hashlib.sha256(json.dumps(pool, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        save('pool.json', dict(pool_digest=pool_digest, **pool))
        if selection is None:
            print(json.dumps(dict(status='selection_required', pool_digest=pool_digest, scenes=len(pool['scenes']),
                instructions='Choose scene_ids and pass a JSON selection with this pool_digest using --selection and --resume. No game build has started.')), flush=True)
        else:
            chosen = json.loads(selection.read_text())
            if chosen.get('pool_digest') != pool_digest or not isinstance(chosen.get('scene_ids'), list):
                raise ValueError('Example selection needs the exact saved pool digest and scene_ids')
            ids = chosen['scene_ids']
            scenes = [s for s in pool['scenes'] if s['id'] in ids]
            if not scenes or len(scenes) != len(ids) or len(set(ids)) != len(ids):
                raise ValueError('Example selection must contain unique offered scene IDs')
            payload = dict(locale=packet['locale'], ui=game_ui(packet['locale']), scenes=public_scenes({'scenes': scenes}))
            brief = call('brief', payload, 'gpt-6.1-sol', GameBrief)
            brief = validate_brief(brief, len(scenes))
            instructions = '\n\n'.join(load_prompt_artifact(prompt_path('memoir/skills/memoir-story-game/' + name))
                for name in ('higgsfield','webpage'))
            save('higgsfield-handoff.json', dict(model='gpt-6-astra', skill='higgsfield-websites', type='game',
                instructions=instructions, input={**payload, 'brief': brief}, synthetic=True,
                selected_scene_ids=ids, pool_digest=pool_digest, steps=receipts))
            print(json.dumps(dict(status='handoff_ready', scenes=len(scenes),
                instructions='This labelled synthetic handoff is for inspection. Canonical games run the separate skill through the confirmed Memoir UI action.')), flush=True)
    trace_client = _get_client()
    if trace_client is not None:
        trace_client.flush()


def main():
    from dotenv import dotenv_values
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--higgsfield-backup', action='store_true', help='Explicitly run this retained backup planning example')
    parser.add_argument('--resume', action='store_true', help='Reuse matching saved live responses')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--selection', type=Path, help='Human-authored JSON: pool_digest and scene_ids; requires --resume')
    parser.add_argument('--env-file', type=Path, default=ROOT / '.env')
    args = parser.parse_args()
    if not args.execute:
        print(json.dumps({'calls': 0, 'planning_steps': 2, 'human_selection_required': True,
            'default_builder':'novel-to-game','default_builder_model':'gpt-6.1-sol','effort':'max',
            'this_script':'higgsfield-backup-example','backup_builder_model':'gpt-6-astra'}))
        return
    if not args.higgsfield_backup:
        parser.error('This is the explicit Higgsfield backup example. Use the Memoir UI for the default NovelToGame flow, or add --higgsfield-backup.')
    settings = {k: v for k, v in dotenv_values(args.env_file, interpolate=False).items() if v}
    credentials = dotenv_values(Path.home() / 'llm_provider/.env', interpolate=False)
    for key in ('PUBLIC_KEY', 'SECRET_KEY'):
        if credentials.get('LANGFUSE_COPYME2AI_' + key):
            os.environ['LANGFUSE_' + key] = credentials['LANGFUSE_COPYME2AI_' + key]
    os.environ['LANGFUSE_BASE_URL'] = 'http://127.0.0.1:' + (credentials.get('LANGFUSE_PORT') or '3001')
    if args.selection and not args.resume:
        parser.error('--selection requires --resume to preserve the offered pool')
    run(args.output, settings, resume=args.resume, selection=args.selection)


if __name__ == '__main__':
    main()
