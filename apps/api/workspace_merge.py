"""Finish an authenticated guest merge across file and task stores."""
from urllib.parse import quote
from uuid import UUID


def transfer_guest_project(store, project_id, guest_id, owner_id):
    """Rebind only the self interview identified by a verified attachment."""
    with store.lock:
        project = store.projects.get(project_id)
        if not project or project.get('supabase_owner_id') == owner_id:
            return
        if (project.get('mode') != 'self'
                or project.get('supabase_owner_id') != guest_id
                or project.get('owner_id') != guest_id
                or project.get('storyteller_id') != guest_id
                or set(project.get('members', {})) != {guest_id}):
            raise ValueError('Attached interview conflicts with an existing local project')
        store.ensure_account(owner_id)
        project['members'] = {owner_id: project['members'][guest_id]}
        project['owner_id'] = owner_id
        project['storyteller_id'] = owner_id
        project['supabase_owner_id'] = owner_id
        project['revision'] += 1
        project['policy_epoch'] += 1
        store.audit('project.guest_transferred', owner_id, project_id, guest_id=guest_id)
        store.emit(project, 'project.guest_transferred')


def remap_memory_ids(value, mapping):
    if isinstance(value, dict):
        return {key: remap_memory_ids(item, mapping) for key, item in value.items()}
    if isinstance(value, list):
        return [remap_memory_ids(item, mapping) for item in value]
    return mapping.get(value, value) if isinstance(value, str) else value


def merge_collection_periods(existing, incoming):
    result = dict(existing)
    for stage, guest in incoming.items():
        current = result.get(stage, {})
        memories = list(dict.fromkeys(current.get('memory_ids', []) + guest.get('memory_ids', [])))
        result[stage] = {**guest, **current, 'memory_ids': memories}
        if memories:
            result[stage]['status'] = 'recorded'
        notes = list(dict.fromkeys(note for note in (current.get('note'), guest.get('note')) if note))
        if notes:
            result[stage]['note'] = '\n'.join(notes)
    return result


def import_guest_files(service, guest_id, files):
    guest_id = str(UUID(guest_id))
    owner_id = str(UUID(service.user_id))
    for item in files:
        source = item['name']
        prefix, category, relative = source.split('/', 2)
        if prefix != guest_id or category not in {'agent', 'attachment'}:
            raise ValueError('Invalid imported file scope')
        if category == 'agent':
            service.agent_path(relative)
            root, tail = relative.split('/', 1)
            destination = f'{owner_id}/agent/{root}/imports/{guest_id}/{tail}'
        else:
            if any(part in {'', '.', '..'} for part in relative.split('/')):
                raise ValueError('Invalid attachment path')
            destination = f'{owner_id}/attachment/imports/{guest_id}/{relative}'
        # Deterministic destinations and upserts make uncertain writes safe to
        # retry. They cannot overwrite another account's existing files.
        response = service.request('GET', '/storage/v1/object/authenticated/memory-spark/' + quote(source, safe='/'))
        service._put(destination, response.content, response.headers.get('content-type', 'application/octet-stream'), overwrite=True)
