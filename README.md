# System Design Agentic Challenges

Evals-driven system design challenges for AI agents. Each challenge ships what a
company would hand a new engineer: the business requirements with measurable
targets, a dataset of conversations, and the real systems the agent talks to. You
write the evals first, then the agent, and the evals decide when it is done.

| Challenge | The agent |
| --- | --- |
| [agentic-bank](agentic-bank/challenge/REQUIREMENTS.md) | A banking assistant that pays card bills and redeems investments, with confirmation and without ever moving money twice |

## Layout

```text
system-design-agentic-challenges/
├── infra/langfuse/          local Langfuse shared by every challenge
└── agentic-bank/
    ├── challenge/           REQUIREMENTS.md: rules, targets and contract
    ├── evals/datasets/      the conversations the agent must get right
    ├── bank-mcp/            the bank, served as MCP tools
    ├── observer-sdk/        puts the agent's steps in the Langfuse trace
    └── src/                 your agent
```

## Requirements

Python 3.12, [uv](https://docs.astral.sh/uv/), Make and Docker.

```sh
make langfuse    # http://localhost:3000; credentials in infra/langfuse/.env
make check       # the gates of every project
```

Each project owns its `pyproject.toml`, `uv.lock`, `.venv` and Makefile; run
`make -C <project> help` for its commands.
