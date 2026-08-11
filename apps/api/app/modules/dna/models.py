"""A resposta do DNA — estado atual, não história.

**É upsert, não append — o oposto de `core/facts.py`, e de propósito.** Fato é história; DNA é
estado atual. Guardar versões faria toda leitura ter que decidir qual resposta vale.

**O histórico de quem mudou o quê é trabalho de `core/audit.py`, e desde 2026-08-11 isso é
verdade.** Até essa data a frase acima estava escrita aqui e não tinha código atrás: `audit`
aparecia UMA vez no módulo inteiro, dentro dela, com zero chamadas. Era a classe de defeito nº 1
do Epic 8 — o documento que afirma sobre a camada de baixo e desliga quem viria conferir —, e aqui
mais grave, porque **sustentava uma decisão de modelagem**: o upsert foi aceito em troca de uma
rede que ninguém tinha tecido.

Quem grava, hoje (verificável por `grep -rn "eventos.registrar" apps/api/app/modules/dna/`):
`service._gravar` → `dna.answer.save` / `dna.answer.skip`, com `target=<source>:<pergunta>`;
`router.nucleo_evento` → `dna.nucleo.open` / `dna.nucleo.abandon`. **Se esta lista divergir do
grep, é ela que está errada.**

`value` nulo NÃO é ausência de linha: é "o dono viu a pergunta e pulou". A distinção sustenta a
quarentena de 7 dias em `cadencia.py` sem tabela nova.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantMixin, TimestampMixin, _uuid

SOURCE_NUCLEO = "nucleo"
SOURCE_GANCHO = "gancho"
SOURCE_CONFIG = "config"


class DnaAnswer(Base, TenantMixin, TimestampMixin):
    """Uma resposta do dono sobre o próprio negócio."""

    __tablename__ = "dna_answers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    question_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # `int | str | list | None` — o formato é decidido pelo catálogo, e a validação acontece no
    # serviço, contra ele. A coluna é frouxa; a porta de entrada é estreita.
    value: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    answered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # A resposta é do TENANT, mas a autoria importa quando há sub-usuário.
    answered_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
