"""Version 3 source integrity, without changing historical budget evidence.

This proves source bytes and old derivations, never provider capability, prices,
semantic acceptance or authority to execute. Runtime/native inputs are included;
the two explicitly reviewed audit tools are outside their own snapshots.
"""
import ast
import hashlib
import json
import os
from pathlib import Path

from scripts import issue14_source_contract as v2

SourceContractError = v2.SourceContractError
PROOF_PATH = 'tests/fixtures/issue14_subscription_source_v3.json'
AUDIT_PATH = 'scripts/issue14_subscription_source_contract.py'
CURRENT_REVISION = 'bbf35488e37d7a83f9542a8b09ba2b7a81e2ca05'
CURRENT_TREE = 'f2a5418d5fd8916cc98231030f7558b275cc774c'
V2_PROOF_SHA256 = 'b3a3ffb7aeff9b14288fda3f6290e24fc12c34594e913b927bd5c4bb3e7b0ec5'
V2_AUDITOR_SHA256 = '60880f1eb7cad584c85a66c1b9d97d7b5c486fe8dba1998fa1978ea0d0aba78e'
EXTRA_PATHS = v2.EXTRA_SOURCE_PATHS | {
    'tests/test_agent_commit_postgres.py', 'tests/test_shared_memory_events_postgres.py',
    'tests/test_guest_conversation_transfer.py', 'tests/test_private_rounds_postgres.py',
    'tests/memoir_postgres_workflow.py', 'tests/evaluation/issue6_semantic_datasets.json'}
TOOLING_PATHS = {v2.AUDIT_PATH, AUDIT_PATH}


def _fail(reason):
    raise SourceContractError(reason)


def _load(root):
    root = Path(root).absolute()
    old_raw = v2._read(root, v2.PROOF_PATH, maximum=4*1024*1024)
    auditor = v2._read(root, v2.AUDIT_PATH)
    if (hashlib.sha256(old_raw).hexdigest() != V2_PROOF_SHA256
            or hashlib.sha256(auditor).hexdigest() != V2_AUDITOR_SHA256):
        _fail('historical_v2_changed')
    old = json.loads(old_raw, object_pairs_hook=v2._unique)
    raw = v2._read(root, PROOF_PATH, maximum=4*1024*1024)
    try:
        current = json.loads(raw, object_pairs_hook=v2._unique)
    except (ValueError, UnicodeError, RecursionError):
        _fail('subscription_proof_invalid')
    if (type(current) is not dict or set(current) != {'schema_version','current_snapshot','objects'}
            or current['schema_version'] != 'memoir-subscription-source-proof/3'
            or type(current['objects']) is not dict):
        _fail('subscription_proof_invalid')
    # Reuse the unchanged, mutation-tested bounded Git-object parser. Its old
    # snapshot names/bytes are retained; new objects supplement rather than
    # relabel either historical snapshot.
    combined = {**old, 'objects': {**old['objects'], **current['objects']}}
    proof = v2._Proof(json.dumps(combined).encode())
    historic = proof.snapshot('historical-v1', v2.HISTORICAL_REVISION, v2.HISTORICAL_TREE)
    prior = proof.snapshot('issue14-inactive-v2', v2.CURRENT_REVISION, v2.CURRENT_TREE)
    snapshot = current['current_snapshot']
    if (type(snapshot) is not dict or set(snapshot) != {'revision','tree','files'}
            or snapshot['revision'] != CURRENT_REVISION or snapshot['tree'] != CURRENT_TREE
            or type(snapshot['files']) is not dict
            or not proof.object(CURRENT_REVISION, 'commit').startswith(('tree '+CURRENT_TREE+'\n').encode())):
        _fail('subscription_snapshot_invalid')
    for path, entry in snapshot['files'].items():
        if (type(path) is not str or type(entry) is not dict or set(entry) != {'blob','sha256'}
                or not v2._hex(entry['blob'],40) or not v2._hex(entry['sha256'],64)):
            _fail('subscription_snapshot_invalid')
        mode, blob = proof.lookup(CURRENT_TREE,path)
        if mode not in {b'100644',b'100755'} or blob != entry['blob']:
            _fail('subscription_membership_invalid')
    # Archived v2 bodies allow the unchanged old auditor/tests to execute on
    # their actual historical snapshot, not an already-drifted checkout.
    for entry in prior.values():
        if hashlib.sha256(proof.object(entry['blob'],'blob')).hexdigest() != entry['sha256']:
            _fail('historical_v2_blob_invalid')
    if set(historic) != v2.HISTORICAL_PATHS:
        _fail('historical_inventory_invalid')
    return root, proof, historic, prior, snapshot['files'], old_raw, auditor


def _tree_inventory(proof):
    paths = set(EXTRA_PATHS)
    for prefix in ('apps/api','scripts'):
        paths.update(proof.python_inventory(CURRENT_TREE,prefix))
    def all_files(node,path,depth=0):
        if depth > 20:
            _fail('source_tree_invalid')
        for name,(mode,child) in proof.tree(node).items():
            try:
                relative=path+'/'+name.decode('utf-8')
            except UnicodeError:
                _fail('source_path_invalid')
            if mode==b'40000':
                all_files(child,relative,depth+1)
            elif mode in {b'100644',b'100755'}:
                paths.add(relative)
            else:
                _fail('source_path_invalid')
    for prefix in ('skills','supabase'):
        mode,node=proof.lookup(CURRENT_TREE,prefix)
        if mode!=b'40000':_fail('source_path_invalid')
        all_files(node,prefix)
    return paths - TOOLING_PATHS


def _inventory(root):
    paths=set(EXTRA_PATHS)
    def unreadable(_error):_fail('source_inventory_unavailable')
    for prefix in ('apps/api','scripts','skills','supabase'):
        directory=root/prefix
        if directory.is_symlink() or not directory.is_dir():_fail('source_inventory_invalid')
        for parent,dirs,files in os.walk(directory,followlinks=False,onerror=unreadable):
            if any((Path(parent)/name).is_symlink() for name in dirs):_fail('source_inventory_invalid')
            for name in files:
                if prefix in ('apps/api','scripts') and not name.endswith('.py'):continue
                paths.add((Path(parent)/name).relative_to(root).as_posix())
    return paths - TOOLING_PATHS


def historical_v2_files(root):
    """Verified original v2 snapshot for historical regression fixtures only."""
    root,proof,_,prior,_,old_raw,auditor=_load(root)
    return {**{path:proof.object(entry['blob'],'blob') for path,entry in prior.items()},
            v2.PROOF_PATH:old_raw, v2.AUDIT_PATH:auditor}


def audit_subscription_source(root):
    root,proof,historic,prior,current,_,_=_load(root)
    expected=_tree_inventory(proof)
    if set(current)!=expected or _inventory(root)!=expected:
        _fail('source_inventory_invalid')
    actual={}
    for path,entry in current.items():
        raw=v2._read(root,path)
        if v2._git_hash('blob',raw)!=entry['blob'] or hashlib.sha256(raw).hexdigest()!=entry['sha256']:
            _fail('current_source_mismatch')
        actual[path]=raw
    legacy=actual['scripts/fifty_round_budget_contract.py']
    if v2._git_hash('blob',legacy)!=v2.LEGACY_MODULE_BLOB:
        _fail('historical_contract_changed')
    constants={node.targets[0].id:ast.literal_eval(node.value)
        for node in ast.parse(legacy).body if isinstance(node,ast.Assign) and len(node.targets)==1
        and isinstance(node.targets[0],ast.Name) and node.targets[0].id=='DERIVATION_FILE_SHA256'}
    pins=constants.get('DERIVATION_FILE_SHA256',{})
    if set(pins)!=v2.HISTORICAL_PATHS:_fail('historical_pin_invalid')
    for path,entry in historic.items():
        if hashlib.sha256(proof.object(entry['blob'],'blob')).hexdigest()!=pins[path]:
            _fail('historical_pin_invalid')
    old_drift=sorted(path for path,entry in prior.items()
        if path not in actual or hashlib.sha256(actual[path]).hexdigest()!=entry['sha256'])
    return {'schema_version':'memoir-subscription-source-audit/3','source_gate_passed':True,
        'scope':'source_integrity_not_execution_or_provider_authority',
        'historical_derivation_integrity_verified':True,'historical_v2_integrity_verified':True,
        'historical_v2_snapshot_revision':v2.CURRENT_REVISION,'historical_v2_matches_current_source':not old_drift,
        'historical_v2_drift_paths':old_drift,'current_snapshot_revision':CURRENT_REVISION,
        'current_snapshot_tree':CURRENT_TREE,'current_source_matches_reviewed_snapshot':True,
        'current_source_file_count':len(current),'live_execution_authorized':False,
        'provider_capability_verified':False,'hard_token_or_monetary_limit_enforced':False}
