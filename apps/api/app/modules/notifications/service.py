"""Notificações: reage a eventos de negócio e enfileira envios ao usuário (owner) + fila async.

Assina `crm.client.moved` (barramento core/events). Como o evento é emitido após o commit
do move, abrimos uma nova tenant_session para ENFILEIRAR a notificação (status="pending"). A
entrega real (WhatsApp/e-mail) fica para o worker (`process_pending`, chamado por app.worker),
fora do request/response HTTP — assim uma falha de envio nunca derruba a request de origem (IV2,
Story 4.3).
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import email, events, whatsapp
from app.db.session import tenant_session
from app.modules.auth.models import User
from app.modules.crm.models import Client, PipelineStage
from app.modules.crm.service import EVENT_CLIENT_MOVED
from app.modules.notifications.models import Notification
from app.modules.settings import service as settings_service
from app.modules.whatsapp_templates.models import (
    PURPOSE_CLIENT_MOVED,
    STATUS_APPROVED,
    WhatsappTemplate,
)

logger = logging.getLogger("e1p.notifications")


class NotificationError(Exception):
    """Erro de domínio do módulo de notificações (padrão MarketingError/JuridicoError).

    Usado como rede de segurança contra ENTRADA INVÁLIDA na origem (ex.: destinatário vazio).
    NÃO é uma rota HTTP: os call sites internos (assinantes de evento) devem tratá-lo dentro do
    próprio módulo, sem propagar e derrubar o publicador do evento.
    """

    def __init__(self, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _owner_recipient(db: Session, tenant_id: str) -> str:
    """Telefone do owner/destinatário para o WhatsApp.

    Prioridade: TenantProfile.phone (editável na tela Configurações por qualquer owner) →
    User.phone (preenchido no fluxo de convite) → User.email (fallback final, preserva o
    placeholder histórico e a graceful degradation quando nenhum telefone foi configurado).
    """
    owner = db.scalar(select(User).where(User.tenant_id == tenant_id, User.role == "owner"))
    profile = settings_service.get_profile(db, tenant_id)
    if profile.phone:
        return profile.phone
    if owner and owner.phone:
        return owner.phone
    return owner.email if owner else ""


def _render_template_preview(body_text: str, variables: list[str]) -> str:
    """Substitui {{1}}, {{2}}, ... no corpo do template pelos valores já resolvidos.

    Duplica `funnels.service._render_template_preview` (função privada de módulo, ~4 linhas) —
    evitamos importar através de módulos por uma função tão pequena (preferência do projeto contra
    abstração prematura).
    """
    rendered = body_text
    for i, value in enumerate(variables, start=1):
        rendered = rendered.replace(f"{{{{{i}}}}}", value)
    return rendered


# Validade por propósito (spec §7): dinheiro-com-data expira no fim do dia do tenant;
# operacional expira em 1h. Ausente da tabela (ou purpose=None) = nunca expira (compat).
_MONEY_PURPOSES = frozenset({"charge_reminder", "contract_send", "quote_send"})
_ONE_HOUR_PURPOSES = frozenset({"client_moved", "staff_invite", "funnel_node"})


def _compute_expires_at(db: Session, *, tenant_id: str, purpose: str | None) -> datetime | None:
    if purpose is None:
        return None
    now = datetime.now(UTC)
    if purpose in _ONE_HOUR_PURPOSES:
        return now + timedelta(hours=1)
    if purpose in _MONEY_PURPOSES:
        profile = settings_service.get_profile(db, tenant_id)
        try:
            tz = ZoneInfo(profile.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            tz = ZoneInfo("America/Sao_Paulo")
        local_now = now.astimezone(tz)
        end_of_day_local = local_now.replace(hour=23, minute=59, second=59, microsecond=0)
        return end_of_day_local.astimezone(UTC)
    return None  # propósito desconhecido — não inventa validade


def enqueue(
    db: Session,
    *,
    tenant_id: str,
    channel: str,
    recipient: str,
    message: str,
    client_id: str | None = None,
    purpose: str | None = None,
    whatsapp_template_name: str | None = None,
    whatsapp_template_language: str | None = None,
    whatsapp_template_variables: list | None = None,
) -> Notification:
    """Enfileira um envio (status="pending") — NÃO entrega agora nem commita.

    A entrega real acontece depois no worker (`process_pending`), fora do request/response HTTP.
    Segue o padrão das demais funções `service.*` que não commitam sozinhas: quem chama decide o
    commit dentro do seu fluxo maior.

    Rede de segurança (Story 7.11): um `recipient` vazio/em-branco é entrada inválida e é
    REJEITADO explicitamente com `NotificationError` — nunca enfileirado como `pending`
    indistinguível de um envio válido (que depois falharia mudo no worker).

    `whatsapp_template_*` (opcionais): template resolvido no ENFILEIRAMENTO (quando o propósito
    tem um vínculo aprovado) — o worker (`process_pending`) usa esses campos pra decidir entre
    `send_template` e `send_text`, sem precisar recalcular o vínculo depois.

    `purpose` (Onda 3): resolve a validade (`expires_at`) — dinheiro-com-data expira no fim do
    dia do tenant, operacional em 1h. `None` (chamadores anteriores à Onda 3) nunca expira,
    preservando o comportamento de hoje.
    """
    if not recipient or not recipient.strip():
        raise NotificationError("destinatário (recipient) vazio ou inválido")
    notification = Notification(
        tenant_id=tenant_id,
        channel=channel,
        recipient=recipient,
        message=message,
        client_id=client_id,
        status="pending",
        attempts=0,
        purpose=purpose,
        expires_at=_compute_expires_at(db, tenant_id=tenant_id, purpose=purpose),
        whatsapp_template_name=whatsapp_template_name,
        whatsapp_template_language=whatsapp_template_language,
        whatsapp_template_variables=whatsapp_template_variables,
    )
    db.add(notification)
    db.flush()
    return notification


def process_pending(db: Session, *, tenant_id: str, limit: int = 50) -> int:
    """Processa a fila de notificações `pending` do tenant. Retorna quantas foram processadas.

    Chamado pelo worker (`app.worker.run_sweep`). Uma falha ao entregar UMA notificação NÃO
    interrompe as demais (IV2): cada envio é isolado em try/except.

    Onda 3 — validade e retry: uma notificação com `expires_at` vencido nunca tenta entregar,
    vira `expired` direto. Uma falha de entrega REAGENDA (`next_attempt_at`, backoff
    exponencial `2**attempts` minutos, capado em 60min) em vez de marcar `failed` terminal —
    mas nunca além da própria validade: se o backoff estouraria `expires_at`, expira em vez de
    reagendar pra depois do próprio prazo.
    """
    now = datetime.now(UTC)
    pending = list(
        db.scalars(
            select(Notification)
            .where(
                Notification.status == "pending",
                (Notification.next_attempt_at.is_(None))
                | (Notification.next_attempt_at <= now),
            )
            .order_by(Notification.created_at)
            .limit(limit)
        ).all()
    )
    # Carregado uma vez por sweep (não por notificação) — a função já é tenant-scoped (param
    # `tenant_id`), então o token/phone_id do provedor é o mesmo para todo o lote.
    profile = settings_service.get_profile(db, tenant_id)
    processed = 0
    for notification in pending:
        if notification.expires_at is not None and notification.expires_at < now:
            notification.status = "expired"
            notification.attempts += 1
            processed += 1
            continue
        try:
            if notification.channel == "email":
                status = email.send_email(
                    to=notification.recipient,
                    subject="Notificação e1p",
                    body=notification.message,
                )
            elif notification.whatsapp_template_name:
                status = whatsapp.send_template(
                    to=notification.recipient,
                    profile=profile,
                    template_name=notification.whatsapp_template_name,
                    language=notification.whatsapp_template_language or "pt_BR",
                    variables=notification.whatsapp_template_variables or [],
                )
            else:
                status = whatsapp.send_text(
                    to=notification.recipient,
                    text=notification.message,
                    profile=profile,
                )
            notification.status = status
        except Exception as exc:  # noqa: BLE001 — isola a falha de UMA notificação (IV2)
            logger.exception(
                "[notifications:process_pending] falha ao enviar id=%s", notification.id
            )
            notification.last_error = str(exc)[:500]
            backoff_minutes = min(2**notification.attempts, 60)
            candidate_next = now + timedelta(minutes=backoff_minutes)
            if notification.expires_at is not None and candidate_next > notification.expires_at:
                notification.status = "expired"  # o backoff estouraria a validade — expira já
            else:
                notification.status = "pending"  # continua pending — tenta de novo depois
                notification.next_attempt_at = candidate_next
        notification.attempts += 1
        processed += 1
    db.commit()
    return processed


def on_client_moved(*, tenant_id: str, client_id: str, to_stage: str, **_: object) -> None:
    with tenant_session(tenant_id) as db:
        client = db.get(Client, client_id)
        # Rede de segurança (Story 7.11): cliente inexistente é entrada inválida na origem.
        # Antes, seguia-se com name="Cliente" (placeholder) e enfileirava-se uma notificação
        # `pending` indistinguível de um caso real — um sucesso silencioso. Agora, curto-circuita
        # explicitamente (não enfileira, loga warning). Fluxo feliz (cliente existente) segue igual.
        if client is None:
            logger.warning(
                "[notifications:on_client_moved] cliente inexistente client_id=%s tenant=%s — "
                "notificação NÃO enfileirada",
                client_id,
                tenant_id,
            )
            return
        stage = db.get(PipelineStage, to_stage)
        col = stage.name if stage else "—"
        text = f'📌 O cliente {client.name} foi movido para a etapa "{col}".'
        recipient = _owner_recipient(db, tenant_id)

        # Resolve o vínculo propósito→template (Configurações) AGORA, dentro da request — o
        # worker (process_pending) só entrega depois, sem recalcular vínculo/propósito.
        profile = settings_service.get_profile(db, tenant_id)
        template_id = (profile.whatsapp_template_bindings or {}).get(PURPOSE_CLIENT_MOVED)
        template = db.get(WhatsappTemplate, template_id) if template_id else None

        whatsapp_template_name = whatsapp_template_language = None
        whatsapp_template_variables: list[str] | None = None
        message = text
        if template is not None and template.status == STATUS_APPROVED:
            whatsapp_template_name = template.name
            whatsapp_template_language = template.language
            whatsapp_template_variables = [client.name, col]  # ordem = PURPOSE_VARIABLE_SPECS
            message = _render_template_preview(template.body_text, whatsapp_template_variables)

        # Enfileira (status="pending") em vez de enviar síncrono aqui: o handler roda dentro da
        # MESMA request que moveu o card (crm.service.move_client → events.emit). A entrega real
        # (WhatsApp) fica para o worker (process_pending), sem bloquear a request (IV2).
        try:
            enqueue(
                db,
                tenant_id=tenant_id,
                channel="whatsapp",
                recipient=recipient,
                message=message,
                client_id=client_id,
                purpose=PURPOSE_CLIENT_MOVED,
                whatsapp_template_name=whatsapp_template_name,
                whatsapp_template_language=whatsapp_template_language,
                whatsapp_template_variables=whatsapp_template_variables,
            )
            db.commit()
        except NotificationError:
            # Destinatário do owner não resolvido (tenant sem owner/contato) — não pode propagar
            # e derrubar o publicador do evento (crm.service já commitou o move). Loga e segue.
            logger.warning(
                "[notifications:on_client_moved] destinatário inválido tenant=%s — "
                "notificação NÃO enfileirada",
                tenant_id,
            )


def list_notifications(db: Session, limit: int = 50) -> list[Notification]:
    return list(
        db.scalars(
            select(Notification).order_by(Notification.created_at.desc()).limit(limit)
        ).all()
    )


def register() -> None:
    """Liga os assinantes do barramento. Chamado uma vez no boot (app.main)."""
    events.subscribe(EVENT_CLIENT_MOVED, on_client_moved)
