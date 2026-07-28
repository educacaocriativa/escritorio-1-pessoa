"""Schemas da bandeja de comprovantes."""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


class ReceiptOut(BaseModel):
    """Um comprovante em staging. Não expõe owner_type/owner_id — são detalhe interno."""

    id: str
    filename: str
    content_type: str
    size: int
    created_at: datetime


class ReceiptLinkIn(BaseModel):
    bill_id: str
    # Marcado por padrão: quem compartilha o comprovante acabou de pagar. A tela deixa desmarcar.
    mark_paid: bool = True


class ReceiptNewBillIn(BaseModel):
    """Formulário curto da tela do celular. Deliberadamente MENOR que PayableCreate: sem
    recorrência, sem classificação DRE, sem centro de custo — quem está no celular com o
    comprovante na mão quer registrar rápido e refinar depois no computador."""

    description: str = ""
    category: str = "Geral"
    supplier: str = ""
    amount_cents: int = Field(gt=0)
    due_date: date
    mark_paid: bool = True
