"""A derivação do estado a partir da DATA — **um lugar só, para os dois lados do dinheiro**.

> *"O estado é **derivado da data, nunca escolhido**"* (design da Onda 2 §4.2.4, normativo).

Existe porque a mesma regra vale para **saída** (`payables`, Story 8.14) e para **entrada**
(`receivables`, Story 8.15): dinheiro cuja data de caixa ainda não chegou está **agendado**;
dinheiro cuja data já chegou (ou passou) está **liquidado**. Uma frase, dois módulos.

⚠️ **Mora em `app/core/`, é PÚBLICA, e as duas coisas são decisão registrada** (correção do @po na
Story 8.14, Task 1):

- **pública**, porque a Story 8.15 a importa. Um símbolo com `_` importado de fora é exatamente a
  costura frouxa que produz duas cópias no primeiro ajuste — foi assim que `_not_investment_yield()`
  nasceu duas vezes entre dois @sm;
- **neutra** (fora de `payables/`), porque fazer `receivables` importar `payables` só por causa
  deste predicado seria acoplamento gratuito entre dois módulos de negócio que, por design, não se
  conhecem.

⚠️ **Os nomes dos estados são PARÂMETRO, não constante daqui.** `app/core` não conhece o vocabulário
de `payables` nem o de `receivables` — e não deve passar a conhecer: seria a mesma inversão de
dependência que a Regra dos Planos proíbe entre `bank` e os módulos de negócio. Quem sabe como se
chama o estado é quem tem a coluna.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

__all__ = ["janela_de_caixa", "status_por_data"]


def status_por_data(
    data: date, today: date, *, status_agendado: str, status_pago: str
) -> str:
    """*"Este dinheiro já saiu/entrou, ou ainda vai?"* — a resposta é a DATA, nunca uma escolha.

    | `data` | resultado |
    |---|---|
    | `> today` | `status_agendado` |
    | `== today` ou `< today` | `status_pago` |

    **A borda é `>`, estrita, e ela é o ponto todo.** `data == today` é liquidação **hoje**, não
    agendamento: o movimento bancário correspondente já tem `posted_at <= hoje` e portanto já entra
    em `active_balance_total(until=today)`. Tratar hoje como agendado faria o mesmo dinheiro ser
    contado duas vezes na Projeção de Caixa (Story 8.14 AC6) — o falso positivo do mesmo tamanho do
    falso negativo que a Onda 0 removeu.

    **PURA e sem relógio:** `today` é parâmetro obrigatório. Uma função que lesse `datetime.now()`
    por dentro seria intestável e traria um segundo conceito de "hoje" para dentro do repositório —
    o `CLAUDE.md` §6.1 já tem a dívida de fuso por tenant registrada, e ela não se resolve
    espalhando relógios.

    Args:
        data: a data de **caixa** informada (`paid_on` em `payables`, `received_on` em
            `receivables`). Data de calendário, jamais `datetime` — a lição de fuso do
            `CLAUDE.md` §6.0 (comparar por data de calendário, nunca por horário local).
        today: a âncora de "hoje" de quem chama, em UTC (a mesma de `payables.summary` e de
            `projection.cash_projection`).
        status_agendado: como o módulo chamador chama o estado "ainda vai acontecer".
        status_pago: como o módulo chamador chama o estado "já aconteceu".
    """
    return status_agendado if data > today else status_pago


def janela_de_caixa(start: date, end: date) -> tuple[datetime, datetime]:
    """`[start, end]` (datas de calendário, **inclusivas**) → `[de, ate)` em TIMESTAMP UTC.

    Serve para filtrar `paid_at` — que é `DateTime`, gravado na **meia-noite UTC** da data de caixa
    por `payables.apply_paid` e `receivables.settle_off_rail` — por uma janela de **datas**.

    **Por que limites de timestamp e não `paid_at::date`:** `::date` não existe no SQLite da suíte,
    e o repositório já resolvia isso assim em `paid_before`, `summary` e `probe_pagamento_duplicado`
    (Story 8.16 só parou de copiar a expressão pela quarta vez). **O teto é EXCLUSIVO** — meia-noite
    do dia seguinte a `end` — justamente para que `end` continue inclusivo mesmo se um dia houver
    hora diferente de zero no campo; um `<= meia-noite de end` perderia o dia inteiro de `end`.

    PURA, sem relógio e sem banco: recebe as duas pontas e devolve as duas pontas.
    """
    return (
        datetime.combine(start, time.min, tzinfo=UTC),
        datetime.combine(end + timedelta(days=1), time.min, tzinfo=UTC),
    )
