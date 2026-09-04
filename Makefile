# Developer entrypoints. Uses the local virtualenv if VENV is set.
PY ?= python
PIP ?= $(PY) -m pip

.PHONY: help install dev lint fmt typecheck test test-unit test-sec cov \
        migrate revision run-api run-bot run-worker up down logs clean

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install: ## Install runtime + dev dependencies (editable)
	$(PIP) install -e ".[dev]"

lint: ## ruff lint
	ruff check .

fmt: ## ruff format
	ruff format .

typecheck: ## mypy
	mypy security database apps

test: ## full test suite
	$(PY) -m pytest

test-unit: ## unit tests only
	$(PY) -m pytest -m unit

test-sec: ## security regression tests
	$(PY) -m pytest -m security

cov: ## test suite with coverage report
	$(PY) -m pytest --cov=. --cov-report=term-missing --cov-report=xml

migrate: ## apply DB migrations
	alembic upgrade head

revision: ## autogenerate a migration: make revision m="add x"
	alembic revision --autogenerate -m "$(m)"

run-api: ## run the API locally
	uvicorn apps.api.main:app --reload --port $${API_PORT:-8000}

run-bot: ## run the Telegram bot locally
	$(PY) -m apps.bot

run-worker: ## run a background worker locally
	$(PY) -m workers

up: ## start the full docker stack
	docker compose up --build -d

down: ## stop the docker stack
	docker compose down

logs: ## tail docker stack logs
	docker compose logs -f --tail=100

clean: ## remove caches and build artifacts
	rm -rf .pytest_cache .ruff_cache .mypy_cache htmlcov .coverage coverage.xml
	find . -name __pycache__ -type d -exec rm -rf {} +
