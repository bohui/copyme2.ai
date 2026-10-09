"""Recovery source integrity with immutable v1/v2/v3 evidence.

This audit never grants execution, provider or budget authority. Its only new
runtime snapshot is independently reviewed before publication. Historical v3
bodies remain bound to the original proof, rather than relabelled as current.
"""
import ast
import hashlib
import json
from pathlib import Path

from scripts import issue14_subscription_source_contract as v3

v2 = v3.v2
SourceContractError = v2.SourceContractError
PROOF_PATH = 'tests/fixtures/issue14_subscription_source_v4.json'
AUDIT_PATH = 'scripts/issue14_subscription_source_contract_v4.py'
CURRENT_REVISION = 'e39195b5595de57791398727d8c0ebb9e88de3f7'
CURRENT_TREE = '4d07434de5dfc173caf0ab93b93ed8395db77e70'
V3_AUDITOR_SHA256 = 'e1cd56fc3f3c961a8ef435baf366666e93fe81cc4f207db36323978b9680712d'
V3_PROOF_SHA256 = '7196d568b3c66d49c890c02f0f399c46ef74b1de0219b41df7e2b6e9498d1d97'
EXTRA_PATHS = v3.EXTRA_PATHS
TOOLING_PATHS = v3.TOOLING_PATHS | {AUDIT_PATH}


def _fail(reason):
    raise SourceContractError(reason)


def _load(root):
    root = Path(root).absolute()
    prior_raw = v2._read(root, v3.PROOF_PATH, maximum=4*1024*1024)
    prior_auditor = v2._read(root, v3.AUDIT_PATH)
    if (hashlib.sha256(prior_raw).hexdigest() != V3_PROOF_SHA256
            or hashlib.sha256(prior_auditor).hexdigest() != V3_AUDITOR_SHA256):
        _fail('historical_v3_changed')
    _, _, historic, _, prior, old_raw, old_auditor = v3._load(root)
    raw = v2._read(root, PROOF_PATH, maximum=4*1024*1024)
    try:
        current = json.loads(raw, object_pairs_hook=v2._unique)
    except (ValueError, UnicodeError, RecursionError):
        _fail('recovery_proof_invalid')
    if (type(current) is not dict or set(current) != {'schema_version', 'current_snapshot', 'objects'}
            or current['schema_version'] != 'memoir-subscription-source-proof/4'
            or type(current['objects']) is not dict):
        _fail('recovery_proof_invalid')
    old = json.loads(old_raw, object_pairs_hook=v2._unique)
    previous = json.loads(prior_raw, object_pairs_hook=v2._unique)
    proof = v2._Proof(json.dumps({**old, 'objects': {
        **old['objects'], **previous['objects'], **current['objects']}}).encode())
    snapshot = current['current_snapshot']
    if (type(snapshot) is not dict or set(snapshot) != {'revision', 'tree', 'files'}
            or snapshot['revision'] != CURRENT_REVISION or snapshot['tree'] != CURRENT_TREE
            or type(snapshot['files']) is not dict
            or not proof.object(CURRENT_REVISION, 'commit').startswith(('tree '+CURRENT_TREE+'\n').encode())):
        _fail('recovery_snapshot_invalid')
    for path, entry in snapshot['files'].items():
        if (type(path) is not str or type(entry) is not dict or set(entry) != {'blob', 'sha256'}
                or not v2._hex(entry['blob'], 40) or not v2._hex(entry['sha256'], 64)):
            _fail('recovery_snapshot_invalid')
        mode, blob = proof.lookup(CURRENT_TREE, path)
        if mode not in {b'100644', b'100755'} or blob != entry['blob']:
            _fail('recovery_membership_invalid')
    for entry in prior.values():
        if hashlib.sha256(proof.object(entry['blob'], 'blob')).hexdigest() != entry['sha256']:
            _fail('historical_v3_blob_invalid')
    return root, proof, historic, prior, snapshot['files'], {
        v2.PROOF_PATH: old_raw, v2.AUDIT_PATH: old_auditor,
        v3.PROOF_PATH: prior_raw, v3.AUDIT_PATH: prior_auditor}


def _tree_inventory(proof):
    paths = set(EXTRA_PATHS)
    for prefix in ('apps/api', 'scripts'):
        paths.update(proof.python_inventory(CURRENT_TREE, prefix))
    def all_files(node, path, depth=0):
        if depth > 20:
            _fail('source_tree_invalid')
        for name, (mode, child) in proof.tree(node).items():
            try:
                relative = path+'/'+name.decode('utf-8')
            except UnicodeError:
                _fail('source_path_invalid')
            if mode == b'40000':
                all_files(child, relative, depth+1)
            elif mode in {b'100644', b'100755'}:
                paths.add(relative)
            else:
                _fail('source_path_invalid')
    for prefix in ('skills', 'supabase'):
        mode, node = proof.lookup(CURRENT_TREE, prefix)
        if mode != b'40000':
            _fail('source_path_invalid')
        all_files(node, prefix)
    return paths - TOOLING_PATHS


def historical_v3_files(root):
    """Original verified v3 files for its unchanged historical audit/mutations."""
    _, proof, _, prior, _, tools = _load(root)
    return {**{path: proof.object(entry['blob'], 'blob') for path, entry in prior.items()}, **tools}


def audit_subscription_source_v4(root):
    root, proof, historic, prior, current, _ = _load(root)
    expected = _tree_inventory(proof)
    if set(current) != expected or v3._inventory(root) - {AUDIT_PATH} != expected:
        _fail('source_inventory_invalid')
    actual = {}
    for path, entry in current.items():
        raw = v2._read(root, path)
        if v2._git_hash('blob', raw) != entry['blob'] or hashlib.sha256(raw).hexdigest() != entry['sha256']:
            _fail('current_source_mismatch')
        actual[path] = raw
    legacy = actual['scripts/fifty_round_budget_contract.py']
    if v2._git_hash('blob', legacy) != v2.LEGACY_MODULE_BLOB:
        _fail('historical_contract_changed')
    constants = {node.targets[0].id: ast.literal_eval(node.value)
        for node in ast.parse(legacy).body if isinstance(node, ast.Assign) and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name) and node.targets[0].id == 'DERIVATION_FILE_SHA256'}
    pins = constants.get('DERIVATION_FILE_SHA256', {})
    if set(pins) != v2.HISTORICAL_PATHS or set(historic) != v2.HISTORICAL_PATHS:
        _fail('historical_pin_invalid')
    for path, entry in historic.items():
        if hashlib.sha256(proof.object(entry['blob'], 'blob')).hexdigest() != pins[path]:
            _fail('historical_pin_invalid')
    drift = sorted(path for path, entry in prior.items()
        if path not in actual or hashlib.sha256(actual[path]).hexdigest() != entry['sha256'])
    return {'schema_version': 'memoir-subscription-source-audit/4', 'source_gate_passed': True,
        'scope': 'source_integrity_not_execution_or_provider_authority',
        'historical_derivation_integrity_verified': True, 'historical_v2_integrity_verified': True,
        'historical_v3_integrity_verified': True, 'historical_v3_snapshot_revision': v3.CURRENT_REVISION,
        'historical_v3_matches_current_source': not drift, 'historical_v3_drift_paths': drift,
        'current_snapshot_revision': CURRENT_REVISION, 'current_snapshot_tree': CURRENT_TREE,
        'current_source_matches_reviewed_snapshot': True, 'current_source_file_count': len(current),
        'live_execution_authorized': False, 'provider_capability_verified': False,
        'hard_token_or_monetary_limit_enforced': False}
