FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked --no-dev --no-install-project

COPY bank ./bank

EXPOSE 8001
# Every start resets the bank to the dataset fixtures, then serves the MCP.
# compose.yaml mounts the dataset, so editing it needs a restart, not a rebuild.
CMD ["sh", "-c", "uv run --locked --no-dev python -m bank.core.seed --db /data/bank.db --dataset /datasets/conversations.json && uv run --locked --no-dev python -m bank.mcp.server --db /data/bank.db --host 0.0.0.0"]
