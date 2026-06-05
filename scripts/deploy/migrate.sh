#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

cd "$ROOT_DIR"

if [[ ! -f .env ]]; then
  echo "error: .env not found in $ROOT_DIR" >&2
  echo "Copy .env.example to .env and set production secrets first." >&2
  exit 1
fi

eval "$("$ROOT_DIR/scripts/deploy/compose-args.sh")"

echo "Running Alembic migrations (compose: ${COMPOSE_ARGS[*]})..."
docker compose "${COMPOSE_ARGS[@]}" run --rm --no-deps api \
  alembic upgrade head

echo "Migrations complete."
