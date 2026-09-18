.DEFAULT_GOAL := help

.PHONY: help sync format format-check lint typecheck test check pre-commit seed mcp up down inspector

# SQLite file lives outside the repository. The evals read the same file.
DB ?= $(HOME)/root/memories/database/system-design-agentic-challenges/agentic-bank/bank.db
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
	@echo 'seed          Reset every customer to its fixture: make seed [DB=path] [DATASET=path]'
	@echo 'mcp           Serve the bank MCP on http://127.0.0.1:8001/mcp: make mcp [DB=path]'
	@echo 'up            Seed and serve the bank MCP in Docker (the same DB file)'
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
	uv run --locked python -m bank.core.seed --db "$(DB)" --dataset "$(DATASET)"

mcp:
	uv run --locked python -m bank.mcp.server --db "$(DB)"

up:
	@mkdir -p "$(dir $(DB))"
	DB_DIR="$(dir $(DB))" docker compose up -d --build

down:
	DB_DIR="$(dir $(DB))" docker compose down

inspector:
	npx -y @modelcontextprotocol/inspector@2.6.0 --config bank/mcp/inspector.json
