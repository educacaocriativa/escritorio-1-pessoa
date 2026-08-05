"""Ciclo de vida da sessão WhatsApp por Evolution API (QR Code). Ver
docs/superpowers/specs/2026-07-30-whatsapp-evolution-multi-tenant-design.md §5.

Separado de `core/whatsapp/providers/evolution.py` (que só cobre ENVIO de mensagem) — gerenciar
a instância (criar, webhook, QR, status, logout) é um contrato de API diferente da Evolution,
com credencial GLOBAL igual, mas endpoints e ciclo de vida próprios.
"""
from __future__ import annotations

import logging
import secrets

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.modules.settings import service as settings_service
from app.modules.whatsapp_session.models import (
    STATUS_CONNECTED,
    STATUS_CONNECTING,
    STATUS_DISCONNECTED,
    PublicWhatsappInstance,
)

logger = logging.getLogger("e1p.whatsapp")


class WhatsappSessionError(Exception):
    def __init__(self, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.status_code = status_code


def _instance_name(tenant_id: str) -> str:
    return f"e1p-{tenant_id}"


def resolve_by_webhook_secret(
    db: Session, *, webhook_secret: str
) -> PublicWhatsappInstance | None:
    """Resolve a instância pelo segredo do webhook — chamado numa sessão SEM tenant (`get_db`),
    ANTES de qualquer autenticação, mesmo padrão de `whatsapp_inbox.resolve_account`. Percorre
    todas as instâncias comparando o valor DECIFRADO (o segredo não é indexável cifrado) — custo
    aceitável pelo volume esperado (uma linha por tenant conectado, não por mensagem)."""
    for instance in db.scalars(select(PublicWhatsappInstance)).all():
        if instance.webhook_secret == webhook_secret:
            return instance
    return None


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
        # timeout generoso: a Evolution só responde depois que o Baileys termina o handshake
        # inicial com o WhatsApp pra gerar o QR — em produção isso já levou mais de 15s.
        resp = httpx.post(
            f"{settings.evolution_api_url}/instance/create",
            headers=_headers(),
            json={"instanceName": instance, "qrcode": True, "integration": "WHATSAPP-BAILEYS"},
            timeout=45,
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
        # v2.3.7 espera o payload ANINHADO sob "webhook" (com "enabled"/"byEvents") — um corpo
        # solto ({"url":..., "webhook_by_events":...}) é ignorado sem erro visível pra quem
        # chama (achado ao vivo: webhook/find devolvia null mesmo após esse POST "ter sucesso").
        resp = httpx.post(
            f"{settings.evolution_api_url}/webhook/set/{instance}",
            headers=_headers(),
            json={
                "webhook": {
                    "enabled": True,
                    "url": (
                        f"{settings.internal_api_base_url}"
                        f"/internal/whatsapp/evolution/webhook/{webhook_secret}"
                    ),
                    "byEvents": False,
                    # `MESSAGES_UPSERT` é o que CHEGA — mensagem do contato e também a que o
                    # dono digita no celular dele (o Baileys espelha as duas no mesmo evento;
                    # ver `from_me` em `parse_inbound`). O que sai pela API da PRÓPRIA Evolution
                    # (`/message/sendText`, usado pelo worker de notificações) vem em
                    # `SEND_MESSAGE` — evento diferente. Sem ele, tudo que o produto dispara
                    # sozinho (funil, cobrança, contrato) saía de verdade e NÃO ficava registrado
                    # na conversa: o fio mostrava só um lado. Nomes conferidos na imagem que roda
                    # em produção (`grep` no dist da v2.3.7), não na documentação.
                    #
                    # Duplicar não é risco: `ingest_webhook_payload` é idempotente por
                    # `wa_message_id`, então a mesma mensagem chegando pelos dois eventos vira
                    # uma linha só.
                    "events": ["MESSAGES_UPSERT", "SEND_MESSAGE"],
                    # A Evolution baixa e decifra a mídia (tem a mediaKey) e injeta o resultado
                    # em `message.base64` — sem isto, mídia recebida (foto/áudio/documento)
                    # chega só com metadado (legenda/mimetype), sem os bytes (ver
                    # `providers/evolution.py::parse_inbound`, que depende deste campo).
                    "base64": True,
                }
            },
            timeout=15,
        )
        if resp.status_code >= 400:
            raise WhatsappSessionError(
                f"Falha ao configurar webhook na Evolution: {resp.text}", 502
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
            headers=_headers(), timeout=45,
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
        # v2.3.7 devolve os campos direto no item (sem wrapper "instance"), com "name" (não
        # "instanceName") e "connectionStatus" (não "status") — confirmado ao vivo contra a
        # API real; achado porque a versão anterior deste código nunca batia, então
        # get_status()/confirm() sempre viam a sessão como desconectada mesmo já conectada.
        if item.get("name") == instance:
            return item.get("connectionStatus")
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
    módulo. Chamado pelo frontend ao ver 'connected' pela primeira vez; se a aba fechar antes
    disso, `promote_pending_connections` (worker) faz a mesma transição."""
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


def promote_pending_connections(db: Session, *, tenant_id: str) -> int:
    """A rede de segurança que `confirm()` sempre prometeu e nunca teve. Devolve 1 se promoveu.

    Quem escreve `whatsapp_provider='evolution'` é `confirm()`, disparado PELO FRONTEND ao ver
    'connected'. Se a aba fechar antes, a Evolution segue conectada e o campo segue nulo — e o
    despachante, que DERIVA o transporte desse campo (`core/whatsapp._resolve`), manda todo
    envio pela Meta, que sem credencial devolve "logged". Nada protesta em lugar nenhum: o
    recebimento continua funcionando (o webhook não consulta o provider), então o tenant parece
    saudável enquanto nenhuma mensagem sai. Bug real de produção (2026-08-05, Doro Eventos): um
    convite de funcionário ficou `logged` e a senha nunca chegou ao destinatário.

    `check_connections` NÃO cobria isso: ele retorna cedo justamente quando o provider ainda não
    é "evolution", que é a condição do defeito.

    Só promove quem está em `connecting`. Uma instância em `disconnected` pode continuar "open"
    do lado da Evolution — `disconnect()` engole falha de rede do logout —, e promovê-la
    desfaria em silêncio um pedido explícito do dono.
    """
    row = db.get(PublicWhatsappInstance, _instance_name(tenant_id))
    if row is None or row.last_status != STATUS_CONNECTING:
        return 0
    profile = settings_service.get_profile(db, tenant_id)
    if profile.whatsapp_provider == "evolution":
        return 0
    if _fetch_evolution_status(row.instance_name) != "open":
        return 0
    profile.whatsapp_provider = "evolution"
    row.last_status = STATUS_CONNECTED
    db.commit()
    logger.info(
        "[whatsapp.session] conexão confirmada pelo worker (aba fechou antes) tenant=%s", tenant_id
    )
    return 1


def refresh_qr(db: Session, *, tenant_id: str) -> str:
    """QR expira em ~60s do lado da Evolution — pede um novo."""
    _require_configured()
    instance = _instance_name(tenant_id)
    try:
        resp = httpx.get(
            f"{settings.evolution_api_url}/instance/connect/{instance}",
            headers=_headers(), timeout=45,
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
