#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.vps.yml}"

cd "$ROOT_DIR"

if [[ ! -f .env ]]; then
  echo "error: .env not found in $ROOT_DIR" >&2
  echo "Copy .env.vps.example to .env and set production secrets first." >&2
  exit 1
fi

echo "Running Alembic migrations (compose file: $COMPOSE_FILE)..."
docker compose -f "$COMPOSE_FILE" run --rm --no-deps api \
  alembic upgrade head

echo "Migrations complete."
