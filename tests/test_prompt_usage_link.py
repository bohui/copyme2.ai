"""Native prompt identity reaches the bounded worker HTTP request."""
import pytest
from apps.api.model_request import manifest_metadata


@pytest.mark.parametrize('name', ['memoir/skills/memory-context/profile', 'memoir/skills/author-timeline/extract'])
def test_published_prompt_identity_is_safe_responses_metadata(name):
    manifest = dict(prompt_sha256='a'*64, schema_sha256='b'*64, manifest_sha256='c'*64,
        artifacts=[dict(name='local/source', version=None, status='local'),
                   dict(name=name, version=1, status='published')])
    metadata = manifest_metadata(manifest)
    assert metadata['langfuse_prompt_name'] == name
    assert metadata['langfuse_prompt_version'] == '1'
    assert all(isinstance(value, str) for value in metadata.values())
    assert 'artifacts' not in metadata


@pytest.mark.parametrize('artifacts', [[], [dict(name='local/source', version=None, status='local')],
    [dict(name='one',version=1,status='published'),dict(name='two',version=1,status='published')],
    [dict(name='invalid',version=True,status='published')],
    [dict(name='invalid',version='latest',status='published')],
    [dict(name='invalid',version=0,status='published')],
    [dict(name='',version=1,status='published')]])
def test_unpublished_or_ambiguous_manifests_do_not_guess_a_prompt(artifacts):
    metadata=manifest_metadata(dict(prompt_sha256='a'*64,schema_sha256='b'*64,manifest_sha256='c'*64,artifacts=artifacts))
    assert 'langfuse_prompt_name' not in metadata
    assert 'langfuse_prompt_version' not in metadata


@pytest.mark.parametrize('phase', ['profile', 'extract'])
def test_worker_forwards_assembled_prompt_once_without_tools(tmp_path, phase):
    import hashlib
    import json
    from test_lifetime_memory_lane_engine import BUDGET,Provider,Publisher,run,transport,page
    from test_background_profile import profile_page
    Provider.bodies=[];Provider.failure=None
    current=profile_page() if phase=='profile' else page()
    if phase=='profile':
        from apps.api.background_profile import profile_packet
        from apps.api.lifetime_memory_lane_engine import build_bounded_lane_input
        bounded=build_bounded_lane_input(current,phase=phase,packet=profile_packet(current),budget=BUDGET)
    else:
        bounded=transport(phase,current)
    run(tmp_path,bounded=bounded,publisher=Publisher())
    assert len(Provider.bodies)==1
    body=Provider.bodies[0]
    expected='memoir/skills/' + ('memory-context/profile' if phase=='profile' else 'author-timeline/extract')
    from apps.api.prompt_artifact import prompt_path
    path=prompt_path(expected)
    receipt=json.loads(path.with_name(path.name+'.langfuse.json').read_text())
    if receipt['sha256'] == hashlib.sha256(path.read_bytes()).hexdigest():
        assert body['metadata']['langfuse_prompt_name']==expected
        assert body['metadata']['langfuse_prompt_version']==str(receipt['version'])
    else:
        assert 'langfuse_prompt_name' not in body['metadata']
        assert 'langfuse_prompt_version' not in body['metadata']
    assert body['tools']==[] and body['tool_choice']=='none'
