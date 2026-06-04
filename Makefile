.PHONY: install lint format test test-postgres test-postgres-preflight migrate dev compose-up compose-down export-contracts

VENV := .venv
BIN := $(VENV)/bin
RUFF_CACHE_DIR ?= /tmp/ruff-cache-uk-jamaat-directory
PYTEST_CACHE_DIR ?= /tmp/pytest-cache-uk-jamaat-directory
export RUFF_CACHE_DIR
export PYTEST_CACHE_DIR

# Host port for Directory PostGIS (54324 avoids common 5432/5433 dev stacks).
POSTGRES_HOST_PORT ?= 54324
export DATABASE_URL ?= postgresql+asyncpg://directory:directory@localhost:$(POSTGRES_HOST_PORT)/directory
export TEST_DATABASE_URL ?= postgresql+asyncpg://directory:directory@localhost:$(POSTGRES_HOST_PORT)/directory_test

install:
	python3.12 -m venv $(VENV)
	$(BIN)/python -m pip install -U pip
	$(BIN)/pip install -e ".[dev]"

lint:
	$(BIN)/ruff check src tests alembic

format:
	$(BIN)/ruff format src tests alembic

test:
	$(BIN)/pytest -o cache_dir=$(PYTEST_CACHE_DIR)

test-postgres-preflight:
	@test -f .env || cp .env.example .env
	@echo "Checking host port $(POSTGRES_HOST_PORT)..."
	@docker ps --format '{{.Names}} {{.Ports}}' | grep $(POSTGRES_HOST_PORT) || true
	@ss -ltnp | grep ':$(POSTGRES_HOST_PORT)' || true
	docker compose up postgres -d
	@docker compose ps postgres
	@docker inspect "$$(docker compose ps -q postgres)" --format '{{json .NetworkSettings.Ports}}'
	docker compose exec -T postgres psql -U directory -d directory \
		-c "SELECT 1 FROM pg_database WHERE datname = 'directory_test'" \
		| grep -q 1 || \
	docker compose exec -T postgres psql -U directory -d directory \
		-c "CREATE DATABASE directory_test;"
	PYTHONPATH=src $(BIN)/python scripts/postgres_preflight.py

test-postgres: test-postgres-preflight
	UK_JAMAAT_TEST_POSTGRES=1 $(BIN)/pytest -o cache_dir=$(PYTEST_CACHE_DIR)

migrate:
	$(BIN)/alembic upgrade head

dev:
	$(BIN)/uvicorn uk_jamaat_directory.main:app --reload --app-dir src

compose-up:
	docker compose up --build

compose-down:
	docker compose down

export-contracts:
	$(BIN)/uk-jamaat-directory export-contracts
