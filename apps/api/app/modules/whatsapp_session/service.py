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
    STATUS_CONNECTED,
    STATUS_CONNECTING,
    STATUS_DISCONNECTED,
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


def _fetch_evolution_status(instance: str) -> str | None:
    """Consulta a Evolution pelo status bruto da instância. Devolve o `status` da Evolution
    ("open", "connecting", etc.) ou None se a instância não aparecer/a chamada falhar."""
    try:
        resp = httpx.get(
            f"{settings.evolution_api_url}/instance/fetchInstances",
            headers=_headers(), params={"instanceName": instance}, timeout=10,
        )
        resp.raise_for_status()
    except httpx.HTTPError:
        return None
    data = resp.json()
    items = data if isinstance(data, list) else []
    for item in items:
        inst = item.get("instance", item)
        if inst.get("instanceName") == instance:
            return inst.get("status")
    return None


def get_status(db: Session, *, tenant_id: str) -> str:
    """PURAMENTE leitura — nunca escreve no banco (ver Global Constraints do plano). Devolve
    'never' (nunca conectou), 'connecting', 'connected' ou 'disconnected'."""
    instance = _instance_name(tenant_id)
    row = db.get(PublicWhatsappInstance, instance)
    if row is None:
        return "never"
    evo_status = _fetch_evolution_status(instance)
    if evo_status == "open":
        return STATUS_CONNECTED
    if evo_status is None:
        return STATUS_DISCONNECTED
    return STATUS_CONNECTING


def confirm(db: Session, *, tenant_id: str) -> str:
    """Reverifica com a Evolution (nunca confia no client) e, se realmente 'open', É QUEM
    seta `whatsapp_provider='evolution'` — a única escrita de transição-pra-conectado deste
    módulo. Chamado pelo frontend ao ver 'connected' pela primeira vez; o worker (Onda 2,
    4ª etapa) é a rede de segurança caso a aba feche antes disso."""
    instance = _instance_name(tenant_id)
    row = db.get(PublicWhatsappInstance, instance)
    if row is None:
        return "never"
    evo_status = _fetch_evolution_status(instance)
    if evo_status != "open":
        return STATUS_CONNECTING if evo_status is not None else STATUS_DISCONNECTED
    profile = settings_service.get_profile(db, tenant_id)
    profile.whatsapp_provider = "evolution"
    row.last_status = STATUS_CONNECTED
    db.commit()
    return STATUS_CONNECTED


def refresh_qr(db: Session, *, tenant_id: str) -> str:
    """QR expira em ~60s do lado da Evolution — pede um novo."""
    _require_configured()
    instance = _instance_name(tenant_id)
    try:
        resp = httpx.get(
            f"{settings.evolution_api_url}/instance/connect/{instance}",
            headers=_headers(), timeout=15,
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise WhatsappSessionError(f"Falha de rede ao renovar o QR: {exc}", 502) from exc
    return resp.json().get("base64", "")


def disconnect(db: Session, *, tenant_id: str) -> None:
    """Logout na Evolution + limpa `whatsapp_provider` (usado pra trocar de número/transporte).
    Não propaga falha de rede do logout — o produto ainda deve conseguir "esquecer" a conexão
    localmente mesmo se a Evolution estiver fora do ar."""
    instance = _instance_name(tenant_id)
    try:
        httpx.delete(
            f"{settings.evolution_api_url}/instance/logout/{instance}",
            headers=_headers(), timeout=15,
        )
    except httpx.HTTPError:
        pass
    profile = settings_service.get_profile(db, tenant_id)
    profile.whatsapp_provider = None
    row = db.get(PublicWhatsappInstance, instance)
    if row is not None:
        row.last_status = STATUS_DISCONNECTED
    db.commit()


def check_connections(db: Session, *, tenant_id: str) -> int:
    """Chamado pelo worker (4ª etapa do sweep). Para tenants JÁ conectados por Evolution
    (`whatsapp_provider == "evolution"`), confere se a sessão caiu (Evolution não reporta mais
    "open") e, se sim, avisa o dono por e-mail (canal que não depende do que acabou de quebrar)
    e marca `last_status`. NÃO cuida da transição connecting->connected (isso é `confirm()`,
    chamado pelo frontend) — só monitora quedas de quem já estava de pé. Devolve quantas quedas
    detectou (0 ou 1, já que é por-tenant; o worker soma entre tenants)."""
    from app.core.email import send_email

    profile = settings_service.get_profile(db, tenant_id)
    if profile.whatsapp_provider != "evolution":
        return 0
    instance = _instance_name(tenant_id)
    row = db.get(PublicWhatsappInstance, instance)
    if row is None or row.last_status != STATUS_CONNECTED:
        return 0
    evo_status = _fetch_evolution_status(instance)
    if evo_status == "open":
        return 0
    row.last_status = STATUS_DISCONNECTED
    db.commit()
    if profile.email:
        send_email(
            to=profile.email,
            subject="WhatsApp desconectado no e1p",
            body=(
                "O WhatsApp da sua conta caiu e precisa ser reconectado. "
                "Acesse Configurações > WhatsApp e escaneie o QR Code novamente."
            ),
        )
    return 1
