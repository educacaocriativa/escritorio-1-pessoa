"""Registro de idempotência da ingestão de leads (`POST /public/ingest/leads`).

Uma linha por `(tenant_id, chave_idempotencia)`, com restrição ÚNICA no banco (spec §6.2): a
Kiwify reenvia o mesmo webhook até 5 vezes e o site tem fila com nova tentativa — a mesma venda
VAI chegar mais de uma vez, e só a primeira pode ter efeito.

Tabela de NEGÓCIO (RLS). `payload` é o registro BRUTO da entrada (o mesmo papel de
`kiwify_eventos` no site), com contato e valores. É o único lugar do e1p onde o valor do pedido
fica, e é de propósito: `facts` não guarda dinheiro (invariante 2 de `core/facts.py`) e não
existe entidade de pedido no e1p (spec §10). `client_id` com CASCADE: apagar o contato (LGPD)
leva junto o payload que tem o e-mail e o telefone dele.

`concluido_em` separa "reivindicada" de "processada". `crm.absorb_lead` commita no meio do
caminho, então a reivindicação entra no MESMO commit do contato e tags + fato + etapa entram no
seguinte. Se o processo cair entre os dois, a linha fica sem `concluido_em` e a PRÓXIMA tentativa
retoma em vez de responder "já processado" — sem isso, uma queda no meio viraria venda sem tag e
sem Ganho, confirmada como sucesso para quem reenviou.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantMixin, TimestampMixin, _uuid


class LeadIngestRecord(Base, TenantMixin, TimestampMixin):
    __tablename__ = "lead_ingest_records"
    __table_args__ = (
        UniqueConstraint("tenant_id", "chave_idempotencia", name="uq_lead_ingest_tenant_chave"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    chave_idempotencia: Mapped[str] = mapped_column(String(200), nullable=False)
    evento: Mapped[str] = mapped_column(String(32), nullable=False)
    # Quando ACONTECEU (a venda, o abandono), não quando chegou aqui.
    ocorrido_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    client_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("clients.id", ondelete="CASCADE"), nullable=True, index=True
    )
    tags_descartadas: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    concluido_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
