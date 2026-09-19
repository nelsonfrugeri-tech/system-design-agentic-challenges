# Aurora Bank MCP

O banco servido como tools MCP sobre streamable HTTP, em
`http://127.0.0.1:8001/mcp`. As regras ficam em `bank/core`; `bank/mcp` só as
expõe e registra cada chamada.

## Como rodar

```sh
make up                      # Docker: volta cada conta ao estado inicial e serve
make inspector               # leia as tools e chame-as em http://127.0.0.1:6274
make seed                    # volta todas as contas ao estado inicial, sem reiniciar
make seed ACCOUNT=acc-1005   # só essa conta (repita ids separados por espaço)
```

O `make mcp` serve o mesmo banco sem Docker. Como o container, ele roda o
`make seed` antes, então todo início volta cada conta ao seu estado inicial e
uma cópia nova do repositório não precisa de mais nada; o schema vem de
`bank/core/schema.sql`. O `make seed` continua funcionando sozinho, com o
banco no ar. O projeto do Docker é `agentic-challenges-bank`, na porta 8001.

## O estado

O banco é um arquivo SQLite, `$BANK_DATA_DIR/bank.db`. O padrão de
`BANK_DATA_DIR` é `agentic-bank/.data`, que está fora do Git; exporte essa
variável (ou passe para o `make`) para mudar o banco de lugar. O `make seed`,
o `make mcp` e o container (o `make up` monta a pasta em `/data`) usam esse
mesmo arquivo, e as evals precisam ler `$BANK_DATA_DIR/bank.db`, com o mesmo
padrão, para verem exatamente o que o banco gravou.

| Tabela | O que guarda |
| --- | --- |
| `accounts` | O saldo em conta de cada conta |
| `bills` | As faturas do cartão: `amount_cents` e `paid_cents` |
| `investments` | Os saldos investidos e o `daily_liquidity` |
| `operations` | Cada resgate e pagamento, com o `status` |
| `calls` | Cada chamada de tool, incluindo leituras e recusas, na ordem de `id` |

A tabela `calls` não tem coluna de turno. Para ligar chamadas e operações a um
turno, leia `MAX(calls.id)` e `MAX(operations.rowid)` antes do turno e leia de
novo depois, com um turno por vez em cada conta.

As contas são as fixtures de `../evals/datasets/conversations.json`: uma conta
por conversa, de `acc-1001` a `acc-1013`. O `make seed DATASET=<arquivo>`
carrega outro arquivo no mesmo formato, como um holdout.

## Quem é a conta

A conta nunca viaja num argumento de tool: ela vem do header `X-Account-Id`,
em toda requisição, do mesmo jeito que a autenticação identifica um cliente
num banco de verdade. Como argumento, o modelo poderia operar a conta de outra
pessoa.

## Leituras e transações

Toda tool declara as annotations padrão do MCP, então um cliente que descobre
as tools pelo `tools/list` distingue umas das outras sem ler texto:

| Tools | Annotations |
| --- | --- |
| `get_balance`, `list_bills`, `list_investments`, `list_operations` | `readOnlyHint: true` |
| `redeem_investment`, `pay_card_bill` | `readOnlyHint: false`, `destructiveHint: true`, `idempotentHint: false` |

O `idempotentHint: false` é proposital: chamar uma transação duas vezes move o
dinheiro duas vezes. Garantir o exactly-once é trabalho da solução, que é a
regra 3 do desafio.

As descrições repetem isso em palavras ("Read-only:" e "Transaction (moves
money, needs the customer's confirmation):"), para modelos que ignoram as
annotations.

## Exemplos de uso

Os exemplos ficam no `inputSchema`, como `examples` do JSON Schema, escritos
com o `Field(examples=[...])` do Pydantic:

```json
"bill_id": {
  "description": "Bill id from list_bills, e.g. bill-gold.",
  "examples": ["bill-gold", "bill-virtual"],
  "type": "string"
}
```

**Por que não um mecanismo nativo:** o SDK Python de MCP fixado aqui, o `mcp`
1.30.0, não tem nenhum. O `@server.tool()` aceita `title`, `annotations`,
`icons`, `meta` e `structured_output`, e nem
`mcp.types.Tool`/`ToolAnnotations` nem `mcp/server/fastmcp/tools/base.py`
mencionam exemplos — conferido no pacote instalado em 17/09/2026. O `examples`
do JSON Schema é a alternativa portátil: chega a qualquer cliente que leia o
schema, que é todo cliente MCP.

Vale revisitar isso se o SDK for atualizado e ganhar um campo próprio de
exemplos.

## Saídas

Toda tool declara um `outputSchema` e devolve conteúdo estruturado. O FastMCP
embrulha um retorno de lista em `{"result": [...]}`; um único modelo volta
como objeto. Os modelos tipados estão em `bank/core/operations.py`.

## Recusas

O banco recusa o que um banco de verdade recusaria. Uma recusa é um erro de
tool (`isError: true`) cujo único conteúdo é uma linha de texto, começando por
um código estável:

```text
Error executing tool <name>: <code>: <message>
Error executing tool pay_card_bill: insufficient_balance: insufficient balance
```

O prefixo vem do FastMCP, que embrulha toda exceção de tool; numa recusa não
há `structuredContent`. Trate a recusa pelo `<code>`, que vem logo depois do
nome da tool.

| Código | Quando |
| --- | --- |
| `insufficient_balance` | O saldo em conta não cobre o pagamento |
| `no_daily_liquidity` | O investimento não pode ser resgatado hoje |
| `amount_out_of_range` | Zero, negativo, ou mais do que resta na fatura ou no investimento |
| `unknown_bill`, `unknown_investment` | O id não existe nessa conta |
| `unknown_account` | O header `X-Account-Id` não corresponde a nenhuma conta |

Uma chamada recusada não muda nada e mesmo assim é registrada em `calls`.
