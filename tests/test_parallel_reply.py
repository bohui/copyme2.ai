import asyncio
import json

import pytest

from apps.api.parallel_reply import RevisableReplyStream, reviewed_reply


@pytest.mark.parametrize('ensure_ascii', [True, False])
@pytest.mark.parametrize('question', [None, '您初到悉尼时，什么最让您难忘？'])
def test_partial_json_streams_only_visible_reply_fields(ensure_ascii, question):
    acknowledgement = '您说过“我们一起经营商店”。👩‍👩‍👧‍👦'
    raw = json.dumps(dict(acknowledgement=acknowledgement, question=question,
        work={'acknowledgement':'PRIVATE INTERNAL FIELD', 'question':'INTERNAL QUESTION'}), ensure_ascii=ensure_ascii)
    stream = RevisableReplyStream()
    visible = ''
    for char in raw:
        delta = stream.feed(char)
        visible += delta
        assert visible == stream.text
        assert 'PRIVATE' not in visible and 'INTERNAL' not in visible
        assert not any(0xD800 <= ord(value) <= 0xDFFF for value in visible)
    assert visible == acknowledgement + ('\n\n' + question if question else '')


def test_reply_text_arrives_before_its_json_string_closes_and_ignores_embedded_field_names():
    stream = RevisableReplyStream()
    assert stream.feed('{"acknowledgement":"Your father') == 'Your father'
    assert stream.feed(' said \\"question\\": hello.","question":"What happened') == ' said "question": hello.\n\nWhat happened'
    assert stream.feed(' next?","work":{"secret":"do not show') == ' next?'
    assert stream.feed('"}}') == ''


@pytest.mark.parametrize('restricted', [False, True])
def test_review_and_generation_overlap_but_review_owns_commit_and_cancellation(restricted):
    async def run():
        entered, release, stopped = asyncio.Event(), asyncio.Event(), asyncio.Event()
        source = {'id':'current-source', 'version':1}
        async def review():
            await release.wait()
            return {**{'source_id':source['id'], 'source_version':1}, 'restricted':restricted}
        async def generate():
            entered.set()
            try:
                if restricted: await asyncio.Event().wait()
                return {'reply':'A complete draft.'}
            finally: stopped.set()
        resets = []
        async def retract(): resets.append('current-turn-only')
        review_task = asyncio.create_task(review())
        result = asyncio.create_task(reviewed_reply(review_task,generate,source=source,retract=retract))
        await asyncio.wait_for(entered.wait(),1)
        assert not result.done(), 'even a complete draft must wait for policy before saving'
        release.set()
        value = await asyncio.wait_for(result,1)
        assert stopped.is_set()
        assert value == (None if restricted else {'reply':'A complete draft.'})
        assert resets == (['current-turn-only'] if restricted else [])
    asyncio.run(run())


@pytest.mark.parametrize('failure', ['timeout', 'foreign-source', 'cancellation'])
def test_failed_or_cancelled_review_never_leaves_generation_running(failure):
    async def run():
        entered, release, stopped = asyncio.Event(), asyncio.Event(), asyncio.Event()
        async def review():
            await release.wait()
            if failure == 'timeout': raise TimeoutError('controlled timeout')
            return {'source_id':'foreign', 'source_version':1, 'restricted':False}
        async def generate():
            entered.set()
            try: await asyncio.Event().wait()
            finally: stopped.set()
        async def retract(): pass
        review_task = asyncio.create_task(review())
        task = asyncio.create_task(reviewed_reply(review_task,generate,source={'id':'current','version':1},retract=retract))
        await asyncio.wait_for(entered.wait(),1)
        if failure == 'cancellation': task.cancel()
        else: release.set()
        with pytest.raises(asyncio.CancelledError if failure=='cancellation' else (TimeoutError if failure=='timeout' else ValueError)):
            await task
        assert stopped.is_set()
        assert review_task.done()
    asyncio.run(run())


def test_discarding_a_completed_draft_also_cancels_its_worker_stream():
    async def run():
        entered, release, stopped = asyncio.Event(), asyncio.Event(), asyncio.Event()
        async def artifact():
            entered.set()
            try: await asyncio.Event().wait()
            finally: stopped.set()
        async def generate(): return {'reply':'Draft.', '_artifact_task':asyncio.create_task(artifact())}
        async def review():
            await release.wait()
            return {'source_id':'current','source_version':1,'restricted':True}
        async def retract(): pass
        task = asyncio.create_task(reviewed_reply(asyncio.create_task(review()),generate,
            source={'id':'current','version':1},retract=retract))
        await asyncio.wait_for(entered.wait(),1)
        release.set()
        assert await task is None
        assert stopped.is_set()
    asyncio.run(run())
