"""Anexos — upload real de arquivos (boleto, contrato) ligados a uma entidade.

Os bytes ficam no Postgres (LargeBinary) com RLS — simples e isolado por tenant para o
estágio atual; migrar para S3 é dívida. owner_type/owner_id ligam o anexo a um Payable,
Charge, etc. Tabela de NEGÓCIO (RLS).
"""
from __future__ import annotations

from sqlalchemy import Integer, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantMixin, TimestampMixin, _uuid

# tipos de arquivo aceitos
ALLOWED_TYPES = {"application/pdf", "image/jpeg", "image/png"}
MAX_BYTES = 10 * 1024 * 1024  # 10 MB


class Attachment(Base, TenantMixin, TimestampMixin):
    __tablename__ = "attachments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    # owner_type: payable / charge / ...
    owner_type: Mapped[str] = mapped_column(String(24), index=True, nullable=False)
    owner_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    # label: boleto / contrato / outro
    label: Mapped[str] = mapped_column(String(24), default="outro", nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
