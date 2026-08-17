"""Read model da linha do tempo do contato.

Mescla DUAS fontes com contratos diferentes:

- **Persistida** — `facts`: os fatos narrativos (chegou, voltou, moveu, decidiu).
- **Derivada** — `quotes`, `charges` e `agenda_events`: os fatos financeiros e de compromisso,
  lidos na ORIGEM.

O financeiro e o compromisso não são copiados para `facts` de propósito. Guardar `amount_cents`
ou `starts_at` em segundo lugar criaria uma segunda versão da verdade — a forma exata do bug que
a Onda 0 do Epic 8 gastou uma onda inteira desfazendo. Ler da origem também traz de graça o
histórico RETROATIVO: contatos que já existiam mostram as cobranças e os compromissos de meses
atrás sem nenhuma migration de dados.

Só compromissos JÁ REALIZADOS entram aqui (`ends_at < agora`, excluído `cancelled`): o futuro
é a pergunta do bloco de Agenda, não da timeline do contato — duas telas, duas perguntas. E só
os que a Agenda narra com EXCLUSIVIDADE: `cobranca_receber`/`cobranca_pagar` ficam de fora
(`KINDS_FINANCEIROS_JA_NARRADOS`) porque a fonte `charges` já os conta como fato financeiro —
sem a exclusão, cada cobrança apareceria DUAS vezes (o dinheiro e um compromisso fantasma).

Fica fora de `service.py` porque é leitura cross-módulo (toca `receivables`, `quotes` e
`agenda`), com responsabilidade distinta das regras de escrita do CRM.
"""
from __future__ import annotations

from datetime import UTC, datetime, time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.facts import Fact
from app.modules.agenda.models import (
    KIND_COBRANCA_PAGAR,
    KIND_COBRANCA_RECEBER,
    STATUS_CANCELLED,
    AgendaEvent,
)
from app.modules.quotes.models import Quote
from app.modules.receivables.models import Charge

# Kinds financeiros: todo `cobranca_receber`/`cobranca_pagar` já é narrado pela fonte `charges`
# acima (título "Cobrança de R$ X — vence DD/MM/AAAA"). Desde a Task 2/3 da Onda 2, ESSES eventos
# de Agenda também carregam `client_id` (backfill da 0078 + escrita em `receivables/service.py`),
# então sem esta exclusão eles casariam de novo aqui e cada cobrança virava DOIS fatos na
# timeline — o dinheiro (fonte `charges`) e um "Compromisso: A receber: Fulano" fantasma que o
# dono nunca marcou. Achado da revisão final da onda: o financeiro já tem dono nesta tela; a
# Agenda entra só com o que ela EXCLUSIVAMENTE sabe (atendimento, reunião, audiência...).
KINDS_FINANCEIROS_JA_NARRADOS = {KIND_COBRANCA_RECEBER, KIND_COBRANCA_PAGAR}

# Teto POR FONTE. A resposta declara `truncated` quando qualquer fonte bate nele — a tela
# avisa em vez de fingir que aquilo é tudo.
LIMITE_POR_FONTE = 100


def _brl(cents: int) -> str:
    return f"R$ {cents / 100:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _instante(valor: object) -> datetime:
    """Normaliza para datetime AWARE em UTC.

    `charges.due_date` é `Date` (data de negócio) e `paid_at`/`created_at` são `timestamptz`.
    Ordenar os dois juntos exige um tipo só; a data vira meia-noite UTC, mesma convenção dos
    eventos all-day da Agenda.
    """
    if isinstance(valor, datetime):
        return valor if valor.tzinfo else valor.replace(tzinfo=UTC)
    return datetime.combine(valor, time.min, tzinfo=UTC)


def build(db: Session, *, client_id: str, limit: int = LIMITE_POR_FONTE) -> tuple[list[dict], bool]:
    """Devolve `(entradas_ordenadas, truncated)`. Mais recente primeiro."""
    truncated = False
    entradas: list[dict] = []

    eventos = list(
        db.scalars(
            select(Fact)
            .where(Fact.client_id == client_id)
            .order_by(Fact.occurred_at.desc(), Fact.id.desc())
            .limit(limit + 1)
        ).all()
    )
    if len(eventos) > limit:
        truncated = True
        eventos = eventos[:limit]
    for e in eventos:
        entradas.append({
            "id": e.id, "kind": e.kind, "title": e.title, "body": e.body,
            "actor": e.actor, "is_ai": e.is_ai, "at": _instante(e.occurred_at),
        })

    cobrancas = list(
        db.scalars(
            select(Charge)
            .where(Charge.client_id == client_id)
            .order_by(Charge.created_at.desc(), Charge.id.desc())
            .limit(limit + 1)
        ).all()
    )
    if len(cobrancas) > limit:
        truncated = True
        cobrancas = cobrancas[:limit]
    for c in cobrancas:
        if c.paid_at is not None:
            entradas.append({
                "id": f"charge:{c.id}:paid", "kind": "payment",
                "title": f"Pagamento recebido — {_brl(c.amount_cents)}",
                "body": c.description, "actor": "sistema", "is_ai": False,
                "at": _instante(c.paid_at),
            })
        entradas.append({
            "id": f"charge:{c.id}", "kind": "charge",
            "title": f"Cobrança de {_brl(c.amount_cents)} — vence {c.due_date:%d/%m/%Y}",
            "body": c.description, "actor": "sistema", "is_ai": False,
            "at": _instante(c.created_at),
        })

    orcamentos = list(
        db.scalars(
            select(Quote)
            .where(Quote.client_id == client_id)
            .order_by(Quote.created_at.desc(), Quote.id.desc())
            .limit(limit + 1)
        ).all()
    )
    if len(orcamentos) > limit:
        truncated = True
        orcamentos = orcamentos[:limit]
    for q in orcamentos:
        entradas.append({
            "id": f"quote:{q.id}", "kind": "quote",
            "title": f"Orçamento “{q.title}” — {_brl(q.total_cents)} ({q.status})",
            "body": q.notes, "actor": "sistema", "is_ai": False,
            "at": _instante(q.created_at),
        })

    agora = datetime.now(UTC)
    compromissos = list(
        db.scalars(
            select(AgendaEvent)
            .where(
                AgendaEvent.client_id == client_id,
                AgendaEvent.ends_at < agora,
                AgendaEvent.status != STATUS_CANCELLED,
                # Ver `KINDS_FINANCEIROS_JA_NARRADOS` no topo do arquivo — a fonte `charges`
                # acima já é dona de contar cobrança nesta timeline.
                AgendaEvent.kind.not_in(KINDS_FINANCEIROS_JA_NARRADOS),
            )
            .order_by(AgendaEvent.starts_at.desc(), AgendaEvent.id.desc())
            .limit(limit + 1)
        ).all()
    )
    if len(compromissos) > limit:
        truncated = True
        compromissos = compromissos[:limit]
    for ev in compromissos:
        entradas.append({
            "id": f"agenda:{ev.id}", "kind": "agenda",
            "title": f"Compromisso: {ev.title}",
            "body": ev.description, "actor": "sistema", "is_ai": False,
            "at": _instante(ev.starts_at),
        })

    entradas.sort(key=lambda e: e["at"], reverse=True)
    if len(entradas) > limit:
        truncated = True
        entradas = entradas[:limit]
    return entradas, truncated
