#!/usr/bin/env bash
# Emit a bash COMPOSE_ARGS array assignment for VPS deploy scripts.
# Usage: eval "$(./scripts/deploy/compose-args.sh)"
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BASE_COMPOSE="${COMPOSE_FILE:-docker-compose.vps.yml}"

args=(-f "$ROOT_DIR/$BASE_COMPOSE")

if [[ -f "$ROOT_DIR/.env" ]]; then
  # shellcheck disable=SC1091
  set -a
  # shellcheck disable=SC1090
  source "$ROOT_DIR/.env"
  set +a
fi

use_shared_proxy="${SHARED_PROXY:-0}"
if [[ "$use_shared_proxy" == "1" || "$use_shared_proxy" == "true" ]]; then
  if [[ ! -f "$ROOT_DIR/docker-compose.vps.shared-proxy.yml" ]]; then
    echo "error: SHARED_PROXY is set but docker-compose.vps.shared-proxy.yml is missing" >&2
    exit 1
  fi
  args+=(-f "$ROOT_DIR/docker-compose.vps.shared-proxy.yml")
fi

printf 'COMPOSE_ARGS=('
for arg in "${args[@]}"; do
  printf '%q ' "$arg"
done
printf ')\n'
