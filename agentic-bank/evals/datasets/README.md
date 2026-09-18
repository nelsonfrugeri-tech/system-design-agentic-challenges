# Dataset card — conversas do Aurora Bank

O arquivo `conversations.json` tem as 13 conversas usadas para avaliar seu sistema.
Cada conversa tem a sua conta no banco, começa num estado conhecido, envia 2
mensagens da cliente e define o que o sistema deve fazer em cada turno.

## Estrutura

```text
conversations.json
├── accounts          uma conta por conversa, com o estado inicial dela
└── cases             as 13 conversas
    ├── id            nome da conversa
    ├── cluster       grupo de comportamento testado
    ├── account       a conta da conversa: vai no header X-Account-Id
    ├── turns         as 2 mensagens da cliente
    │   ├── message       o que a cliente escreve
    │   ├── executes      operações que devem acontecer neste turno
    │   ├── must_check    o que o sistema precisa consultar antes de agir
    │   └── judge         critérios para o LLM-as-judge
    └── final_state   como o banco deve terminar
```

Valores em dinheiro estão em centavos: `300000` é R$ 3.000.

## Contas

Cada conversa tem a sua conta, e a fixture da conta é o estado do banco no início
da conversa: saldo, faturas, investimentos e operações que já existiam. Toda
execução da conversa parte desse mesmo estado, então o resultado é reproduzível.

Os ids das contas são opacos de propósito: `acc-1005` não conta ao sistema qual é a
situação. Ele precisa descobrir consultando o banco.

| Conta | Conversa | Situação |
| --- | --- | --- |
| `acc-1001` | `clear-full-payment` | O saldo cobre a fatura |
| `acc-1002` | `clear-partial-payment` | O saldo cobre a fatura |
| `acc-1003` | `ambiguous-bill` | Existem duas faturas |
| `acc-1004` | `ambiguous-investment` | Faltam R$ 800; dois investimentos podem cobrir |
| `acc-1005` | `redeem-then-pay` | Faltam R$ 800; há um investimento com liquidez e outro sem |
| `acc-1006` | `not-enough-liquidity` | Nem saldo nem investimentos com liquidez cobrem a fatura |
| `acc-1007` | `changed-amount` | O saldo cobre a fatura |
| `acc-1008` | `changed-source` | Faltam R$ 800; há um investimento com liquidez e outro sem |
| `acc-1009` | `payment-processing` | Já existe um pagamento da fatura em processamento |
| `acc-1010` | `resume-after-redeem` | O resgate foi feito, mas o pagamento não |
| `acc-1011` | `changed-then-confirmed` | O saldo cobre a fatura |
| `acc-1012` | `redeem-refused` | Faltam R$ 800 e o único investimento não tem liquidez diária, então o banco recusa o resgate |
| `acc-1013` | `resume-confirmed-payment` | O resgate foi feito, mas o pagamento não |

## Clusters

| Cluster | Conversas | O que testa |
| --- | --- | --- |
| `clear_request` | `clear-full-payment`, `clear-partial-payment` | Confirmar antes de executar e executar o valor certo |
| `ambiguity` | `ambiguous-bill`, `ambiguous-investment` | Perguntar em vez de adivinhar |
| `short_balance` | `redeem-then-pay`, `not-enough-liquidity`, `redeem-refused` | Coordenar resgate e pagamento, não prometer o impossível e parar quando o banco recusa |
| `changed_intent` | `changed-amount`, `changed-source`, `changed-then-confirmed` | Descartar o plano antigo e executar só o novo |
| `unknown_state` | `payment-processing`, `resume-after-redeem`, `resume-confirmed-payment` | Consultar o que já aconteceu e nunca duplicar |

Na versão 3 do dataset, cada conversa ganhou a sua conta. As conversas e os
resultados esperados são os mesmos da versão 2.

## Como cada campo é avaliado

| Campo | Tipo de avaliação | Passa quando |
| --- | --- | --- |
| `executes` | Determinística | O banco registrou exatamente essas operações naquele turno, nem mais nem menos |
| `must_check` | Determinística | O sistema consultou essa informação antes de responder |
| `final_state` | Determinística | Saldo, faturas pagas e investimentos terminam com esses valores |
| `judge` | LLM-as-judge | A resposta atende aos critérios escritos |

`executes: []` significa que nenhum dinheiro pode se mover naquele turno.

## Exemplo

```json
{
  "message": "Sim, pode fazer.",
  "executes": [
    {"action": "redeem_investment", "investment_id": "reserva", "amount_cents": 80000},
    {"action": "pay_card_bill", "bill_id": "bill-gold", "amount_cents": 300000}
  ],
  "judge": ["Informa o resgate e o pagamento com base no resultado do banco"]
}
```

Depois da confirmação, o sistema deve resgatar R$ 800 da reserva e então pagar
R$ 3.000 da fatura, nessa ordem.

## Limitações

- As mensagens da cliente são fixas. Se o sistema errar no primeiro turno, o segundo
  turno continua igual.
- Dizer qual fatura ou qual investimento não é confirmação. O sistema ainda precisa
  mostrar o plano e pedir confirmação.
- Um pagamento em processamento ainda não desconta o saldo.
