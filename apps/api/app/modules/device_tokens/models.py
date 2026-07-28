"""Token de dispositivo: credencial de escopo único para o Atalho do iOS.

Tabela GLOBAL (sem `TenantMixin`, sem RLS) pela MESMA razão que `users` é: o tenant precisa
ser resolvido A PARTIR do token, antes de existir uma `tenant_session` para consultar. Guarda
apenas hash e metadado de credencial — nenhum dado de negócio. Vale aqui a mesma regra já
registrada no CLAUDE.md para `users`: nenhum módulo de negócio consulta esta tabela.

O desenho assume que o token VAI vazar um dia (ele vive em texto claro dentro do atalho, no
aparelho). Por isso o `scope` é travado: ele só autoriza `POST /payables/receipts`, uma
escrita que não devolve nenhum dado. Ver `app/core/receipt_auth.py`.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, _uuid

# Único escopo existente. Autoriza SOMENTE o upload do comprovante para a bandeja.
SCOPE_RECEIPT_UPLOAD = "receipt_upload"


class DeviceToken(Base, TimestampMixin):
    __tablename__ = "device_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    # tenant_id é coluna simples de resolução (não controla acesso por RLS — a tabela é global).
    tenant_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    user_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    # sha256 do token cru. O cru NUNCA é persistido — mesmo padrão do reset de senha.
    token_hash: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    scope: Mapped[str] = mapped_column(String(32), nullable=False, default=SCOPE_RECEIPT_UPLOAD)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
