"""Schemas da bandeja de comprovantes."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


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
