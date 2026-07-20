"""Anexos — upload real de arquivos (boleto, contrato) ligados a uma entidade.

Os bytes podem morar em duas camadas (Story 3.5): object storage S3-compatível (quando
`storage_key` está setado) ou no Postgres (`data` LargeBinary — fallback legado / storage
desligado). Ambas as colunas são nullable: exatamente uma delas carrega os bytes por linha.
owner_type/owner_id ligam o anexo a um Payable, Charge, etc. Tabela de NEGÓCIO (RLS).
"""
from __future__ import annotations

from sqlalchemy import Integer, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantMixin, TimestampMixin, _uuid

# tipos de arquivo aceitos (inclui mídia recebida/enviada via WhatsApp — áudio/vídeo/documento
# genérico — ver whatsapp_inbox)
ALLOWED_TYPES = {
    "application/pdf", "image/jpeg", "image/png",
    "audio/ogg", "audio/mpeg", "video/mp4", "application/octet-stream",
}
MAX_BYTES = 10 * 1024 * 1024  # 10 MB

# Imagens INTENCIONALMENTE públicas (logo/fotos): só formatos renderizáveis em <img>/CSS.
# Distinto de ALLOWED_TYPES (que inclui PDF) — estas nunca são abertas como documento.
PUBLIC_IMAGE_TYPES = {"image/jpeg", "image/png"}


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
    # Bytes no Postgres (fallback legado / storage S3 desligado). Nullable desde a Story 3.5:
    # anexos migrados para o S3 têm `data=None` e `storage_key` setado.
    data: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    # Chave do objeto no storage S3-compatível (Story 3.5). None = bytes ainda no Postgres.
    storage_key: Mapped[str | None] = mapped_column(String(512), nullable=True)


class PublicImage(Base, TimestampMixin):
    """Imagens deliberadamente PÚBLICAS na leitura (logo/fotos de proposta, carrossel, site).

    Tabela GLOBAL (SEM ``TenantMixin`` / SEM RLS), mesmo padrão de ``published_proposals`` /
    ``published_pages`` / ``published_contracts``: a LEITURA é pública por design — a imagem é
    renderizada num ``<img>``/``background-image`` inclusive nas páginas públicas sem login
    (``/p/:slug``), onde nenhum token é enviado. O isolamento relevante (Regra de Ouro nº 1)
    acontece na ESCRITA: o upload (``POST /attachments/public-images``) exige um usuário
    autenticado do tenant, e ``tenant_id`` é gravado APENAS para rastreio/auditoria — NUNCA é
    usado como controle de acesso de leitura. É uma tabela separada de ``Attachment`` (que guarda
    boletos/contratos e permanece 100% protegida por RLS, sem nenhuma rota pública).
    """

    __tablename__ = "public_images"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    # tenant_id: coluna simples de rastreio/auditoria — NÃO controla acesso de leitura.
    tenant_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
