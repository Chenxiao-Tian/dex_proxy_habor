#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$REPO_ROOT"

ENV_FILE="$REPO_ROOT/.env"
if [[ -f "$ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  source "$ENV_FILE"
fi

if [[ -z "${HARBOR_API_KEY:-}" ]]; then
  echo "[run_harbor_proxy_local] HARBOR_API_KEY is not set. Export it or populate .env." >&2
  exit 2
fi

CONFIG_PATH="$REPO_ROOT/harbor/harbor.config.json"
if [[ ! -f "$CONFIG_PATH" ]]; then
  cat >&2 <<'MSG'
[run_harbor_proxy_local] Missing harbor/harbor.config.json.
Create it from the staging template in TESTING_VASQUEZ_HARBOR.md before launching the proxy.
MSG
  exit 3
fi

PORT=$(CONFIG_PATH="$CONFIG_PATH" python - <<'PY'
import json
import os
from pathlib import Path
cfg_path = Path(os.environ['CONFIG_PATH'])
with cfg_path.open() as fh:
    config = json.load(fh)
port = (config.get('server') or {}).get('port', 1958)
print(port)
PY
)

export CONFIG_PATH="$CONFIG_PATH"
export PORT="$PORT"
if [[ -z "${DEX_PROXY_BASE:-}" ]]; then
  export DEX_PROXY_BASE="http://127.0.0.1:${PORT}"
fi

printf '%s\n' \
  "[run_harbor_proxy_local] Using config: $CONFIG_PATH" \
  "[run_harbor_proxy_local] Harbor API key length: ${#HARBOR_API_KEY}" \
  "[run_harbor_proxy_local] Listening on: ${DEX_PROXY_BASE} (port ${PORT})"

exec python -m dex_proxy.main -s -c "$CONFIG_PATH" -n harbor "$@"
