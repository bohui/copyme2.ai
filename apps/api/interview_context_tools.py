"""Read-only, owner-scoped retrieval for a persistent interview thread."""
import asyncio

from .lifetime_memory_context import serialize_packet


class InterviewContextTools:
    def __init__(self, publisher, fence, *, max_bytes=16384):
        self.publisher = publisher
        self.fence = fence.model_dump(mode='json')
        self.calls = 0
        self.bytes = 0
        self.max_bytes = max_bytes

    def specs(self):
        return [dict(name='memoir_read_context', description=
            'Read an authorized page of earlier narrator originals, continuity, or event details. Public context is not personal testimony.',
            inputSchema=dict(type='object', additionalProperties=False, required=['collection', 'after', 'query', 'event_id'],
                properties=dict(collection=dict(type='string', enum=['sources', 'continuity', 'events', 'event_sources', 'event_details']),
                    after=dict(type=['string', 'null'], maxLength=128),
                    query=dict(type=['string', 'null'], maxLength=80),
                    event_id=dict(type=['string', 'null'], maxLength=128))))]

    async def read(self, args):
        from psycopg import AsyncConnection
        from psycopg.types.json import Jsonb
        scope = self.fence['identity']
        collection = args['collection']
        if collection == 'continuity':
            function = 'read_lifetime_continuity'
            values = dict(p_conversation_id=scope['conversation_id'], p_policy_epoch=self.fence['policy_epoch'],
                p_after=args['after'] or '', p_limit=4)
        elif collection == 'sources' and args['query']:
            function = 'read_lifetime_source_page'
            values = dict(p_conversation_id=scope['conversation_id'], p_policy_epoch=self.fence['policy_epoch'],
                p_cursor=args['after'], p_limit=4, p_query=args['query'])
        else:
            function = 'read_lifetime_collection_page'
            values = dict(p_project_id=scope['project_id'], p_kind=collection, p_after=args['after'],
                p_limit=4, p_event_id=args['event_id'])
        async with asyncio.timeout(5):
            async with await AsyncConnection.connect(self.publisher._dsn, connect_timeout=2) as connection:
                await connection.execute('set local role authenticated')
                await connection.execute("select set_config('request.jwt.claim.sub',%s,true)", (scope['owner_id'],))
                await connection.execute('select public.lock_lifetime_publication(%s)', (Jsonb(self.fence),))
                placeholders = ','.join(name + '=>%s' for name in values)
                result = await connection.execute('select public.' + function + '(' + placeholders + ')', list(values.values()))
                return (await result.fetchone())[0]

    async def call(self, params):
        args = params.get('arguments')
        fields = self.specs()[0]['inputSchema']['properties']
        if (params.get('tool') != 'memoir_read_context' or not isinstance(args, dict) or set(args) != set(fields)
                or args['collection'] not in fields['collection']['enum']
                or any(value is not None and (not isinstance(value, str) or len(value) > fields[key]['maxLength'])
                       for key, value in args.items() if key != 'collection')
                or (args['collection'] not in {'event_sources', 'event_details'} and args['event_id'] is not None)
                or (args['collection'] != 'sources' and args['query'] is not None)):
            raise ValueError('Invalid interview context request')
        self.calls += 1
        if self.calls > 4:
            raise ValueError('Interview retrieval call limit exceeded')
        value = await self.read(args)
        text = serialize_packet(value)
        self.bytes += len(text.encode())
        if self.bytes > self.max_bytes:
            raise ValueError('Interview retrieval byte limit exceeded')
        return dict(contentItems=[dict(type='inputText', text=text)], success=True)
