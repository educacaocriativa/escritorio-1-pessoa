"""Conta de investimento — entidade de NEGÓCIO (RLS), Story 5.6.

`kind` (tipo de aplicação) e `index_rate_label` (indexador/taxa) são TEXTO LIVRE informativo —
NÃO há integração com API de índice de mercado (CDI/IPCA reais) nem cálculo automático de
rendimento por indexador; o rendimento é sempre lançado explicitamente pelo dono via
`register_yield` (ver service). `index_rate_label` é só um rótulo (ex.: "CDI 110%", "IPCA+6%").

Dinheiro sempre em centavos `BigInteger` (Regra de Ouro nº 4). `accrued_yield_cents` acumula o
rendimento já lançado; cada lançamento também cria uma `Charge` de receita financeira (Task 3).
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import BigInteger, Date, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantMixin, TimestampMixin, _uuid

# Tipos SUGERIDOS de aplicação (vocabulário oferecido na UI). NÃO é enum fechado — o backend aceita
# qualquer texto curto e NÃO valida contra esta lista (produto de investimento não é taxonomia
# fechada; mesmo contraste deliberado do `kind` livre do centro de custo — Story 5.5).
SUGGESTED_KINDS: tuple[str, ...] = ("CDB", "Tesouro", "Fundo", "Poupança", "LCI/LCA", "Ações")

# Prefixo do `Charge.external_ref` que MARCA um lançamento como rendimento de investimento (Task 3).
# Correlaciona a Charge sintética à conta de origem SEM uma FK dura (mesmo padrão de referência
# solta do projeto). É também o marcador que distingue esse lançamento de uma cobrança de cliente.
# ⚠️ Story 5.6 (quality_gate Aria): `receivables.service._INVESTMENT_REF_PREFIX` DUPLICA esta string
# de propósito para filtrar estes lançamentos das telas de Contas a Receber (sem criar dependência
# circular receivables→investments). Se mudar aqui, mude lá também.
EXTERNAL_REF_PREFIX = "investment:"


def external_ref_for(account_id: str) -> str:
    """`external_ref` da Charge de rendimento de uma conta (ex.: 'investment:<account_id>')."""
    return f"{EXTERNAL_REF_PREFIX}{account_id}"


class InvestmentAccount(Base, TenantMixin, TimestampMixin):
    __tablename__ = "investment_accounts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    # Tipo de aplicação (texto livre categorizado — ver SUGGESTED_KINDS). Default vazio.
    kind: Mapped[str] = mapped_column(String(24), default="", nullable=False)
    # Indexador/taxa como RÓTULO informativo (não é cálculo automático). Ex.: "CDI 110%".
    index_rate_label: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    # Principal aplicado (centavos).
    principal_cents: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    # Rendimento acumulado (centavos) — soma dos rendimentos já lançados via register_yield.
    accrued_yield_cents: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    opened_at: Mapped[date] = mapped_column(Date, nullable=False)
