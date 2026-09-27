#!/usr/bin/env python3
"""Read-only, bounded source inventory. Emits paths/line numbers, not source text.
Heuristic discovery only: this is not a complete localization/AST audit.
"""
from __future__ import annotations
import argparse
import json
import os
import re
from pathlib import Path

SKIP = {'.git', '.agents', '.codex', '.next', 'node_modules', 'dist', 'build',
        '.venv', 'venv', 'coverage', 'uploads', 'recordings', 'transcripts',
        'secrets', '.idea', '__pycache__', 'vendor', '.turbo'}
SOURCE = {'.tsx', '.jsx', '.ts', '.js', '.mjs', '.py', '.html'}
PATTERNS = {
    'jsx_literal': re.compile(r'>\s*[A-Za-z\u3400-\u9fff][^<>{}\n]{2,}<'),
    'literal_accessibility_or_input_label': re.compile(r'(?:aria-label|placeholder|title|alt)\s*=\s*[\"\'][^\"\']+[\"\']'),
    'literal_notification': re.compile(r'(?:toast|alert|confirm)(?:\.[a-zA-Z]+)?\s*\(\s*[\"\']'),
    'possible_error_text': re.compile(r'(?:detail|message)\s*[:=]\s*[\"\'][A-Za-z\u3400-\u9fff]'),
    'localization_usage': re.compile(r'next-intl|useTranslations|getTranslations|Intl\.'),
    'state_sensitive': re.compile(r'MediaRecorder|recording|paymentInProgress|beforeunload'),
}

def inventory(root: Path, max_files: int = 15000) -> dict:
    root = root.resolve()
    if not root.is_dir():
        raise ValueError('Repository path must be an existing directory')
    result = {'root': str(root), 'heuristic_only': True, 'truncated': False,
              'scanned_files': 0, 'packages': [], 'routes': [], 'findings': []}
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in SKIP and not d.startswith('.')
                          and not (Path(directory) / d).is_symlink())
        for name in sorted(files):
            path = Path(directory) / name
            if path.is_symlink() or name.startswith('.') or path.stat().st_size > 1_000_000:
                continue
            if name != 'package.json' and path.suffix not in SOURCE:
                continue
            if result['scanned_files'] >= max_files:
                result['truncated'] = True
                return result
            result['scanned_files'] += 1
            relative = str(path.relative_to(root))
            try:
                text = path.read_text(encoding='utf-8')
            except (UnicodeError, OSError):
                continue
            if name == 'package.json':
                try:
                    package = json.loads(text)
                    deps = {**package.get('dependencies', {}), **package.get('devDependencies', {})}
                    result['packages'].append({'path': relative, 'dependencies': {
                        k: deps[k] for k in ('next', 'react', 'next-intl', 'typescript',
                                            'negotiator', 'franc', 'vitest', '@playwright/test') if k in deps}})
                except (ValueError, TypeError, AttributeError):
                    result['findings'].append({'path': relative, 'line': 1, 'kind': 'invalid-package-json'})
                continue
            if name in {'page.tsx', 'page.jsx', 'layout.tsx', 'layout.jsx', 'route.ts'}:
                result['routes'].append(relative)
            for line_number, line in enumerate(text.splitlines(), 1):
                for kind, pattern in PATTERNS.items():
                    if pattern.search(line):
                        result['findings'].append({'path': relative, 'line': line_number, 'kind': kind})
    return result

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('--max-files', type=int, default=15000)
    args = parser.parse_args()
    if args.max_files < 1:
        parser.error('--max-files must be positive')
    try:
        print(json.dumps(inventory(args.root, args.max_files), ensure_ascii=False, indent=2))
    except (ValueError, OSError) as exc:
        parser.exit(2, f'{exc}\n')
if __name__ == '__main__':
    main()
