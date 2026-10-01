"""Credencial de máquina: token com escopo, emitido para um TENANT (não para uma pessoa).

Irmã de `device_tokens` — hash sha256, escopo travado, revogação —, com uma diferença de
propósito: o dono de um `DeviceToken` é uma PESSOA (o Atalho do iOS dela); o dono de um
`MachineToken` é um SISTEMA que fala com o e1p servidor-a-servidor. Hoje, o site que empurra
leads (`POST /public/ingest/leads`). Por isso não há `user_id`.

Reconstrói, com escopo e contrato novos, a capacidade que o PR #270 removeu (chave de API de
"Integrações", migração 0083) — o caso "site headless que não embute iframe" que a própria nota
de remoção deixou previsto.

Tabela GLOBAL (sem `TenantMixin`, sem RLS) pela mesma razão de `device_tokens` e `users`: o
tenant é resolvido A PARTIR do token, antes de existir uma `tenant_session`. Guarda só hash e
metadado de credencial — nenhum dado de negócio. Quem a lê: a dependência de autenticação de
`lead_ingest/router.py` e o script `app/scripts/lead_ingest_admin.py`. Nenhum módulo de negócio.

⚠️ Por ser global, a purga dinâmica de `platform.delete_account` (que varre subclasses de
`TenantMixin`) NÃO a alcança — o DELETE explícito mora lá.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, _uuid

# Autoriza SOMENTE `POST /public/ingest/leads`: uma escrita que não devolve nenhum dado do
# tenant. O pior caso de um vazamento é alguém criar leads falsos — visíveis e apagáveis.
SCOPE_LEAD_INGEST = "lead_ingest"
SCOPES = frozenset({SCOPE_LEAD_INGEST})


class MachineToken(Base, TimestampMixin):
    __tablename__ = "machine_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    # Coluna de RESOLUÇÃO, não de controle de acesso (a tabela é global).
    tenant_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    # sha256 do token cru. O cru NUNCA é persistido.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
