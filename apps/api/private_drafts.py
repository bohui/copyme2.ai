"""Private incremental samples from host-authorized round checkpoints."""
import os

from .codex_runtime import normalize_conversation_language
from .memoir_preview import source_snapshot
from .private_draft_jobs import PrivateDraftJobs
from .recall import free_recall_rounds, private_draft_cadence


def enabled():
    return os.getenv('MEMORY_SPARK_PRIVATE_DRAFTS_ENABLED','true').strip().lower() in {'true','1','yes','on'}


def synchronize(storage, project, locale=None):
    path=os.getenv('MEMORY_SPARK_TASK_DB')
    reader=getattr(storage,'private_draft_rounds',None)
    if not path or not callable(reader) or not project:
        return {'status':'collecting','preview':None,'updating':False,'revision':0}
    from .memoir_preview import lifetime_draft_head
    governed=lifetime_draft_head(storage,project)
    if governed:
        return governed
    rounds=reader(project)
    reader=getattr(storage,'composition_memories',None) or getattr(storage,'all_memories',storage.memories)
    rows=reader()
    # Legacy account-wide sources have no project assignment; do not count
    # them or silently assign them to a new interview.
    sources=source_snapshot([r for r in rows if r.get('project_id')==project],project)
    locale=normalize_conversation_language(locale or storage.profile().get('preferred_language'))
    return PrivateDraftJobs(path).synchronize(storage.user_id,project,locale,rounds,sources,
        completed=storage.recall_rounds_completed(),free_limit=free_recall_rounds(),
        cadence=private_draft_cadence(),enabled=enabled(),
        authorization_event_id=storage.private_draft_event(project))
