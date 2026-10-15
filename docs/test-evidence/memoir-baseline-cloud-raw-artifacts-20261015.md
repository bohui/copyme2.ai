# PR69: transferable original cloud evidence

This evidence-only follow-up makes **all 42 original files** in the
`c74715a360d10b25f7ac87fe3b31203dca870bb6` aggregate ledger available through
the repository. The originals were still present in this implementation
workspace. Every original matched its recorded SHA-256 before packaging;
every archive member was read back and compared byte-for-byte afterwards.
No repository test, build, service or supplementary check command was rerun.
No missing original was reconstructed.

- [Accessible-path manifest](memoir-baseline-cloud-raw-artifacts-20261015.json)
  maps each original absolute `/tmp` path to a relative archive member, byte
  count and original SHA-256.
- [Original raw-file bundle](memoir-baseline-cloud-raw-artifacts-20261015.tar.gz)
  contains all 42 regular files, including the empty lint log, unchanged.
- [Original aggregate ledger](memoir-baseline-cloud-aggregate-20261015.json)
  remains unchanged; its `raw_evidence_sha256` map is the authority for all
  original hashes.

The bundle covers four XML files, twelve check receipts, twelve check logs,
eleven supporting environment/phase/provenance files and three helper files.
It includes the supplementary originals that the independent reviewer could
not access, without requiring a reviewer-specific list of missing files.
Archive metadata is normalized; **file contents are not edited or redacted**.

## Content review and limits

The files come from the existing synthetic controlled aggregate. Provider/
service authority was cleared, no real user data was used, and the browser
boundary allowed only owned loopback origins. Credential/private-key/cloud-key/
JWT and credential-URL/email shapes were screened, resulting matches were
checked against tracked negative-test literals, and structured metadata/helper
content was reviewed. No real secrets or private user data were found, so no
file was excluded and no redaction changed an original hash.

The credential-shaped URL in the JUnit input is the tracked literal
`user:password` rejection case in `tests/test_memoir_fifty_photo.py:165-170`.
The email-shaped wrong-destination input is the before-network rejection case
in `tests/test_setup_memoir_test_accounts.py:200-204`. These are synthetic test
parameters, not credentials collected from a service. Local process IDs, paths,
loopback ports, synthetic UUIDs and parent-supplied task identifiers remain as
originally recorded.

Parent-reported audit of exact `c74715a` found no discrepancy in the evidence
delta, 1,037 non-document source files, case archives, comparison or 593 retained
failures/errors. It independently verified **22 of 42** raw hashes; **20
original files were unavailable in that review task**. That earlier limitation
is not retroactively described as verification. This delivery is verified by
the implementation agent; independent verification of the transferred bundle
is pending re-review through the parent for task
`01a1404f-c3cb-760e-aa04-bd89f35b50d0`.

## Verification without executing or extracting helpers

From the repository root, this reads archive members in memory, verifies the
bundle hash and all 42 original hashes, and confirms the manifest matches the
unchanged aggregate ledger. It neither executes helper code nor writes to the
original `/tmp` paths:

```python
from pathlib import Path
import hashlib
import json
import tarfile

folder = Path("docs/test-evidence")
manifest = json.loads((folder / "memoir-baseline-cloud-raw-artifacts-20261015.json").read_text())
ledger = json.loads(Path(manifest["source_ledger_path"]).read_text())
bundle = Path(manifest["archive"]["repository_path"])
assert hashlib.sha256(bundle.read_bytes()).hexdigest() == manifest["archive"]["sha256"]
expected = {entry["original_path"]: entry["sha256"] for entry in manifest["artifacts"]}
assert expected == ledger["raw_evidence_sha256"]
with tarfile.open(bundle, "r:gz") as archive:
    assert len(archive.getmembers()) == 42
    assert all(member.isfile() for member in archive.getmembers())
    assert {member.name for member in archive.getmembers()} == {
        entry["archive_member"] for entry in manifest["artifacts"]
    }
    for entry in manifest["artifacts"]:
        raw = archive.extractfile(entry["archive_member"]).read()
        assert len(raw) == entry["bytes"]
        assert hashlib.sha256(raw).hexdigest() == entry["sha256"]
print("Verified all 42 original raw-artifact hashes")
```

The manifest identifies the original ledger revision, actual execution head
`b4e184c8ad2568b6c671b0f6ea22b0ae404b8afb` and unchanged source/test revision
`51ca7fe5629f74f6a657a7a2e611d86dabf91bf8`. The aggregate remains **5,478
passed, 572 failed, 21 errors and 249 skipped**. All 593 failures/errors and
existing policy/platform/acceptance limits remain unchanged. This transfer
adds no source edit, test result, policy decision, merge or deployment.
