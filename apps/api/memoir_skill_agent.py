"""Codex owns the tool loop; the host owns the skill catalog and capabilities."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
import re
import shutil
import tempfile
from urllib.parse import urlsplit

from .codex_agent import CodexConnection, provider_config
from .codex_worker_files import write_config
from .llm_tracing import trace_llm_call, update_llm_trace
from .model_request import instruction_manifest
from .prompt_artifact import ROOT, load_prompt_artifact, prompt_path
from .prompt_catalog import PROMPT_PATHS
from .prompt_composition import render_prompt_artifact


def skill_metadata(name):
    if not re.fullmatch(r'memoir-[a-z-]+', name):
        raise ValueError('Unavailable Memoir skill')
    path = ROOT / 'skills' / name / 'SKILL.md'
    text = load_prompt_artifact(path)
    header = text.split('---', 2)[1]
    description = re.search(r'^description:\s*(.+)$', header, re.M)
    declared = re.search(r'^name:\s*(.+)$', header, re.M)
    if not description or not declared or declared[1].strip() != name:
        raise ValueError('Invalid Memoir skill metadata')
    return {'name': name, 'description': description[1].strip()}, path


def skill_document(name, file, path):
    return {'skill': name, 'file': file, 'instructions': render_prompt_artifact(path)}


class SkillTools:
    def __init__(self, names, *, execute=None, work=None, process_source=None,
            source_skills=(), max_calls=32, max_bytes=65536):
        self.catalog = {}
        self.paths = {}
        for name in names:
            metadata, path = skill_metadata(name)
            self.catalog[name], self.paths[name] = metadata, path
        self.execute, self.work = execute, work
        self.process_source, self.source_skills = process_source, tuple(source_skills)
        self.sources_processed = 0
        self.reads = []
        self.calls = 0
        self.bytes = 0
        self.max_calls, self.max_bytes = max_calls, max_bytes
        self.executions = []

    def specs(self):
        properties = {'skill': {'type': 'string', 'enum': list(self.catalog)}}
        tools = [{'type':'function', 'name': 'memoir_read_skill',
            'description': 'Read a Memoir SKILL.md or a versioned reference before using it.',
            'inputSchema': {'type': 'object', 'additionalProperties': False,
                'properties': {**properties, 'file': {'type': 'string'}}, 'required': ['skill']}}]
        if self.execute is not None:
            tools.append({'type':'function', 'name': 'memoir_execute_skill',
                'description': 'Execute a previously read Memoir skill against current eligible background work.',
                'inputSchema': {'type': 'object', 'additionalProperties': False,
                    'properties': properties, 'required': ['skill']}})
        if self.work is not None:
            tools.append({'type':'function', 'name': 'memoir_pending_work',
                'description': 'Refresh eligible background work and its dependencies after a skill finishes.',
                'inputSchema': {'type': 'object', 'additionalProperties': False,
                    'properties': {}, 'required': []}})
        if self.process_source is not None:
            tools.append({'type':'function', 'name':'memoir_process_source',
                'description':'Choose the skills needed for the current original window and process it. An empty list records that no skill is needed. Read each chosen SKILL.md first.',
                'inputSchema':{'type':'object','additionalProperties':False,
                    'properties':{'skills':{'type':'array','items':{'type':'string','enum':list(self.source_skills)},
                        'maxItems':len(self.source_skills),'uniqueItems':True}},'required':['skills']}})
        return tools

    async def call(self, params):
        self.calls += 1
        if self.calls > self.max_calls:
            raise ValueError('Memoir agent tool budget exceeded')
        args = params.get('arguments')
        if not isinstance(args, dict) or len(json.dumps(args).encode()) > 2048:
            raise ValueError('Invalid Memoir tool arguments')
        tool = params.get('tool')
        name = args.get('skill')
        if tool == 'memoir_process_source' and self.process_source is not None and set(args) == {'skills'}:
            names = args['skills']
            if (not isinstance(names, list) or any(not isinstance(item, str) or item not in self.source_skills for item in names)
                    or len(names) != len(set(names))):
                value = {'error':'invalid_source_skills'}
            elif any(self.paths[item] not in self.reads for item in names):
                value = {'error':'read_skill_first'}
            else:
                value = await self.process_source(names)
                self.sources_processed += 1
                self.executions.append({'skills':list(names),'result':value})
        elif tool == 'memoir_pending_work' and self.work is not None and not args:
            value = await self.work()
        elif name not in self.catalog:
            value = {'error': 'skill_unavailable'}
        elif tool == 'memoir_read_skill' and not set(args) - {'skill', 'file'}:
            file = args.get('file', 'SKILL.md')
            if not isinstance(file, str):
                raise ValueError('Invalid skill reference')
            root = self.paths[name].parent
            candidate = root / file
            path = candidate.resolve()
            if (Path(file).is_absolute() or '..' in Path(file).parts or candidate.is_symlink()
                    or not path.is_relative_to(root.resolve())
                    or path not in {ROOT / p for p in PROMPT_PATHS.values()}):
                value = {'error': 'reference_unavailable'}
            else:
                value = skill_document(name, path.relative_to(root.resolve()).as_posix(), path)
                self.reads.append(path)
        elif tool == 'memoir_execute_skill' and self.execute is not None and set(args) == {'skill'}:
            if self.paths[name] not in self.reads:
                value = {'error': 'read_skill_first'}
            else:
                value = await self.execute(name)
                self.executions.append({'skill': name, 'result': value})
        else:
            value = {'error': 'tool_unavailable'}
        text = json.dumps(value, ensure_ascii=False, allow_nan=False)
        self.bytes += len(text.encode())
        if self.bytes > self.max_bytes:
            raise ValueError('Memoir agent context budget exceeded')
        return {'contentItems': [{'type': 'inputText', 'text': text}], 'success': 'error' not in value}


async def run_skill_agent(*, command, home_root, base_url, api_key, model,
        instructions, packet, skills, schema=None, execute=None, work=None,
        process_source=None, source_skills=(),
        publisher=None, fence=None, timeout=240, effort=None, connection_factory=None,
        issue14_admission=None, uid=None, apply_owner=False, max_tool_bytes=65536,
        trace_name='memoir-skill-agent'):
    from .issue14_execution_admission import issue14_connection_options
    endpoint = urlsplit(base_url)
    if (not api_key or endpoint.scheme not in {'http','https'} or not endpoint.hostname
            or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment):
        raise ValueError('Memoir agent provider is not configured')
    tools = SkillTools(skills, execute=execute, work=work, process_source=process_source,
        source_skills=source_skills, max_bytes=max_tool_bytes)
    instructions = load_prompt_artifact(prompt_path('memoir/shared/skill-agent')) + '\n\n' + instructions
    catalog = list(tools.catalog.values())
    prompt = json.dumps({'task': packet, 'available_skills': catalog}, ensure_ascii=False)
    @asynccontextmanager
    async def admission():
        from .lifetime_memory_lane_engine import check_lane_generation
        check_lane_generation()
        async with publisher.guard(fence):
            check_lane_generation()
            yield
    root = Path(home_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o711)
    home = Path(tempfile.mkdtemp(prefix='memoir-agent-', dir=root))
    try:
        import os
        with trace_llm_call(trace_name, model, gateway=True) as trace:
            write_config(home, root, os.getuid() if uid is None else uid,
                provider_config(base_url, model, governed=True), apply_owner=apply_owner)
            options = dict(provider_env={'MEMORY_SPARK_LLM_API_KEY': api_key}, timeout=timeout,
                request_admission=admission, tool_handler=tools.call,
                **issue14_connection_options(issue14_admission))
            async with asyncio.timeout(timeout), (connection_factory or CodexConnection)(command, home, **options) as connection:
                opened = await connection.request('thread/start', {
                    'cwd': str(home), 'ephemeral': True, 'modelProvider': 'llm_provider',
                    'model': model, 'approvalPolicy': 'never', 'sandbox': 'read-only',
                    'baseInstructions': instructions, 'dynamicTools': tools.specs()})
                thread_id = opened['thread']['id']
                reply = await connection.turn(thread_id, prompt, output_schema=schema, effort=effort,
                    responsesapi_client_metadata={'generation_name':trace_name,'trace_name':trace_name})
            if not tools.sources_processed and not any(path in tools.reads for path in tools.paths.values()):
                raise ValueError('Memoir agent did not read a skill')
            # The trace records what the agent actually read, including references.
            sources = '\n\n'.join(render_prompt_artifact(path) for path in dict.fromkeys(tools.reads))
            manifest = instruction_manifest(instructions + '\n' + sources, schema, variant='codex-skill-agent')
            update_llm_trace(trace, metadata={'prompt_manifest': manifest,
                'skills_read': [p.parent.name if p.name == 'SKILL.md' else p.relative_to(ROOT).as_posix()
                    for p in dict.fromkeys(tools.reads)], 'tool_calls': tools.calls})
            async with admission():
                pass
            return {'thread_id': thread_id, 'reply': reply, 'artifacts': [],
                'skill_receipt': {'prompt_manifest': manifest, 'tool_calls': tools.calls,
                    'skills_read': [name for name, path in tools.paths.items() if path in tools.reads],
                    'executions': tools.executions}}
    finally:
        shutil.rmtree(home)
