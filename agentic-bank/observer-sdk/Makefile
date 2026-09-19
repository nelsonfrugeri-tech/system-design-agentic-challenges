.DEFAULT_GOAL := help

.PHONY: help sync format format-check lint typecheck test check pre-commit

help:
	@echo 'sync          Install locked dependencies with uv'
	@echo 'format        Format Python with Black'
	@echo 'format-check  Check Black formatting'
	@echo 'lint          Run Ruff'
	@echo 'typecheck     Run strict mypy'
	@echo 'test          Run offline tests'
	@echo 'check         format-check, lint, typecheck, test'
	@echo 'pre-commit    format, then check'

sync:
	uv sync --locked

format:
	uv run --locked black observer_sdk tests

format-check:
	uv run --locked black --check observer_sdk tests

lint:
	uv run --locked ruff check observer_sdk tests

typecheck:
	uv run --locked mypy

test:
	uv run --locked pytest -q

check:
	$(MAKE) format-check
	$(MAKE) lint
	$(MAKE) typecheck
	$(MAKE) test

pre-commit:
	$(MAKE) format
	$(MAKE) check

