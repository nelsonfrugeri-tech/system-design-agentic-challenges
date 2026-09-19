# Aurora Bank MCP

The bank served as MCP tools over streamable HTTP, on
`http://127.0.0.1:8001/mcp`. `bank/core` holds the rules; `bank/mcp` only
exposes them and records every call.

## Run

```sh
make up                      # Docker: reset every account to its fixture, then serve
make inspector               # read the tools and call them at http://127.0.0.1:6274
make seed                    # reset every account again, without restarting
make seed ACCOUNT=acc-1005   # reset only that account (repeat ids with spaces)
```

`make mcp` serves the same bank without Docker. The Docker project is
`agentic-challenges-bank`, on port 8001.

## State

The bank is one SQLite file, `agentic-bank/.data/bank.db`, gitignored.
`DATA_DIR=<dir>` moves it for every target (`seed`, `mcp`, `up`, `down`); the
file name is always `bank.db`, so Docker and the host use the same file and the
evals read exactly what the bank wrote.

| Table | What it holds |
| --- | --- |
| `accounts` | Checking balance per account |
| `bills` | Card bills: `amount_cents` and `paid_cents` |
| `investments` | Investment balances and `daily_liquidity` |
| `operations` | Every redemption and payment, with its `status` |
| `calls` | Every MCP tool call, reads and refusals included, in `id` order |

`calls` has no turn column. To attribute calls and operations to one turn,
read `MAX(calls.id)` and `MAX(operations.rowid)` before the turn and read
again after it, with one turn in flight per account.

The accounts are the fixtures of `../evals/datasets/conversations.json`: one
account per case, `acc-1001` to `acc-1013`. `make seed DATASET=<file>` loads
another file with the same shape, such as a holdout.

## Who the account is

The account never travels in a tool argument: it comes from the `X-Account-Id`
header on every request, the way authentication identifies a customer in a real
bank. A tool argument would let the model operate somebody else's account.

## Reads and transactions

Every tool declares the standard MCP hints, so a client that discovers the
tools through `tools/list` can tell them apart without reading prose:

| Tools | Annotations |
| --- | --- |
| `get_balance`, `list_bills`, `list_investments`, `list_operations` | `readOnlyHint: true` |
| `redeem_investment`, `pay_card_bill` | `readOnlyHint: false`, `destructiveHint: true`, `idempotentHint: false` |

`idempotentHint: false` is deliberate: calling a transaction twice moves money
twice. Guaranteeing exactly-once is the candidate's job, which is rule 3 of the
challenge.

The descriptions repeat it in words ("Read-only:" and "Transaction (moves
money, needs the customer's confirmation):") for models that ignore
annotations.

## Examples of use

The examples live in the `inputSchema` as JSON Schema `examples`, written with
Pydantic's `Field(examples=[...])`:

```json
"bill_id": {
  "description": "Bill id from list_bills, e.g. bill-gold.",
  "examples": ["bill-gold", "bill-virtual"],
  "type": "string"
}
```

**Why not a native mechanism:** the MCP Python SDK pinned here, `mcp` 1.30.0,
has none. `@server.tool()` accepts `title`, `annotations`, `icons`, `meta` and
`structured_output`, and neither `mcp.types.Tool`/`ToolAnnotations` nor
`mcp/server/fastmcp/tools/base.py` mentions examples — checked in the installed
package on 2026-09-17. JSON Schema `examples` is the portable alternative: it
reaches any client that reads the schema, which is every MCP client.

Revisit this if the SDK is upgraded and gains a first-class examples field.

## Outputs

Every tool declares an `outputSchema` and returns structured content. FastMCP
wraps a list return in `{"result": [...]}`; a single model is returned as its
own object. The typed models are in `bank/core/operations.py`.

## Refusals

The bank refuses what a real bank would refuse. A refusal is a tool error
(`isError: true`) whose only content is one text line, led by a stable code:

```text
Error executing tool <name>: <code>: <message>
Error executing tool pay_card_bill: insufficient_balance: insufficient balance
```

The prefix comes from FastMCP, which wraps every tool exception; there is no
`structuredContent` on a refusal. Branch on the `<code>` after the tool name.

| Code | When |
| --- | --- |
| `insufficient_balance` | The checking balance does not cover the payment |
| `no_daily_liquidity` | The investment cannot be redeemed today |
| `amount_out_of_range` | Zero, negative, or more than the bill or investment holds |
| `unknown_bill`, `unknown_investment` | The id does not exist in this account |
| `unknown_account` | The `X-Account-Id` header names no account |

A refused call changes nothing and is still recorded in `calls`.
