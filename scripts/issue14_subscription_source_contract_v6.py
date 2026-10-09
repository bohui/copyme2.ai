"""Additive source integrity for the explicit five-case, fifty-input profile.

Original v1-v5 proofs, auditors and 5/10/15 evidence keep their exact identities.
This offline audit grants no execution, provider, publication or budget authority.
"""
import ast
import hashlib
import json
from pathlib import Path

from scripts import issue14_subscription_source_contract_v5 as v5


v4, v3, v2 = v5.v4, v5.v3, v5.v2
SourceContractError = v2.SourceContractError
PROOF_PATH = 'tests/fixtures/issue14_subscription_source_v6.json'
AUDIT_PATH = 'scripts/issue14_subscription_source_contract_v6.py'
CURRENT_REVISION = '493a71850882fb48a343a95f5ba537f2b4715d0f'
CURRENT_TREE = '5a9808f95e2a2ed21d8fde46d79fe41bea7c9a58'
V5_AUDITOR_SHA256 = '294db5d8aef39d9595a42fe52b2746734059e5124c73f13f66660448ea1826db'
V5_PROOF_SHA256 = '94070f30ef19b7de626eac54ba1052656d16bf588a0151ddcd90cf5f5d29f78a'
DATASET_PATH = 'tests/evaluation/memoir_five_case_inputs.json'
DATASET_SHA256 = 'e7f705bc4a96537b01cb5cde7d412972bdd929de49d339bc6b1a95bc9cb43927'
EXPECTED_PATH = 'tests/evaluation/memoir_five_case_expected.json'
EXPECTED_SHA256 = '9391515876dc2f346291e9ecca653e3710a1497d6a03961291cebb8f01d1c242'
EXTRA_PATHS = v5.EXTRA_PATHS | {DATASET_PATH, EXPECTED_PATH}
TOOLING_PATHS = v5.TOOLING_PATHS | {AUDIT_PATH}


def _fail(reason):
    raise SourceContractError(reason)


def _load(root):
    root = Path(root).absolute()
    prior_raw = v2._read(root, v5.PROOF_PATH, maximum=4 * 1024 * 1024)
    prior_auditor = v2._read(root, v5.AUDIT_PATH)
    if (hashlib.sha256(prior_raw).hexdigest() != V5_PROOF_SHA256
            or hashlib.sha256(prior_auditor).hexdigest() != V5_AUDITOR_SHA256):
        _fail('historical_v5_changed')
    _, _, historic, _, prior, tools, _ = v5._load(root)
    raw = v2._read(root, PROOF_PATH, maximum=4 * 1024 * 1024)
    try:
        current = json.loads(raw, object_pairs_hook=v2._unique)
    except (ValueError, UnicodeError, RecursionError):
        _fail('current_proof_invalid')
    if (type(current) is not dict
            or set(current) != {'schema_version', 'current_snapshot', 'objects'}
            or current['schema_version'] != 'memoir-subscription-source-proof/6'
            or type(current['objects']) is not dict):
        _fail('current_proof_invalid')
    old = json.loads(tools[v2.PROOF_PATH], object_pairs_hook=v2._unique)
    objects = dict(old['objects'])
    for body in (tools[v3.PROOF_PATH], tools[v4.PROOF_PATH], prior_raw):
        objects.update(json.loads(body, object_pairs_hook=v2._unique)['objects'])
    objects.update(current['objects'])
    # Preserve the unchanged bounded Git parser and its historical snapshots.
    proof = v2._Proof(json.dumps({**old, 'objects': objects}).encode())
    snapshot = current['current_snapshot']
    if (type(snapshot) is not dict or set(snapshot) != {'revision', 'tree', 'files'}
            or snapshot['revision'] != CURRENT_REVISION or snapshot['tree'] != CURRENT_TREE
            or type(snapshot['files']) is not dict
            or not proof.object(CURRENT_REVISION, 'commit').startswith(('tree ' + CURRENT_TREE + '\n').encode())):
        _fail('current_snapshot_invalid')
    for path, entry in snapshot['files'].items():
        v5._entry(proof, CURRENT_TREE, path, entry)
    # V5's original source bodies are archived rather than repinned to this tree.
    for entry in prior.values():
        if hashlib.sha256(proof.object(entry['blob'], 'blob')).hexdigest() != entry['sha256']:
            _fail('historical_v5_blob_invalid')
    tools = {**tools, v5.PROOF_PATH: prior_raw, v5.AUDIT_PATH: prior_auditor}
    return root, proof, historic, prior, snapshot['files'], tools


def historical_v5_files(root):
    """Verified original v5 source and tools for its unchanged historical tests."""
    _, proof, _, prior, _, tools = _load(root)
    return {**{path: proof.object(entry['blob'], 'blob') for path, entry in prior.items()},
            **tools}


def _tree_inventory(proof):
    paths = set(EXTRA_PATHS)
    for prefix in ('apps/api', 'scripts'):
        paths.update(proof.python_inventory(CURRENT_TREE, prefix))

    def all_files(node, path, depth=0):
        if depth > 20:
            _fail('source_tree_invalid')
        for name, (mode, child) in proof.tree(node).items():
            try:
                relative = path + '/' + name.decode('utf-8')
            except UnicodeError:
                _fail('source_path_invalid')
            if mode == b'40000':
                all_files(child, relative, depth + 1)
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


def audit_subscription_source_v6(root):
    root, proof, historic, prior, current, _ = _load(root)
    expected = _tree_inventory(proof)
    actual_paths = (v3._inventory(root) - TOOLING_PATHS) | EXTRA_PATHS
    if set(current) != expected or actual_paths != expected:
        _fail('source_inventory_invalid')
    actual = {}
    for path, entry in current.items():
        raw = v2._read(root, path)
        if (v2._git_hash('blob', raw) != entry['blob']
                or hashlib.sha256(raw).hexdigest() != entry['sha256']):
            _fail('current_source_mismatch')
        actual[path] = raw
    if hashlib.sha256(actual[DATASET_PATH]).hexdigest() != DATASET_SHA256:
        _fail('original_dataset_changed')
    if hashlib.sha256(actual[EXPECTED_PATH]).hexdigest() != EXPECTED_SHA256:
        _fail('original_expected_changed')
    legacy = actual['scripts/fifty_round_budget_contract.py']
    if v2._git_hash('blob', legacy) != v2.LEGACY_MODULE_BLOB:
        _fail('historical_contract_changed')
    pins = next((ast.literal_eval(node.value) for node in ast.parse(legacy).body
        if isinstance(node, ast.Assign) and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name) and node.targets[0].id == 'DERIVATION_FILE_SHA256'), {})
    if set(pins) != v2.HISTORICAL_PATHS or set(historic) != v2.HISTORICAL_PATHS:
        _fail('historical_pin_invalid')
    for path, entry in historic.items():
        if hashlib.sha256(proof.object(entry['blob'], 'blob')).hexdigest() != pins[path]:
            _fail('historical_pin_invalid')
    drift = sorted(path for path, entry in prior.items()
        if path not in actual or hashlib.sha256(actual[path]).hexdigest() != entry['sha256'])
    return {'schema_version': 'memoir-subscription-source-audit/6', 'source_gate_passed': True,
        'scope': 'source_integrity_not_execution_or_provider_authority',
        'historical_derivation_integrity_verified': True, 'historical_v2_integrity_verified': True,
        'historical_v3_integrity_verified': True, 'historical_v4_integrity_verified': True,
        'historical_v5_integrity_verified': True, 'historical_v5_snapshot_revision': v5.CURRENT_REVISION,
        'historical_v5_matches_current_source': not drift, 'historical_v5_drift_paths': drift,
        'newly_monitored_source_paths': sorted(set(current) - set(prior)),
        'original_five_case_inputs_integrity_verified': True,
        'original_five_case_expected_integrity_verified': True,
        'historical_publication_test_source_verified': True,
        'current_snapshot_revision': CURRENT_REVISION, 'current_snapshot_tree': CURRENT_TREE,
        'current_source_matches_reviewed_snapshot': True, 'current_source_file_count': len(current),
        'live_execution_authorized': False, 'provider_capability_verified': False,
        'hard_token_or_monetary_limit_enforced': False}
