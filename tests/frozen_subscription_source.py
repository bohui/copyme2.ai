"""Materialize immutable v6 source evidence for offline historical tests only.

The current checkout must still pass its own admission gates. Reconstructing
these authenticated historical inputs grants no authority to run or publish it.
"""
import hashlib
from pathlib import Path

from scripts import issue14_subscription_source_contract_v6 as v6


def materialize_frozen_v6(destination):
    source = Path(__file__).resolve().parents[1]
    _, proof, _, _, snapshot, tools = v6._load(source)
    assert len(snapshot) == 303
    files = {}
    for name, entry in snapshot.items():
        raw = proof.object(entry['blob'], 'blob')
        assert hashlib.sha256(raw).hexdigest() == entry['sha256'], name
        files[name] = raw
    files.update(tools)
    for name in (v6.AUDIT_PATH, v6.PROOF_PATH):
        files[name] = v6.v2._read(source, name, maximum=4 * 1024 * 1024)
    for name, raw in files.items():
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)

    # Every mutation test starts with a passing, exact frozen snapshot. This
    # prevents unrelated checkout drift from making a negative test vacuous.
    report = v6.audit_subscription_source_v6(destination)
    assert report['source_gate_passed'] is True
    assert report['current_source_matches_reviewed_snapshot'] is True
    assert report['current_snapshot_revision'] == v6.CURRENT_REVISION
    assert report['current_snapshot_tree'] == v6.CURRENT_TREE
    assert report['live_execution_authorized'] is False
    assert report['provider_capability_verified'] is False
    assert report['hard_token_or_monetary_limit_enforced'] is False
    return destination
