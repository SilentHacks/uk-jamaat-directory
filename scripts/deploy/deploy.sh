#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.vps.yml}"
SKIP_BACKUP="${SKIP_BACKUP:-0}"
SKIP_MIGRATE="${SKIP_MIGRATE:-0}"
SKIP_SMOKE="${SKIP_SMOKE:-0}"

cd "$ROOT_DIR"

if [[ ! -f .env ]]; then
  echo "error: .env not found in $ROOT_DIR" >&2
  echo "Copy .env.vps.example to .env and configure production secrets." >&2
  exit 1
fi

echo "==> Deploy checklist: pull/build, backup, migrate, restart, smoke test"
echo "    compose file: $COMPOSE_FILE"

echo "==> Pull latest source (if using git on the server)"
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  git pull --ff-only
else
  echo "    (not a git checkout — skipping pull)"
fi

echo "==> Build and start services"
docker compose -f "$COMPOSE_FILE" up -d --build

if [[ "$SKIP_BACKUP" != "1" ]]; then
  echo "==> Pre-deploy Postgres backup"
  "$ROOT_DIR/scripts/deploy/backup-postgres.sh"
else
  echo "==> Skipping backup (SKIP_BACKUP=1)"
fi

if [[ "$SKIP_MIGRATE" != "1" ]]; then
  echo "==> Apply database migrations"
  "$ROOT_DIR/scripts/deploy/migrate.sh"
else
  echo "==> Skipping migrations (SKIP_MIGRATE=1)"
fi

echo "==> Restart application services"
docker compose -f "$COMPOSE_FILE" up -d --build api worker beat caddy

echo "==> Wait for API health"
for _ in $(seq 1 30); do
  if docker compose -f "$COMPOSE_FILE" exec -T api curl -fsS http://localhost:8000/v1/health >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

if [[ "$SKIP_SMOKE" != "1" ]]; then
  echo "==> Public smoke test"
  "$ROOT_DIR/scripts/deploy/smoke-test.sh"
else
  echo "==> Skipping smoke test (SKIP_SMOKE=1)"
fi

echo "Deploy complete."
