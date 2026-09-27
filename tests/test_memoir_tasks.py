import pytest
from pydantic import ValidationError

from apps.api.memoir_tasks import MemoirTask, execute_task


def test_chapter_preserves_source_text_and_repeated_execution():
    task = MemoirTask(kind='BuildChapter', sources=[{'id': 'memory-1', 'content': 'I think it was 1970.'}])
    result = execute_task(task)
    assert result == execute_task(task)
    assert result['blocks'] == [{'type': 'narrative', 'text': 'I think it was 1970.',
                                 'source_memory_ids': ['memory-1']}]


def test_outline_cannot_introduce_unknown_sources():
    with pytest.raises(ValidationError, match='unknown memory'):
        MemoirTask(kind='BuildOutline', sources=[{'id': 'own', 'content': 'My story'}],
                   sections=[{'title': 'Childhood', 'memory_ids': ['other-user']}])


def test_outline_requires_an_explicit_structure():
    with pytest.raises(ValidationError, match='structure'):
        MemoirTask(kind='BuildOutline', sources=[{'id': 'own', 'content': 'My story'}])


def test_export_and_preview_keep_provenance():
    sources = [{'id': 'one', 'content': 'First memory'}, {'id': 'two', 'content': 'Second memory'}]
    exported = execute_task(MemoirTask(kind='BuildSourceExport', sources=sources))
    assert exported['sources'] == sources
    preview = execute_task(MemoirTask(kind='BuildFreePreview', sources=sources))
    assert preview['source_memory_ids'] == ['one', 'two']


def test_task_rejects_unknown_execution_kind():
    with pytest.raises(ValidationError):
        MemoirTask(kind='RunShell', sources=[{'id': 'one', 'content': 'x'}])
