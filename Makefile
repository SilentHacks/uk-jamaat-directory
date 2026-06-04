.PHONY: install lint format test test-postgres migrate dev compose-up compose-down

VENV := .venv
BIN := $(VENV)/bin
RUFF_CACHE_DIR ?= /tmp/ruff-cache-uk-jamaat-directory
PYTEST_CACHE_DIR ?= /tmp/pytest-cache-uk-jamaat-directory
export RUFF_CACHE_DIR
export PYTEST_CACHE_DIR

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

test-postgres:
	UK_JAMAAT_TEST_POSTGRES=1 $(BIN)/pytest -o cache_dir=$(PYTEST_CACHE_DIR)

migrate:
	$(BIN)/alembic upgrade head

dev:
	$(BIN)/uvicorn uk_jamaat_directory.main:app --reload --app-dir src

compose-up:
	docker compose up --build

compose-down:
	docker compose down
