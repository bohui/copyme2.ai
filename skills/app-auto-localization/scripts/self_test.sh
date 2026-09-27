#!/usr/bin/env bash
set -euo pipefail
SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TSC="${TSC:-tsc}"
BUILD_DIR="$(mktemp -d)"
export BUILD_DIR
trap 'rm -rf "$BUILD_DIR"' EXIT
"$TSC" "$SKILL_DIR/assets/runtime/locale-policy.ts" \
  "$SKILL_DIR/assets/runtime/text-signal.ts" \
  --strict --target ES2022 --module commonjs --skipLibCheck --outDir "$BUILD_DIR"
node --test "$SKILL_DIR/tests/test_runtime.cjs"
python3 -m unittest discover -s "$SKILL_DIR/tests" -p 'test_*.py' -v
python3 "$SKILL_DIR/scripts/check_catalogs.py" \
  "$SKILL_DIR/assets/messages/en-AU.json" "$SKILL_DIR/assets/messages/zh-CN.json"
# Browser/Next.js integration and the real franc/ICU dependencies are NOT tested here.
