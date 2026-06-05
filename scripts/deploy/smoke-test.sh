#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.vps.yml}"

cd "$ROOT_DIR"

if [[ ! -f .env ]]; then
  echo "error: .env not found in $ROOT_DIR" >&2
  exit 1
fi

# shellcheck disable=SC1091
set -a
source .env
set +a

BASE_URL="${SMOKE_BASE_URL:-$PUBLIC_BASE_URL}"

if [[ -z "$BASE_URL" ]]; then
  echo "error: set PUBLIC_BASE_URL in .env or SMOKE_BASE_URL for smoke tests" >&2
  exit 1
fi

echo "Smoke test: GET $BASE_URL/v1/health"
health_json="$(curl -fsS "$BASE_URL/v1/health")"
echo "$health_json" | grep -q '"status"' || {
  echo "error: /v1/health response missing status field" >&2
  exit 1
}

echo "Smoke test: GET $BASE_URL/v1/health/ready"
ready_json="$(curl -fsS "$BASE_URL/v1/health/ready")"
echo "$ready_json" | grep -q '"ready"' || {
  echo "error: /v1/health/ready response missing ready field" >&2
  exit 1
}

echo "Smoke test: GET $BASE_URL/v1/mosques?limit=1"
curl -fsS "$BASE_URL/v1/mosques?limit=1" >/dev/null

echo "All smoke checks passed."
