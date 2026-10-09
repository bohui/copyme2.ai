"""Current PR45/46 source with immutable earlier audit/publication evidence.

Source integrity never authorizes models, publication, spending or deployment.
The root journalist prompt is explicitly included in this expanded inventory.
"""
import ast
import hashlib
import json
from pathlib import Path
from scripts import issue14_subscription_source_contract_v4 as v4

v3, v2 = v4.v3, v4.v2
SourceContractError = v2.SourceContractError
PROOF_PATH = 'tests/fixtures/issue14_subscription_source_v5.json'
AUDIT_PATH = 'scripts/issue14_subscription_source_contract_v5.py'
PROMPT_PATH = 'Mira_Memoir_Journalist_System_Prompt_v1.0.md'
CURRENT_REVISION = '3d0e157f0835a72c3fb3aa9ec6766f8c2aaaa67b'
CURRENT_TREE = 'fda1225d8cde3c00d81d4168e7d7a1a68c4d4b4a'
V4_AUDITOR_SHA256 = '555038bbf3d26e34343739e4f5e61c714bef19020bae3e492d36986aa2dcf927'
V4_PROOF_SHA256 = '0d4da3b718eba1139c1beb1b84a42d46f30b79f1ec7f63c99c05fe3571189d80'
EXTRA_PATHS = v4.EXTRA_PATHS | {PROMPT_PATH}
TOOLING_PATHS = v4.TOOLING_PATHS | {AUDIT_PATH}
HISTORICAL_SUPPORT_PATHS = {PROMPT_PATH, 'tests/test_issue6_langfuse_publication.py'}


def _fail(reason):
    raise SourceContractError(reason)


def _entry(proof, tree, path, entry):
    if (type(path) is not str or type(entry) is not dict or set(entry) != {'blob', 'sha256'}
            or not v2._hex(entry['blob'], 40) or not v2._hex(entry['sha256'], 64)):
        _fail('current_snapshot_invalid')
    mode, blob = proof.lookup(tree, path)
    if mode not in {b'100644', b'100755'} or blob != entry['blob']:
        _fail('current_membership_invalid')


def _load(root):
    root = Path(root).absolute()
    prior_raw = v2._read(root, v4.PROOF_PATH, maximum=4*1024*1024)
    prior_auditor = v2._read(root, v4.AUDIT_PATH)
    if (hashlib.sha256(prior_raw).hexdigest() != V4_PROOF_SHA256
            or hashlib.sha256(prior_auditor).hexdigest() != V4_AUDITOR_SHA256):
        _fail('historical_v4_changed')
    _, _, historic, _, prior, tools = v4._load(root)
    raw = v2._read(root, PROOF_PATH, maximum=4*1024*1024)
    try:
        current = json.loads(raw, object_pairs_hook=v2._unique)
    except (ValueError, UnicodeError, RecursionError):
        _fail('current_proof_invalid')
    if (type(current) is not dict or set(current) != {
            'schema_version', 'current_snapshot', 'objects', 'historical_support'}
            or current['schema_version'] != 'memoir-subscription-source-proof/5'
            or type(current['objects']) is not dict
            or type(current['historical_support']) is not dict
            or set(current['historical_support']) != HISTORICAL_SUPPORT_PATHS):
        _fail('current_proof_invalid')
    old = json.loads(tools[v2.PROOF_PATH], object_pairs_hook=v2._unique)
    objects = dict(old['objects'])
    for body in (tools[v3.PROOF_PATH], prior_raw):
        objects.update(json.loads(body, object_pairs_hook=v2._unique)['objects'])
    objects.update(current['objects'])
    proof = v2._Proof(json.dumps({**old, 'objects': objects}).encode())
    snapshot = current['current_snapshot']
    if (type(snapshot) is not dict or set(snapshot) != {'revision', 'tree', 'files'}
            or snapshot['revision'] != CURRENT_REVISION or snapshot['tree'] != CURRENT_TREE
            or type(snapshot['files']) is not dict
            or not proof.object(CURRENT_REVISION, 'commit').startswith(('tree '+CURRENT_TREE+'\n').encode())):
        _fail('current_snapshot_invalid')
    for path, entry in snapshot['files'].items():
        _entry(proof, CURRENT_TREE, path, entry)
    for entry in prior.values():
        if hashlib.sha256(proof.object(entry['blob'], 'blob')).hexdigest() != entry['sha256']:
            _fail('historical_v4_blob_invalid')
    support = {}
    for path, entry in current['historical_support'].items():
        _entry(proof, v4.CURRENT_TREE, path, entry)
        content = proof.object(entry['blob'], 'blob')
        if hashlib.sha256(content).hexdigest() != entry['sha256']:
            _fail('historical_support_invalid')
        support[path] = content
    tools = {**tools, v4.PROOF_PATH: prior_raw, v4.AUDIT_PATH: prior_auditor}
    return root, proof, historic, prior, snapshot['files'], tools, support


def historical_v4_files(root):
    """Exact earlier runtime plus frozen tools and its original root prompt."""
    _, proof, _, prior, _, tools, support = _load(root)
    return {**{path: proof.object(entry['blob'], 'blob') for path, entry in prior.items()},
            **tools, PROMPT_PATH: support[PROMPT_PATH]}


def historical_test_files(root):
    """Unchanged original publisher tests bound to the earlier Git tree."""
    *_, support = _load(root)
    return {path: content for path, content in support.items() if path.startswith('tests/')}


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



def audit_subscription_source_v5(root):
    root, proof, historic, prior, current, _, _ = _load(root)
    expected = _tree_inventory(proof)
    actual_paths = (v3._inventory(root) - {v4.AUDIT_PATH, AUDIT_PATH}) | {PROMPT_PATH}
    if set(current) != expected or actual_paths != expected:
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
    return {'schema_version': 'memoir-subscription-source-audit/5', 'source_gate_passed': True,
        'scope': 'source_integrity_not_execution_or_provider_authority',
        'historical_derivation_integrity_verified': True, 'historical_v2_integrity_verified': True,
        'historical_v3_integrity_verified': True, 'historical_v4_integrity_verified': True,
        'historical_v4_snapshot_revision': v4.CURRENT_REVISION,
        'historical_v4_matches_current_source': not drift, 'historical_v4_drift_paths': drift,
        'newly_monitored_source_paths': sorted(set(current)-set(prior)),
        'historical_publication_test_source_verified': True,
        'current_snapshot_revision': CURRENT_REVISION, 'current_snapshot_tree': CURRENT_TREE,
        'current_source_matches_reviewed_snapshot': True, 'current_source_file_count': len(current),
        'live_execution_authorized': False, 'provider_capability_verified': False,
        'hard_token_or_monetary_limit_enforced': False}
