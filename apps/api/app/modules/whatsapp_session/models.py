"""Snapshot GLOBAL (sem RLS, SEM TenantMixin) da instância Evolution de cada tenant — resolve
`instance_name -> tenant_id` + `webhook_secret` ANTES de qualquer autenticação. Mesmo padrão de
`PublicWhatsappAccount` (whatsapp_inbox), chave natural distinta (nome de instância, não
phone_number_id da Meta) — por isso é tabela própria, não a mesma.
"""
from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.token_crypto import EncryptedToken
from app.db.base import Base, TimestampMixin

STATUS_CONNECTING = "connecting"
STATUS_CONNECTED = "connected"
STATUS_DISCONNECTED = "disconnected"


class PublicWhatsappInstance(Base, TimestampMixin):
    __tablename__ = "public_whatsapp_instances"

    instance_name: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    # Cifrado em repouso (mesmo padrão de `PublicWhatsappAccount.app_secret`) — usado como
    # segmento de path no webhook interno (Onda 3), defesa em profundidade além do isolamento
    # de rede (a Evolution só existe na rede interna do Docker).
    webhook_secret: Mapped[str] = mapped_column(EncryptedToken, nullable=False)
    last_status: Mapped[str] = mapped_column(
        String(16), default=STATUS_CONNECTING, nullable=False
    )
