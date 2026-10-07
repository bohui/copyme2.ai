"""Generated mobile OpenAPI subset stays reviewed alongside runtime DTOs."""
from copy import deepcopy
import json

import pytest

from scripts import check_mobile_openapi as contract


@pytest.fixture
def sample():
    return {
        'openapi': '3.1.0',
        'paths': {
            '/v1/user/example': {'get': {'summary': 'Example', 'operationId': 'unstable_name',
                'responses': {'200': {'description': 'Success', 'content': {'application/json': {
                    'schema': {'$ref': '#/components/schemas/Example'}}}}}}},
            '/v1/legacy-only': {'post': {'responses': {'200': {'description': 'Demo'}}}},
        },
        'components': {'schemas': {
            'Example': {'title': 'Example', 'type': 'object', 'required': ['id'], 'properties': {
                'id': {'type': 'string'}, 'detail': {'$ref': '#/components/schemas/Detail'}}},
            'Detail': {'type': 'object', 'properties': {'kind': {'type': 'string', 'enum': ['b', 'a']}}},
            'Unrelated': {'type': 'object'},
        }},
    }


def subset(sample):
    return contract.build_snapshot(sample, operations={'/v1/user/example': ('get',)})


def test_normalized_snapshot_keeps_only_selected_canonical_operations_and_transitive_refs(sample):
    snapshot = subset(sample)
    assert set(snapshot['paths']) == {'/api/v1/memoir/user/example'}
    assert set(snapshot['components']['schemas']) == {'Example', 'Detail'}
    assert 'operationId' not in json.dumps(snapshot)
    assert 'summary' not in json.dumps(snapshot)
    assert snapshot['components']['schemas']['Detail']['properties']['kind']['enum'] == ['a', 'b']


def test_normalization_preserves_real_properties_named_like_documentation(sample):
    sample['components']['schemas']['Example']['properties']['title'] = {'type': 'string'}
    sample['components']['schemas']['Example']['properties']['description'] = {'type': 'string'}
    sample['components']['schemas']['Example']['examples'] = [{'$ref': 'documentation-only'}]
    snapshot = subset(sample)
    fields = snapshot['components']['schemas']['Example']['properties']
    assert fields['title'] == {'type': 'string'}
    assert fields['description'] == {'type': 'string'}


def test_selected_route_removal_is_detected(sample):
    del sample['paths']['/v1/user/example']['get']
    with pytest.raises(ValueError, match='Missing mobile operation'):
        subset(sample)


def test_required_field_addition_and_property_removal_create_reviewable_drift(sample):
    expected = subset(sample)
    changed = deepcopy(expected)
    changed['components']['schemas']['Example']['required'].append('detail')
    assert 'detail' in contract.snapshot_diff(expected, changed)
    changed = deepcopy(expected)
    del changed['components']['schemas']['Example']['properties']['id']
    assert 'id' in contract.snapshot_diff(expected, changed)
    assert contract.snapshot_diff(expected, expected) == ''


def test_enum_narrowing_and_unresolved_reference_are_detected(sample):
    before = subset(sample)
    sample['components']['schemas']['Detail']['properties']['kind']['enum'] = ['a']
    assert '"b"' in contract.snapshot_diff(before, subset(sample))
    del sample['components']['schemas']['Detail']
    with pytest.raises(ValueError, match='Unresolved OpenAPI reference'):
        subset(sample)


def test_documentation_and_required_order_do_not_cause_drift(sample):
    sample['components']['schemas']['Example']['required'] = ['id', 'detail']
    before = subset(sample)
    sample['components']['schemas']['Example']['required'] = ['detail', 'id']
    sample['paths']['/v1/user/example']['get']['summary'] = 'New documentation'
    assert contract.snapshot_diff(before, subset(sample)) == ''


def test_check_mode_never_rewrites_snapshot_and_write_is_explicit(sample, tmp_path, monkeypatch, capsys):
    snapshot = tmp_path / 'snapshot.json'
    monkeypatch.setattr(contract, 'load_openapi', lambda: sample)
    monkeypatch.setattr(contract, 'MOBILE_OPERATIONS', {'/v1/user/example': ('get',)})
    assert contract.main(['--snapshot', str(snapshot)]) == 1
    assert not snapshot.exists()
    assert contract.main(['--snapshot', str(snapshot), '--write']) == 0
    original = snapshot.read_bytes()
    assert contract.main(['--snapshot', str(snapshot)]) == 0
    sample['components']['schemas']['Example']['required'].append('detail')
    assert contract.main(['--snapshot', str(snapshot)]) == 1
    assert snapshot.read_bytes() == original
    assert 'drift' in capsys.readouterr().out.lower()


def test_checked_in_snapshot_matches_schema_without_network_or_runtime_work(monkeypatch):
    import httpx
    from apps.api.codex_runtime import CodexRuntime
    def forbidden(*args, **kwargs):
        raise AssertionError('Generating schemas must not run providers or HTTP requests')
    monkeypatch.setattr(httpx.Client, 'request', forbidden)
    monkeypatch.setattr(httpx.AsyncClient, 'request', forbidden)
    monkeypatch.setattr(CodexRuntime, 'turn', forbidden)
    expected = json.loads(contract.DEFAULT_SNAPSHOT.read_text())
    assert contract.snapshot_diff(expected, contract.build_snapshot()) == ''
