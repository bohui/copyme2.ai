"""Read-only W0 inventory of an explicitly supplied JSON fixture/export.

No network/database access, implicit production input, or automatic mapping.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from apps.api.lifetime_memory_contracts import inventory_accounts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path, help='Explicit local JSON account inventory')
    args = parser.parse_args()
    accounts = json.loads(args.input.read_text(encoding='utf-8'))
    if not isinstance(accounts, list):
        parser.error('input must be an array of account inventories')
    print(json.dumps({'schema_version': 1, 'read_only': True, 'accounts': inventory_accounts(accounts)}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
