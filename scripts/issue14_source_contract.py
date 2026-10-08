"""Offline versioned source integrity for issue 14's inactive implementation.

Historical proposal bytes remain frozen. Current source eligibility is a
separate contract, never provider capability, budget approval or live admission.
This module reads source/proof files only; it imports or executes no app code.
"""
import ast
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import zlib


PROOF_PATH = 'tests/fixtures/issue14_source_contract_v2.json'
AUDIT_PATH = 'scripts/issue14_source_contract.py'
HISTORICAL_REVISION = '3a9a339813ed06fb06ba18815bf32b880072314e'
HISTORICAL_TREE = '640f47d4ea8d1e8cb52f3198dfb93719cec1457e'
CURRENT_REVISION = '1026a1b97731f098962d045d24fefa581797ca67'
CURRENT_TREE = '60445c90ce5a16968719cb530e932560e45b35c3'
LEGACY_MODULE_BLOB = 'fd809659e5b3eb31e9593d5340f904a534efbda8'
HISTORICAL_PATHS = frozenset({
    'apps/api/codex_runtime.py', 'apps/api/codex_worker_service.py',
    'apps/api/memory_event_worker.py', 'apps/api/memory_events.py',
    'apps/api/canonical_composer.py', 'apps/api/memoir_preview.py',
    'apps/api/temporal_workflows.py', 'apps/api/codex_agent.py',
    'scripts/canary_worker.py', 'scripts/canary_send_guard.py',
    'scripts/canary_gateway_actor.py', 'compose.yml', '.env.example',
})
EXTRA_SOURCE_PATHS = frozenset({'apps/__init__.py', 'pyproject.toml', 'compose.yml', '.env.example'})
_MAX_OBJECT_BYTES = 3 * 1024 * 1024


class SourceContractError(ValueError):
    """A fixed source-validation failure; never a request to run a provider."""


def _fail(reason):
    raise SourceContractError(reason)


def _hex(value, length):
    return type(value) is str and re.fullmatch('[0-9a-f]{' + str(length) + '}', value) is not None


def _git_hash(kind, raw):
    return hashlib.sha1(kind.encode() + b' ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()


def _read(root, relative, maximum=_MAX_OBJECT_BYTES):
    # Walk from an owned directory descriptor. Never follow a source/proof link
    # or read a guessed environment file outside the explicit inventory.
    parts = relative.split('/')
    if any(not part or part in {'.', '..'} for part in parts):
        _fail('source_path_invalid')
    descriptor = None
    try:
        descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        # Inspect non-regular entries without blocking on a FIFO's writer.
        child = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
        os.close(descriptor)
        descriptor = child
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > maximum:
            _fail('source_file_invalid')
        chunks, size = [], 0
        while True:
            chunk = os.read(descriptor, min(65536, maximum + 1 - size))
            if not chunk:
                break
            size += len(chunk)
            if size > maximum:
                _fail('source_file_invalid')
            chunks.append(chunk)
        return b''.join(chunks)
    except OSError:
        _fail('source_file_unavailable')
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _fail('proof_invalid')
        result[key] = value
    return result


class _Proof:
    def __init__(self, raw):
        try:
            value = json.loads(raw, object_pairs_hook=_unique)
        except (ValueError, UnicodeError, RecursionError):
            _fail('proof_invalid')
        if (type(value) is not dict or set(value) != {'schema_version', 'snapshots', 'objects'}
                or value['schema_version'] != 'memoir-source-proof/1'
                or type(value['snapshots']) is not dict
                or set(value['snapshots']) != {'historical-v1', 'issue14-inactive-v2'}
                or type(value['objects']) is not dict or not 1 <= len(value['objects']) <= 1000):
            _fail('proof_invalid')
        self.snapshots, self.objects = value['snapshots'], {}
        total = 0
        for sha, entry in value['objects'].items():
            if (not _hex(sha, 40) or type(entry) is not dict
                    or set(entry) != {'kind', 'size', 'data'}
                    or type(entry['kind']) is not str or entry['kind'] not in {'commit', 'tree', 'blob'}
                    or type(entry['size']) is not int or not 0 <= entry['size'] <= _MAX_OBJECT_BYTES
                    or type(entry['data']) is not str):
                _fail('proof_object_invalid')
            try:
                encoded = base64.b64decode(entry['data'], validate=True)
                decoder = zlib.decompressobj()
                content = decoder.decompress(encoded, entry['size'] + 1)
            except (ValueError, zlib.error):
                _fail('proof_object_invalid')
            total += len(content)
            if (len(content) != entry['size'] or not decoder.eof or decoder.unconsumed_tail
                    or decoder.unused_data or total > 8 * 1024 * 1024
                    or _git_hash(entry['kind'], content) != sha):
                _fail('proof_object_invalid')
            self.objects[sha] = (entry['kind'], content)

    def object(self, sha, kind):
        if sha not in self.objects or self.objects[sha][0] != kind:
            _fail('proof_object_unavailable')
        return self.objects[sha][1]

    def tree(self, sha):
        raw, offset, entries = self.object(sha, 'tree'), 0, {}
        order = []
        while offset < len(raw):
            space, null = raw.find(b' ', offset), raw.find(b'\0', offset)
            if space <= offset or null <= space or null + 21 > len(raw):
                _fail('proof_tree_invalid')
            mode, name = raw[offset:space], raw[space + 1:null]
            if (mode not in {b'40000', b'100644', b'100755', b'120000', b'160000'}
                    or not name or b'/' in name or name in {b'.', b'..'} or name in entries):
                _fail('proof_tree_invalid')
            entries[name] = (mode, raw[null + 1:null + 21].hex())
            order.append(name + (b'/' if mode == b'40000' else b''))
            offset = null + 21
        if order != sorted(order):
            _fail('proof_tree_invalid')
        return entries

    def lookup(self, tree, path):
        parts = path.split('/')
        if any(part in {'', '.', '..'} for part in parts):
            _fail('proof_path_invalid')
        mode = b'40000'
        for part in parts:
            if mode != b'40000':
                _fail('proof_path_invalid')
            entry = self.tree(tree).get(part.encode())
            if entry is None:
                _fail('proof_membership_invalid')
            mode, tree = entry
        return mode, tree

    def python_inventory(self, tree, prefix):
        mode, sha = self.lookup(tree, prefix)
        if mode != b'40000':
            _fail('proof_path_invalid')
        paths = set()
        def walk(node, path, depth):
            if depth > 20:
                _fail('proof_tree_invalid')
            for name, (entry_mode, child) in self.tree(node).items():
                try:
                    relative = path + '/' + name.decode('utf-8')
                except UnicodeError:
                    _fail('proof_path_invalid')
                if entry_mode == b'40000':
                    walk(child, relative, depth + 1)
                elif relative.endswith('.py'):
                    if entry_mode not in {b'100644', b'100755'}:
                        _fail('proof_path_invalid')
                    paths.add(relative)
        walk(sha, prefix, 0)
        return paths

    def snapshot(self, name, revision, tree):
        value = self.snapshots[name]
        if (type(value) is not dict or set(value) != {'revision', 'tree', 'files'}
                or value['revision'] != revision or value['tree'] != tree
                or type(value['files']) is not dict):
            _fail('proof_snapshot_invalid')
        commit = self.object(revision, 'commit')
        if not commit.startswith(('tree ' + tree + '\n').encode()):
            _fail('proof_snapshot_invalid')
        for path, entry in value['files'].items():
            if (type(path) is not str or type(entry) is not dict
                    or set(entry) != {'blob', 'sha256'}
                    or not _hex(entry['blob'], 40) or not _hex(entry['sha256'], 64)):
                _fail('proof_snapshot_invalid')
            mode, blob = self.lookup(tree, path)
            if mode not in {b'100644', b'100755'} or blob != entry['blob']:
                _fail('proof_membership_invalid')
        return value['files']


def _current_inventory(root):
    result = set(EXTRA_SOURCE_PATHS)
    def unreadable(_error):
        _fail('source_inventory_unavailable')
    for prefix in ('apps/api', 'scripts'):
        directory = root / prefix
        if directory.is_symlink() or not directory.is_dir():
            _fail('source_inventory_invalid')
        for current, dirs, files in os.walk(directory, followlinks=False, onerror=unreadable):
            if any((Path(current) / name).is_symlink() for name in dirs):
                _fail('source_inventory_invalid')
            for name in files:
                if name.endswith('.py'):
                    relative = (Path(current) / name).relative_to(root).as_posix()
                    if relative != AUDIT_PATH:
                        result.add(relative)
    return result


def audit_source_contract(root):
    """Require historical integrity AND current snapshot/inventory equality.

    The source auditor itself, tests and documentation are reviewed tooling,
    not executable application inputs in the earlier snapshot. Its one explicit
    path is excluded from the Python inventory; no wildcard additions are allowed.
    """
    root = Path(root).absolute()
    proof = _Proof(_read(root, PROOF_PATH, maximum=4 * 1024 * 1024))
    historic = proof.snapshot('historical-v1', HISTORICAL_REVISION, HISTORICAL_TREE)
    current = proof.snapshot('issue14-inactive-v2', CURRENT_REVISION, CURRENT_TREE)
    if set(historic) != HISTORICAL_PATHS:
        _fail('historical_inventory_invalid')
    expected = set(EXTRA_SOURCE_PATHS)
    for prefix in ('apps/api', 'scripts'):
        expected.update(proof.python_inventory(CURRENT_TREE, prefix))
    if set(current) != expected or _current_inventory(root) != expected:
        _fail('source_inventory_invalid')
    actual = {}
    for path, entry in current.items():
        raw = _read(root, path)
        if (_git_hash('blob', raw) != entry['blob']
                or hashlib.sha256(raw).hexdigest() != entry['sha256']):
            _fail('current_source_mismatch')
        actual[path] = raw
    module = actual['scripts/fifty_round_budget_contract.py']
    if _git_hash('blob', module) != LEGACY_MODULE_BLOB:
        _fail('historical_contract_changed')
    try:
        constants = {node.targets[0].id: ast.literal_eval(node.value)
            for node in ast.parse(module).body if isinstance(node, ast.Assign)
            and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id in {'DERIVATION_SOURCE_REVISION', 'DERIVATION_SOURCE_TREE',
                'DERIVATION_FILE_SHA256', 'SCHEMA_VERSION'}}
    except (ValueError, TypeError, SyntaxError):
        _fail('historical_contract_changed')
    if (constants.get('DERIVATION_SOURCE_REVISION') != HISTORICAL_REVISION
            or constants.get('DERIVATION_SOURCE_TREE') != HISTORICAL_TREE
            or constants.get('SCHEMA_VERSION') != 'memoir-fifty-budget-proposal/1'
            or type(constants.get('DERIVATION_FILE_SHA256')) is not dict
            or set(constants['DERIVATION_FILE_SHA256']) != HISTORICAL_PATHS):
        _fail('historical_contract_changed')
    drift = []
    for path, entry in historic.items():
        raw = proof.object(entry['blob'], 'blob')
        expected_sha = constants['DERIVATION_FILE_SHA256'][path]
        if hashlib.sha256(raw).hexdigest() != expected_sha or entry['sha256'] != expected_sha:
            _fail('historical_pin_invalid')
        if hashlib.sha256(actual[path]).hexdigest() != expected_sha:
            drift.append(path)
    return {'schema_version': 'memoir-issue14-source-audit/2',
        'scope': 'inactive_source_integrity_not_provider_or_campaign_admission',
        'source_gate_passed': True, 'historical_derivation_integrity_verified': True,
        'historical_revision': HISTORICAL_REVISION, 'historical_tree': HISTORICAL_TREE,
        'current_snapshot_revision': CURRENT_REVISION, 'current_snapshot_tree': CURRENT_TREE,
        'current_source_matches_reviewed_snapshot': True, 'current_source_file_count': len(current),
        'legacy_derivation_matches_current_source': not drift,
        'legacy_source_drift_paths': sorted(drift), 'live_execution_authorized': False,
        'provider_capability_verified': False, 'hard_token_or_monetary_limit_enforced': False}
