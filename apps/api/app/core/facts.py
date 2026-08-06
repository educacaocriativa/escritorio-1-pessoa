"""O Registro de Fatos — a memória narrativa do negócio.

Espelha o formato de `core/audit.py` (modelo + função de gravação no mesmo módulo), mas com
propósito distinto: `audit_entries` é trilha TÉCNICA ("quem mutou o quê"), `facts` é NARRATIVA
("o que aconteceu"). A trilha responde auditoria; o fato responde ao dono.

Duas invariantes que valem para toda linha:

1. **Texto congelado.** `title` e `body` são texto, não referência. Um fato gravado hoje diz
   "Movido de Em contato → Proposta" e continua dizendo isso depois de a coluna ser renomeada.
   Evidência não se reescreve sozinha — mesmo princípio de `bank_transactions.raw_description`.

2. **O fato não guarda dinheiro.** O valor é lido de `charges`/`bank_transactions` na hora de
   compor, nunca copiado para cá. Copiar criaria uma segunda versão da verdade sobre dinheiro —
   a forma exata do bug que a Onda 0 do Epic 8 gastou uma onda inteira desfazendo. A guarda
   abaixo torna isso mecânico em vez de disciplina.
"""
from __future__ import annotations

import re
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.db.base import Base, TenantMixin, TimestampMixin, _uuid

# --- Taxonomia -------------------------------------------------------------------------
# Convenção: `<módulo>.<entidade>.<verbo-no-passado>`. Registro único e greppável — trinta
# módulos emitindo string solta produzem `payment_received` e `payment.received` convivendo
# em seis meses.
#
# ⚠️ O prefixo é o vocabulário de `User.allowed_modules` (o que o dono vê na tela de
# permissões), NÃO o nome da pasta do módulo: `quotes` e `pages` emitem sob `comercial`.

CRM_LEAD_CRIADO = "crm.lead.criado"
CRM_LEAD_RETORNOU = "crm.lead.retornou"
CRM_ETAPA_MOVIDA = "crm.etapa.movida"
CRM_LEAD_REABERTO = "crm.lead.reaberto"
CRM_NOTA_CRIADA = "crm.nota.criada"
CRM_FUNIL_INSCRITO = "crm.funil.inscrito"

FIN_PAGAMENTO_RECEBIDO = "financeiro.pagamento.recebido"
FIN_COBRANCA_PROTESTADA = "financeiro.cobranca.protestada"
FIN_CONTA_PAGA = "financeiro.conta.paga"


class FactError(ValueError):
    """Violação de invariante do registro. Estoura a transação de propósito."""


# `R$ 1.234,56`, `R$1234`, `R$ 12,00` — o formato que o sistema gera em `_brl()`.
_PADRAO_DINHEIRO = re.compile(r"R\$\s*[\d.,]+")


class Fact(Base, TenantMixin, TimestampMixin):
    """Um fato narrativo na história do negócio."""

    __tablename__ = "facts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    # O vocabulário de `User.allowed_modules`. É o eixo de permissão do briefing.
    module: Mapped[str] = mapped_column(String(32), nullable=False)
    kind: Mapped[str] = mapped_column(String(48), nullable=False)
    title: Mapped[str] = mapped_column(String(140), nullable=False)
    body: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # CASCADE: a história de um contato não sobrevive ao contato (LGPD, direito ao
    # esquecimento). Contato é o sujeito PRIVILEGIADO num produto centrado em CRM; os demais
    # sujeitos usam a referência leve abaixo, que não cascateia e exige expurgo explícito.
    client_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("clients.id", ondelete="CASCADE"), nullable=True, index=True
    )
    subject_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    subject_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    actor: Mapped[str] = mapped_column(String(64), nullable=False)
    is_ai: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # QUANDO ACONTECEU, distinto de `created_at` (quando gravamos). Mensagem recebida às 23h50
    # e processada às 23h55 pertence à noite de ontem. A janela do briefing usa este campo.
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False, index=True
    )
    # `emitted` hoje. Existe para que um backfill futuro seja distinguível SEM migration —
    # nenhuma consulta pode assumir que o log cobre desde sempre.
    origin: Mapped[str] = mapped_column(String(16), default="emitted", nullable=False)

    # Default do lado do PYTHON, sobrescrevendo o `server_default=func.now()` do
    # TimestampMixin. No Postgres `now()` é o timestamp da TRANSAÇÃO: dois fatos do mesmo
    # commit sairiam com instante idêntico e o desempate cairia no uuid, invertendo a
    # causalidade na tela. Lição já paga por `ClientEvent`. O `server_default` fica para
    # qualquer INSERT que não passe pelo ORM.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )


def record(
    db: Session,
    *,
    tenant_id: str,
    module: str,
    kind: str,
    title: str,
    actor: str,
    body: str = "",
    client_id: str | None = None,
    subject_type: str | None = None,
    subject_id: str | None = None,
    is_ai: bool = False,
    occurred_at: datetime | None = None,
) -> Fact:
    """Grava um fato narrativo. **NÃO commita** — quem chama decide o momento.

    Sem retry, sem fila, sem abstração. Se falhar, a transação inteira falha — que é o
    comportamento correto: um fato que existe sem o negócio (ou o inverso) é pior que nenhum
    fato.

    ⚠️ Chame `db.flush()` antes se `subject_id` vier de um objeto recém-adicionado: o `id`
    ainda é `None` antes do flush. É a dívida MNT-001 em 17 call sites de `audit.record`.
    """
    if not kind.startswith(f"{module}."):
        raise FactError(
            f"kind '{kind}' não segue a convenção '<módulo>.<entidade>.<verbo>' "
            f"para o módulo '{module}'"
        )
    if _PADRAO_DINHEIRO.search(title):
        raise FactError(
            f"Invariante 2: o título do fato não pode conter dinheiro — {title!r}. "
            "O valor é lido da origem (charges/bank_transactions) na composição."
        )

    fact = Fact(
        tenant_id=tenant_id,
        module=module,
        kind=kind,
        title=title[:140],
        body=body,
        actor=actor,
        client_id=client_id,
        subject_type=subject_type,
        subject_id=subject_id,
        is_ai=is_ai,
        occurred_at=occurred_at or datetime.now(UTC),
    )
    db.add(fact)
    return fact
