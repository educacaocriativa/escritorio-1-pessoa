"""Assistente Jurídico — documentos gerados por IA a partir das skills jurídicas.

Cada skill (petição, sentença, contrato, despacho, etc.) tem um SKILL.md (prompt-sistema) e
um wizard_config (formulário). O usuário preenche o formulário, opcionalmente anexa peças, e a
IA gera o documento. O resultado fica salvo aqui (RLS por tenant).

O texto enviado à IA é SEMPRE anonimizado antes (ver core/anonymizer.py) — segredo de justiça.
client_id (opcional) liga o documento a um cliente do CRM, integrando com o resto do software.
"""
from __future__ import annotations

from sqlalchemy import JSON, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantMixin, TimestampMixin, _uuid

STATUS_READY = "ready"
STATUS_FAILED = "failed"


class LegalDocument(Base, TenantMixin, TimestampMixin):
    __tablename__ = "legal_documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    skill: Mapped[str] = mapped_column(String(60), nullable=False)
    category: Mapped[str] = mapped_column(String(24), default="core", nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    # Vínculo opcional com o CRM (cliente/parte) — integra com Ficha 360°.
    client_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    content: Mapped[str] = mapped_column(Text, default="", nullable=False)  # documento (markdown)
    metadata_raw: Mapped[str] = mapped_column(Text, default="", nullable=False)  # seção METADADOS
    # Entradas do wizard (para reabrir/auditar) — sem PII sensível além do que o usuário digitou.
    answers: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(12), default=STATUS_READY, nullable=False)
