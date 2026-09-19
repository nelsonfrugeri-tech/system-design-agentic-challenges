.DEFAULT_GOAL := help

.PHONY: help sync format format-check lint typecheck test check pre-commit seed mcp up down inspector

# The bank is $(BANK_DATA_DIR)/bank.db for seed, mcp and the container, and the
# evals read the same file. The default agentic-bank/.data is gitignored;
# export BANK_DATA_DIR (or pass it to make) to move it.
BANK_DATA_DIR ?= $(abspath ../.data)
# Empty resets every account; ACCOUNT="acc-1005 acc-1006" resets only those.
ACCOUNT ?=
DATASET ?= ../evals/datasets/conversations.json

help:
	@echo 'sync          Install locked dependencies with uv'
	@echo 'format        Format Python with Black'
	@echo 'format-check  Check Black formatting'
	@echo 'lint          Run Ruff'
	@echo 'typecheck     Run strict mypy'
	@echo 'test          Run offline tests'
	@echo 'check         format-check, lint, typecheck, test'
	@echo 'pre-commit    format, then check'
	@echo 'seed          Reset accounts to their fixtures: make seed [ACCOUNT=acc-1005] [DATASET=path]'
	@echo 'mcp           Seed, then serve the bank MCP on http://127.0.0.1:8001/mcp: make mcp'
	@echo 'up            Seed and serve the bank MCP in Docker (the same $$BANK_DATA_DIR/bank.db)'
	@echo 'down          Stop the Docker bank MCP'
	@echo 'inspector     Browse and call the tools in MCP Inspector (http://127.0.0.1:6274)'

sync:
	uv sync --locked

format:
	uv run --locked black bank tests

format-check:
	uv run --locked black --check bank tests

lint:
	uv run --locked ruff check bank tests

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

seed:
	uv run --locked python -m bank.core.seed --db "$(BANK_DATA_DIR)/bank.db" --dataset "$(DATASET)" $(foreach account,$(ACCOUNT),--account $(account))

# Like the container: every start resets the bank, so a fresh checkout works.
mcp: seed
	uv run --locked python -m bank.mcp.server --db "$(BANK_DATA_DIR)/bank.db"

up:
	@mkdir -p "$(BANK_DATA_DIR)"
	BANK_DATA_DIR="$(abspath $(BANK_DATA_DIR))" docker compose up -d --build

down:
	BANK_DATA_DIR="$(abspath $(BANK_DATA_DIR))" docker compose down

inspector:
	npx -y @modelcontextprotocol/inspector@2.6.0 --config bank/mcp/inspector.json
