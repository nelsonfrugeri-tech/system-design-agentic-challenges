.DEFAULT_GOAL := help
PROJECTS := agentic-bank/bank-mcp agentic-bank/observer-sdk

.PHONY: help langfuse check

help:
	@echo 'langfuse  Start the local Langfuse (http://localhost:3000); keys in infra/langfuse/.env'
	@echo 'check     Black, Ruff, strict mypy and offline tests of every project'

langfuse:
	bash infra/langfuse/start.sh

check:
	@set -e; for project in $(PROJECTS); do $(MAKE) -C "$$project" check; done
