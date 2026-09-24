#!/usr/bin/env python3
"""Create a verified copy of a local Memory Spark store snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import tarfile
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--objects", type=Path, help="Filesystem object-store root to include")
    parser.add_argument("--objects-output", type=Path, help="Gzip tar archive path for the object store")
    args = parser.parse_args()

    if bool(args.objects) != bool(args.objects_output):
        raise SystemExit("--objects and --objects-output must be provided together")

    payload = json.loads(args.source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("store", payload), dict):
        raise SystemExit("source is not a valid Memory Spark snapshot")
    raw = args.source.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{args.output.name}.", suffix=".tmp", dir=args.output.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, args.output)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
    manifest = {
        "source": str(args.source),
        "backup": str(args.output),
        "sha256": digest,
        "bytes": len(raw),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    args.output.with_suffix(args.output.suffix + ".manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Backup: {args.output}")
    print(f"SHA256: {digest}")

    if args.objects and args.objects_output:
        if not args.objects.exists() or not args.objects.is_dir():
            raise SystemExit(f"object store does not exist or is not a directory: {args.objects}")
        entries = []
        args.objects_output.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(prefix=f".{args.objects_output.name}.", suffix=".tmp", dir=args.objects_output.parent)
        os.close(fd)
        try:
            with tarfile.open(temporary_name, mode="w:gz") as archive:
                for path in sorted(item for item in args.objects.rglob("*") if item.is_file()):
                    relative = path.relative_to(args.objects).as_posix()
                    content = path.read_bytes()
                    archive.add(path, arcname=relative, recursive=False)
                    entries.append({"path": relative, "sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content)})
            os.replace(temporary_name, args.objects_output)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)
        object_raw = args.objects_output.read_bytes()
        object_manifest = {
            "objects": str(args.objects),
            "backup": str(args.objects_output),
            "archive_sha256": hashlib.sha256(object_raw).hexdigest(),
            "file_count": len(entries),
            "files": entries,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        args.objects_output.with_suffix(args.objects_output.suffix + ".manifest.json").write_text(json.dumps(object_manifest, indent=2) + "\n", encoding="utf-8")
        print(f"Objects: {args.objects_output} ({len(entries)} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
