#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

cd "$ROOT_DIR"

if [[ ! -f .env ]]; then
  echo "error: .env not found in $ROOT_DIR" >&2
  exit 1
fi

# Read only PUBLIC_BASE_URL from .env. Avoid `source .env`: values like
# APP_NAME="UK Jamaat Directory" contain spaces/parens and break shell parsing.
PUBLIC_BASE_URL="$(grep -E '^PUBLIC_BASE_URL=' .env | tail -n1 | cut -d= -f2- || true)"

BASE_URL="${SMOKE_BASE_URL:-${PUBLIC_BASE_URL:-}}"

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
echo "$ready_json" | grep -q '"status":"ok"' || {
  echo "error: /v1/health/ready response missing status ok" >&2
  exit 1
}
echo "$ready_json" | grep -q '"database":"ok"' || {
  echo "error: /v1/health/ready response missing database ok" >&2
  exit 1
}

echo "Smoke test: GET $BASE_URL/v1/mosques?limit=1"
curl -fsS "$BASE_URL/v1/mosques?limit=1" >/dev/null

echo "Smoke test: GET $BASE_URL/v1/openapi.json"
openapi_json="$(curl -fsS "$BASE_URL/v1/openapi.json")"
echo "$openapi_json" | grep -q '"openapi"' || {
  echo "error: /v1/openapi.json missing openapi field" >&2
  exit 1
}

echo "Smoke test: GET $BASE_URL/ (landing page)"
curl -fsS "$BASE_URL/" | grep -qi '<html' || {
  echo "error: landing page did not return HTML" >&2
  exit 1
}

echo "Smoke test: security headers on $BASE_URL/"
headers="$(curl -fsSI "$BASE_URL/")"
echo "$headers" | grep -qi 'strict-transport-security' || {
  echo "error: HSTS header missing on landing page" >&2
  exit 1
}
echo "$headers" | grep -qi 'x-content-type-options' || {
  echo "error: X-Content-Type-Options header missing on landing page" >&2
  exit 1
}

echo "All smoke checks passed."
