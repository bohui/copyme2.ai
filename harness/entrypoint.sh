#!/bin/sh
set -eu

# The developer harness uses the same local provider as the application
# runtime. The provider reads its credential from the container environment;
# no Codex account login or credential file is needed.
mkdir -p "${CODEX_HOME:-/codex-home}"
python3 - <<'PY'
import json
import os
from pathlib import Path

home = Path(os.environ.get("CODEX_HOME", "/codex-home"))
base_url = os.environ.get("MEMORY_SPARK_LLM_BASE_URL", "http://127.0.0.1:4000/v1").rstrip("/")
model = os.environ.get("MEMORY_SPARK_LLM_MODEL", "deepseek-v4-flash")
config = "\n".join([
    'model_provider = "llm_provider"',
    'model = ' + json.dumps(model),
    'approval_policy = "never"',
    'sandbox_mode = "read-only"',
    "[model_providers.llm_provider]",
    'name = "Local llm_provider"',
    'base_url = ' + json.dumps(base_url),
    'wire_api = "responses"',
    'env_key = "MEMORY_SPARK_LLM_API_KEY"',
    'requires_openai_auth = false',
    "",
])
(home / "config.toml").write_text(config, encoding="utf-8")
PY

exec "$@"
