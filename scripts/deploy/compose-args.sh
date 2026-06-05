#!/usr/bin/env bash
# Emit COMPOSE_ARGS for production deploy scripts.
# Usage: eval "$(./scripts/deploy/compose-args.sh)"
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

args=(
  -f "$ROOT_DIR/docker-compose.production.yml"
)

if [[ -f "$ROOT_DIR/docker-compose.local.yml" ]]; then
  args+=(-f "$ROOT_DIR/docker-compose.local.yml")
fi

printf 'COMPOSE_ARGS=('
for arg in "${args[@]}"; do
  printf '%q ' "$arg"
done
printf ')\n'
