#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$REPO_ROOT"

ENV_FILE="$REPO_ROOT/.env"
if [[ -f "$ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  source "$ENV_FILE"
fi

: "${DEX_PROXY_BASE:=http://127.0.0.1:1958}"
export DEX_PROXY_BASE

printf '%s\n' \
  "[run_vasquez_local] Using DEX proxy base: ${DEX_PROXY_BASE}" \
  "[run_vasquez_local] Default symbol: ETHUSDT"

exec python vasquez/examples/run_vasquez_binance.py --base "$DEX_PROXY_BASE" "$@"
