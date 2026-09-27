#!/usr/bin/env python3
"""Structural catalogue check. Full ICU validation is a SEPARATE required check.
Rejects duplicate JSON keys, non-string leaves, empty strings, dotted key names,
missing/extra keys and mismatched argument-name sets. Not an ICU grammar parser.
"""
from __future__ import annotations
import argparse
import json
import re
from pathlib import Path

def reject_duplicates(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f'Duplicate JSON key: {key}')
        out[key] = value
    return out

def load_catalog(path: Path) -> dict[str, str]:
    data = json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=reject_duplicates)
    out = {}
    def walk(node, prefix=''):
        if not isinstance(node, dict) or not node:
            raise ValueError(f'Expected nonempty object at {prefix or "root"}')
        for key, value in node.items():
            if not key or '.' in key:
                raise ValueError(f'Empty/dotted catalogue key: {key}')
            full = f'{prefix}.{key}' if prefix else key
            if isinstance(value, dict):
                walk(value, full)
            elif isinstance(value, str) and value.strip():
                out[full] = value
            else:
                raise ValueError(f'Expected nonempty message string at {full}')
    walk(data)
    return out

def argument_names(value: str) -> set[str]:
    # Approximate: quoted ICU literals can cause false positives. Full parser wins.
    return set(re.findall(r'\{\s*([A-Za-z_][A-Za-z_0-9]*)\s*(?:[,}])', value))

def compare(base: dict[str, str], other: dict[str, str]) -> list[dict]:
    errors = []
    for key in sorted(base.keys() - other.keys()):
        errors.append({'kind': 'missing_key', 'key': key})
    for key in sorted(other.keys() - base.keys()):
        errors.append({'kind': 'extra_key', 'key': key})
    for key in sorted(base.keys() & other.keys()):
        if argument_names(base[key]) != argument_names(other[key]):
            errors.append({'kind': 'argument_name_mismatch', 'key': key})
    return errors

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('base', type=Path)
    parser.add_argument('translations', type=Path, nargs='+')
    args = parser.parse_args()
    try:
        base = load_catalog(args.base)
        results = [{'file': str(p), 'errors': compare(base, load_catalog(p))} for p in args.translations]
    except (OSError, ValueError) as exc:
        parser.exit(2, f'{exc}\n')
    ok = all(not r['errors'] for r in results)
    print(json.dumps({'structural_ok': ok, 'base_keys': len(base), 'results': results,
        'full_icu_validation': 'NOT_RUN',
        'note': 'Run check_icu.mjs with the target app parser before release.'}, indent=2))
    raise SystemExit(0 if ok else 1)
if __name__ == '__main__':
    main()
