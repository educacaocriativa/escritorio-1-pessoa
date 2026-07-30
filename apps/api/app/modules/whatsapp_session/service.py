"""Ciclo de vida da sessão WhatsApp por Evolution API (QR Code). Ver
docs/superpowers/specs/2026-07-30-whatsapp-evolution-multi-tenant-design.md §5.

Separado de `core/whatsapp/providers/evolution.py` (que só cobre ENVIO de mensagem) — gerenciar
a instância (criar, webhook, QR, status, logout) é um contrato de API diferente da Evolution,
com credencial GLOBAL igual, mas endpoints e ciclo de vida próprios.
"""
from __future__ import annotations

import secrets

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.modules.settings import service as settings_service
from app.modules.whatsapp_session.models import (
    STATUS_CONNECTING,
    PublicWhatsappInstance,
)


class WhatsappSessionError(Exception):
    def __init__(self, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.status_code = status_code


def _instance_name(tenant_id: str) -> str:
    return f"e1p-{tenant_id}"


def _headers() -> dict[str, str]:
    return {"apikey": settings.evolution_api_key}


def _require_configured() -> None:
    if not settings.evolution_api_key:
        raise WhatsappSessionError(
            "Evolution API não configurada nesta instalação (EVOLUTION_API_KEY ausente)", 503
        )


def connect(db: Session, *, tenant_id: str) -> dict:
    """Idempotente: cria a instância na Evolution se não existir, configura o webhook (aponta
    para a rota interna que a Onda 3 implementa) e devolve o QR em base64.

    NÃO altera `TenantProfile.whatsapp_provider` — essa transição só acontece em `confirm()`,
    depois que o QR é escaneado de verdade (ver Global Constraints do plano)."""
    _require_configured()
    instance = _instance_name(tenant_id)
    settings_service.get_profile(db, tenant_id)  # garante que o profile existe

    try:
        resp = httpx.post(
            f"{settings.evolution_api_url}/instance/create",
            headers=_headers(),
            json={"instanceName": instance, "qrcode": True, "integration": "WHATSAPP-BAILEYS"},
            timeout=15,
        )
        # A Evolution devolve erro se a instância já existir — idempotente: ignoramos esse
        # caso específico (detectado pelo texto da resposta) e seguimos pro resto do fluxo.
        if resp.status_code >= 400 and "already" not in resp.text.lower():
            raise WhatsappSessionError(
                f"Falha ao criar instância na Evolution: {resp.text}", 502
            )
    except httpx.HTTPError as exc:
        raise WhatsappSessionError(f"Falha de rede ao criar instância: {exc}", 502) from exc

    existing = db.get(PublicWhatsappInstance, instance)
    webhook_secret = existing.webhook_secret if existing else secrets.token_urlsafe(32)

    try:
        httpx.post(
            f"{settings.evolution_api_url}/webhook/set/{instance}",
            headers=_headers(),
            json={
                "url": (
                    f"{settings.internal_api_base_url}"
                    f"/internal/whatsapp/evolution/webhook/{webhook_secret}"
                ),
                "webhook_by_events": False,
                "events": ["MESSAGES_UPSERT"],
            },
            timeout=15,
        )
    except httpx.HTTPError as exc:
        raise WhatsappSessionError(f"Falha de rede ao configurar webhook: {exc}", 502) from exc

    if existing is None:
        db.add(
            PublicWhatsappInstance(
                instance_name=instance, tenant_id=tenant_id,
                webhook_secret=webhook_secret, last_status=STATUS_CONNECTING,
            )
        )
    else:
        existing.last_status = STATUS_CONNECTING
    db.commit()

    try:
        resp = httpx.get(
            f"{settings.evolution_api_url}/instance/connect/{instance}",
            headers=_headers(), timeout=15,
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise WhatsappSessionError(f"Falha de rede ao obter QR: {exc}", 502) from exc

    data = resp.json()
    return {"qr_base64": data.get("base64", ""), "status": STATUS_CONNECTING}
