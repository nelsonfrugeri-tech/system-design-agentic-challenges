.DEFAULT_GOAL := help

.PHONY: help sync env format format-check lint typecheck test check pre-commit eval stub

# The harness reads $(BANK_DATA_DIR)/bank.db, the same file bank-mcp serves.
BANK_DATA_DIR ?= $(abspath ../.data)
BANK_URL ?= http://127.0.0.1:8001/mcp
SOLUTION_URL ?= http://127.0.0.1:8000
DATASET ?= datasets/conversations.json
name ?= dev
type ?= default
path ?=
dataset ?= $(DATASET)
mode ?= oracle
port ?= 8000
# Written by `make langfuse` at the repository root; outside Git.
LANGFUSE_ENV ?= $(abspath ../../infra/langfuse/.env)

export BANK_DATA_DIR BANK_URL

help:
	@echo 'sync          Install locked dependencies with uv'
	@echo 'env           Write .env with the local Langfuse keys, from infra/langfuse/.env'
	@echo 'format        Format Python with Black'
	@echo 'format-check  Check Black formatting'
	@echo 'lint          Run Ruff'
	@echo 'typecheck     Run strict mypy'
	@echo 'test          Unit and local integration tests (spawn bank-mcp and the stub)'
	@echo 'check         format-check, lint, typecheck, test'
	@echo 'pre-commit    format, then check'
	@echo 'eval          Run: make eval name=<name> [type=default|stub] or type=holdout path=/absolute/file'
	@echo 'stub          Serve a fake assistant: make stub mode=oracle|refuse|pay [port=8000]'

sync:
	uv sync --locked

env:
	@test -f "$(LANGFUSE_ENV)" || { echo "$(LANGFUSE_ENV) not found: run make langfuse at the repository root" >&2; exit 1; }
	@grep -E '^LANGFUSE_(HOST|PUBLIC_KEY|SECRET_KEY)=' "$(LANGFUSE_ENV)" > .env
	@echo "wrote .env: LANGFUSE_HOST, LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY"

format:
	uv run --locked black harness baselines tests

format-check:
	uv run --locked black --check harness baselines tests

lint:
	uv run --locked ruff check harness baselines tests

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

eval:
	@set -a; if [ -f .env ]; then . ./.env; fi; set +a; \
	uv run --locked python -m harness.run --name "$(name)" --type "$(type)" $(if $(path),--path "$(path)",) --solution-url "$(SOLUTION_URL)"; \
	code=$$?; echo "harness exit $$code (0 approved, 1 a gate failed, 2 preflight, 3 harness error)"; exit $$code

stub:
	uv run --locked python -m baselines.stub --mode "$(mode)" --port "$(port)" --bank-url "$(BANK_URL)" --dataset "$(dataset)"
