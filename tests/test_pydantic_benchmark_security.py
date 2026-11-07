"""Exercise the private benchmark relay and AAS tool callback scopes."""
import asyncio
import json
import os
from types import SimpleNamespace

import pytest

from apps.api.interview_context_tools import InterviewContextTools
from scripts.deepseek_benchmark_transport import Bridge


@pytest.mark.skipif(not os.getenv('MEMOIR_TEST_AAS_CORE'), reason='Requires the AAS benchmark build')
def test_other_exchange_cannot_route_or_settle_a_tool(tmp_path):
    from scripts.pydantic_benchmark_transport import ComparisonRuntimes, aas_trace, comparison_body

    bridge = Bridge(model='gpt-6.1-sol', effort='low', delay=.001, normalize=comparison_body)
    runtimes = ComparisonRuntimes(bridge, os.environ['MEMOIR_TEST_AAS_CORE'], os.getenv('MEMOIR_TEST_NODE', 'node'))
    scope = 'synthetic owner-only answer'
    arguments = dict(collection='sources', after=None, query='kite', event_id=None)
    receipt = dict(success=True, contentItems=[dict(type='inputText', text=json.dumps({'private': scope}))])

    def provider(body, step):
        if step == 1:
            return dict(type='function_call', name='memoir_read_context', call_id='call_fixture',
                        arguments=json.dumps(arguments))
        tool = next(item for item in body['input'] if item['type'] == 'function_call_output')
        assert json.loads(tool['output']) == {'private': scope}
        return {'reply': scope}

    async def run():
        async with bridge.serve(), runtimes.serve(), bridge.exchange(provider) as owned, bridge.exchange() as foreign:
            client = runtimes.client
            wrong_bearer = await client.post(owned.origin + '/v1/responses', json={},
                headers={'Authorization': 'Bearer ' + foreign.token})
            assert wrong_bearer.status_code == 403 and not owned.requests
            wrong_trace = {'Authorization': 'Bearer ' + runtimes.secret, 'traceparent': aas_trace(foreign)}
            seen = []

            async def tool(params):
                assert params['tool'] == 'memoir_read_context' and params['arguments'] == arguments
                seen.append(params['callId'])
                denied = await client.post(runtimes.aas_url + '/tool-results', headers=wrong_trace,
                    json=dict(id=params['callId'], result=receipt))
                assert denied.status_code == 404
                return receipt

            factory = runtimes.factory('advanced_aas', owned)
            async with factory([], tmp_path, tool_handler=tool) as connection:
                tools = InterviewContextTools(None, SimpleNamespace(model_dump=lambda **_: {}))
                opened = await connection.request('thread/start', dict(model=bridge.model,
                    baseInstructions='Use the authorized recall tool.',
                    dynamicTools=tools.specs()))
                schema = dict(type='object', additionalProperties=False,
                              properties={'reply': {'type': 'string'}}, required=['reply'])
                result = await connection.turn(opened['thread']['id'], 'Recall the answer.',
                                               effort=bridge.effort, output_schema=schema)
            assert json.loads(result) == {'reply': scope} and len(owned.requests) == 2
            assert len(seen) == 1 and not foreign.requests

    asyncio.run(run())
