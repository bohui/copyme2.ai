import asyncio

import psycopg

from apps.api.atlas_updates import AtlasUpdates
from test_agent_commit_postgres import OWNER, OTHER
from test_lifetime_memory_reads import sql
from test_lifetime_memory_publication import database, event_database, private_database, attachment_database


def test_atlas_stream_delivers_committed_changes_only_to_the_owning_project(sql):
    sql(f"""insert into public.user_memoir_project(user_id,project_id)
        values ('{OWNER}','atlas-project'),('{OWNER}','other-project'),('{OTHER}','atlas-project');""")
    sql(f"""insert into public.user_interview_photo(user_id,project_id,object_path,content_type,byte_size,width,height)
        values ('{OWNER}','atlas-project','atlas-fixture.png','image/png',8,2,2);""")

    async def scenario():
        feed = AtlasUpdates()
        connection = await psycopg.AsyncConnection.connect(sql.publication_dsn)
        streams = [feed.events(sql.publication_dsn, owner, project, expires_in=5, heartbeat=0.1)
                   for owner, project in [(OWNER, 'atlas-project'), (OWNER, 'other-project'), (OTHER, 'atlas-project')]]
        watched, *unrelated = streams
        statement = '''update public.user_memoir_project set event_sequence=event_sequence+1
                       where user_id=%s and project_id='atlas-project' '''
        try:
            for stream in streams:
                while not await anext(stream):
                    pass
            await connection.execute(statement, (OWNER,))
            assert not await anext(watched)
            await connection.rollback()
            assert not await anext(watched)
            await connection.execute(statement, (OWNER,))
            await connection.commit()
            assert await anext(watched)
            for stream in unrelated:
                assert not await anext(stream)
            photo_ready = "update public.user_interview_photo set status='ready' where object_path='atlas-fixture.png'"
            await connection.execute(photo_ready)
            assert not await anext(watched)
            await connection.commit()
            assert await anext(watched)
            for stream in unrelated:
                assert not await anext(stream)
            await connection.execute(photo_ready)
            await connection.commit()
            assert not await anext(watched), 'An idempotent upload retry must not resend the map'
        finally:
            for stream in streams:
                await stream.aclose()
            await feed.close()
            await connection.close()

    asyncio.run(scenario())
