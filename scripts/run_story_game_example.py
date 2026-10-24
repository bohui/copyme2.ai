#!/usr/bin/env python3
"""Run the fictional age-eight benchmark through the two published prompts."""
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


def run(output, settings, *, resume=False):
    import httpx
    from apps.api.memoir_story_game import load_story_game_skill
    from apps.api.prompt_artifact import load_prompt_artifact, prompt_path
    from apps.api.model_request import instruction_manifest, manifest_metadata
    from apps.api.story_game_runtime import GameProposal, GameWebpage, game_ui, validate_scenes
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
                'memoir/skills/memoir-story-game/' + ('proposal' if phase == 'scenes' else 'webpage')))
            schema = schema_type.model_json_schema()
            manifest = instruction_manifest(instructions, schema, variant='story-game-' + phase)
            request = dict(model=model, instructions=instructions, input=json.dumps(payload, ensure_ascii=False),
                store=False, max_output_tokens=32768 if phase == 'scenes' else 16384,
                reasoning={'effort': settings.get('MEMORY_SPARK_MEMOIR_COMPOSER_REASONING_EFFORT') or 'low'},
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

        scenes = call('scenes', packet, settings['MEMORY_SPARK_MEMOIR_COMPOSER_MODEL'], GameProposal)
        scenes = validate_scenes(packet, scenes)
        payload = dict(locale=packet['locale'], ui=game_ui(packet['locale']), scenes=[
            dict(index=i, title=scene['title'], person=scene['person'], quote=scene['quote'])
            for i, scene in enumerate(scenes['scenes'])])
        webpage = call('webpage', payload, 'gpt-6-astra', GameWebpage)
        validate_webpage(webpage['html'], game_ui(packet['locale']))
        (output / 'webpage.html').write_text(webpage['html'])
        save('validated-result.json', dict(scenes=scenes['scenes'], html=webpage['html'],
            locale=packet['locale'], synthetic=True, input_sha256=hashlib.sha256(
                json.dumps(packet, sort_keys=True).encode()).hexdigest(), steps=receipts))
        print(json.dumps({'status': 'validated', 'scenes': len(scenes['scenes']), 'events': len(packet['timeline'])}), flush=True)
    trace_client = _get_client()
    if trace_client is not None:
        trace_client.flush()


def main():
    from dotenv import dotenv_values
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--resume', action='store_true', help='Reuse matching saved live responses')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--env-file', type=Path, default=ROOT / '.env')
    args = parser.parse_args()
    if not args.execute:
        print(json.dumps({'calls': 0, 'planned_steps': 2, 'step_2_model': 'gpt-6-astra'}))
        return
    settings = {k: v for k, v in dotenv_values(args.env_file, interpolate=False).items() if v}
    credentials = dotenv_values(Path.home() / 'llm_provider/.env', interpolate=False)
    for key in ('PUBLIC_KEY', 'SECRET_KEY'):
        if credentials.get('LANGFUSE_COPYME2AI_' + key):
            os.environ['LANGFUSE_' + key] = credentials['LANGFUSE_COPYME2AI_' + key]
    os.environ['LANGFUSE_BASE_URL'] = 'http://127.0.0.1:' + (credentials.get('LANGFUSE_PORT') or '3001')
    run(args.output, settings, resume=args.resume)


if __name__ == '__main__':
    main()
