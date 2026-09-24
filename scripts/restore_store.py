#!/usr/bin/env python3
"""Verify and atomically restore a local Memory Spark store snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
import tarfile
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backup", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--objects-backup", type=Path, help="Gzip tar archive produced by backup_store.py")
    parser.add_argument("--objects-destination", type=Path, help="Filesystem object-store destination")
    args = parser.parse_args()

    if bool(args.objects_backup) != bool(args.objects_destination):
        raise SystemExit("--objects-backup and --objects-destination must be provided together")

    raw = args.backup.read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("store", payload), dict):
        raise SystemExit("backup is not a valid Memory Spark snapshot")
    manifest_path = args.backup.with_suffix(args.backup.suffix + ".manifest.json")
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        expected = manifest.get("sha256")
        actual = hashlib.sha256(raw).hexdigest()
        if expected != actual:
            raise SystemExit("backup checksum does not match its manifest")
    args.destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{args.destination.name}.", suffix=".tmp", dir=args.destination.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, args.destination)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)
    print(f"Restored: {args.destination}")
    print(f"SHA256: {hashlib.sha256(raw).hexdigest()}")

    if args.objects_backup and args.objects_destination:
        if not args.objects_backup.exists():
            raise SystemExit(f"object backup does not exist: {args.objects_backup}")
        object_manifest_path = args.objects_backup.with_suffix(args.objects_backup.suffix + ".manifest.json")
        object_manifest = json.loads(object_manifest_path.read_text(encoding="utf-8")) if object_manifest_path.exists() else {}
        object_raw = args.objects_backup.read_bytes()
        expected_archive_hash = object_manifest.get("archive_sha256")
        if expected_archive_hash and expected_archive_hash != hashlib.sha256(object_raw).hexdigest():
            raise SystemExit("object backup checksum does not match its manifest")
        args.objects_destination.parent.mkdir(parents=True, exist_ok=True)
        temporary_directory = Path(tempfile.mkdtemp(prefix=f".{args.objects_destination.name}.", dir=args.objects_destination.parent))
        try:
            with tarfile.open(args.objects_backup, mode="r:gz") as archive:
                members = archive.getmembers()
                for member in members:
                    member_path = Path(member.name)
                    if member_path.is_absolute() or ".." in member_path.parts:
                        raise SystemExit("object backup contains an unsafe path")
                    if member.issym() or member.islnk():
                        raise SystemExit("object backup may not contain links")
                # The explicit member checks above keep extraction safe on
                # Python 3.11, whose TarFile.extractall has no filter argument.
                archive.extractall(temporary_directory)
            expected_files = {entry["path"]: entry for entry in object_manifest.get("files", [])}
            actual_files = {path.relative_to(temporary_directory).as_posix(): path for path in temporary_directory.rglob("*") if path.is_file()}
            if expected_files and set(expected_files) != set(actual_files):
                raise SystemExit("object backup file manifest does not match the archive")
            for relative, path in actual_files.items():
                expected = expected_files.get(relative)
                if expected and (expected.get("bytes") != path.stat().st_size or expected.get("sha256") != hashlib.sha256(path.read_bytes()).hexdigest()):
                    raise SystemExit(f"object checksum does not match its manifest: {relative}")
            old_destination = args.objects_destination.with_name(f".{args.objects_destination.name}.old")
            if old_destination.exists():
                shutil.rmtree(old_destination)
            if args.objects_destination.exists():
                os.replace(args.objects_destination, old_destination)
            os.replace(temporary_directory, args.objects_destination)
            if old_destination.exists():
                shutil.rmtree(old_destination)
            print(f"Objects restored: {args.objects_destination} ({len(actual_files)} files)")
        finally:
            if temporary_directory.exists():
                shutil.rmtree(temporary_directory)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
