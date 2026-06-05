#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SKIP_BACKUP="${SKIP_BACKUP:-0}"
SKIP_MIGRATE="${SKIP_MIGRATE:-0}"
SKIP_SMOKE="${SKIP_SMOKE:-0}"

cd "$ROOT_DIR"

if [[ ! -f .env ]]; then
  echo "error: .env not found in $ROOT_DIR" >&2
  echo "Copy .env.example to .env and configure secrets." >&2
  exit 1
fi

eval "$("$ROOT_DIR/scripts/deploy/compose-args.sh")"

if [[ "$SKIP_BACKUP" == "1" || "$SKIP_MIGRATE" == "1" || "$SKIP_SMOKE" == "1" ]]; then
  echo "WARNING: break-glass deploy skips enabled — SKIP_BACKUP=$SKIP_BACKUP SKIP_MIGRATE=$SKIP_MIGRATE SKIP_SMOKE=$SKIP_SMOKE" >&2
fi

echo "==> Deploy checklist: pull, backup, build, migrate, restart, smoke test"
echo "    compose: ${COMPOSE_ARGS[*]}"

echo "==> Pull latest source (if using git on the server)"
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  git pull --ff-only
else
  echo "    (not a git checkout — skipping pull)"
fi

echo "==> Ensure data services are running"
docker compose "${COMPOSE_ARGS[@]}" up -d postgres redis minio

echo "==> Stop application writers before backup/migrate"
docker compose "${COMPOSE_ARGS[@]}" stop api worker beat 2>/dev/null || true

if [[ "$SKIP_BACKUP" != "1" ]]; then
  echo "==> Pre-deploy Postgres backup"
  "$ROOT_DIR/scripts/deploy/backup-postgres.sh"
else
  echo "==> Skipping backup (SKIP_BACKUP=1)"
fi

build_services=(api worker beat)
if ! docker compose "${COMPOSE_ARGS[@]}" config 2>/dev/null | grep -A12 '^  caddy:' | grep -q 'profiles:'; then
  build_services+=(caddy)
fi

echo "==> Build application images"
docker compose "${COMPOSE_ARGS[@]}" build "${build_services[@]}"

if [[ "$SKIP_MIGRATE" != "1" ]]; then
  echo "==> Apply database migrations"
  "$ROOT_DIR/scripts/deploy/migrate.sh"
else
  echo "==> Skipping migrations (SKIP_MIGRATE=1)"
fi

echo "==> Start application services"
docker compose "${COMPOSE_ARGS[@]}" up -d api worker beat
if ! docker compose "${COMPOSE_ARGS[@]}" config 2>/dev/null | grep -A12 '^  caddy:' | grep -q 'profiles:'; then
  docker compose "${COMPOSE_ARGS[@]}" up -d caddy
else
  echo "==> Skipping bundled caddy (profiled — use host reverse proxy)"
  docker compose "${COMPOSE_ARGS[@]}" stop caddy 2>/dev/null || true
fi

echo "==> Wait for API health"
health_ok=0
for _ in $(seq 1 30); do
  if docker compose "${COMPOSE_ARGS[@]}" exec -T api curl -fsS http://localhost:8000/v1/health >/dev/null 2>&1; then
    health_ok=1
    break
  fi
  sleep 2
done
if [[ "$health_ok" != "1" ]]; then
  echo "error: API did not become healthy within 60s" >&2
  exit 1
fi

if [[ "$SKIP_SMOKE" != "1" ]]; then
  echo "==> Public smoke test"
  "$ROOT_DIR/scripts/deploy/smoke-test.sh"
else
  echo "==> Skipping smoke test (SKIP_SMOKE=1)"
fi

echo "Deploy complete."
