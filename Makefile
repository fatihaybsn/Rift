PYTHON ?= python3

.PHONY: help install dev test lint format check clean

help:
	@echo "Available targets:"
	@echo "  install   Install project and dev dependencies"
	@echo "  dev       Run local development server"
	@echo "  test      Run tests"
	@echo "  lint      Run lint checks"
	@echo "  format    Format code"
	@echo "  check     Run lint + test"
	@echo "  clean     Remove caches"

install:
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -e ".[dev]"

dev:
	uvicorn app.main:app --reload

test:
	pytest -q

lint:
	ruff check .

format:
	ruff format .

check: lint test

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -type d -name ".ruff_cache" -exec rm -rf {} +