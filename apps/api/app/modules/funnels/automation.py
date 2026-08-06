"""Auto-enroll: inscreve automaticamente um lead novo no Funil de Vendas padrão do tenant.

Assina `crm.client.created` (barramento core/events). Como o evento é emitido após o commit
da criação do cliente, abrimos uma nova tenant_session para rodar o `engine.enroll` — mesmo
padrão de `notifications/service.py::on_client_moved` (IV2: uma falha aqui nunca derruba a
request de origem, que já commitou o lead).

Só dispara para leads que vieram de captura automatizada (`source` em AUTO_ENROLL_SOURCES) —
criação manual no CRM e importação em lote NÃO entram sozinhas no funil, para não surpreender
o dono nem inscrever em massa.
"""
from __future__ import annotations

import logging

from sqlalchemy import select

from app.core import events
from app.core.facts import CRM_FUNIL_INSCRITO
from app.db.session import tenant_session
from app.modules.crm.service import EVENT_CLIENT_CREATED, EVENT_CLIENT_RETURNED, record_event
from app.modules.funnels import engine, service
from app.modules.funnels.models import RUN_RUNNING, RUN_WAITING, FunnelRun
from app.modules.settings import service as settings_service

logger = logging.getLogger("e1p.funnels.automation")

AUTO_ENROLL_SOURCES = {"landing", "api"}


def on_client_created(*, tenant_id: str, client_id: str, source: str, **_: object) -> None:
    if source not in AUTO_ENROLL_SOURCES:
        return
    with tenant_session(tenant_id) as db:
        profile = settings_service.get_profile(db, tenant_id)
        if not profile.default_entry_funnel_id:
            return
        try:
            engine.enroll(
                db, tenant_id=tenant_id, actor="sistema:auto-enroll",
                funnel_id=profile.default_entry_funnel_id, client_id=client_id,
            )
        except service.FunnelError:
            # Funil apagado/inválido/vazio: não pode propagar e derrubar o publicador do
            # evento (crm.service já commitou o lead). Loga e segue (mesma garantia de
            # notifications.on_client_moved).
            logger.warning(
                "[funnels:on_client_created] auto-enroll falhou tenant=%s funil=%s cliente=%s",
                tenant_id, profile.default_entry_funnel_id, client_id,
            )


def _ja_esta_andando(db, *, funnel_id: str, client_id: str) -> bool:
    """Jornada viva (running/waiting) para este contato neste funil."""
    return db.scalar(
        select(FunnelRun.id).where(
            FunnelRun.funnel_id == funnel_id,
            FunnelRun.client_id == client_id,
            FunnelRun.status.in_((RUN_RUNNING, RUN_WAITING)),
        )
    ) is not None


def on_client_returned(*, tenant_id: str, client_id: str, source: str, **_: object) -> None:
    """Contato conhecido voltou pela captura: reinscreve, se a jornada anterior já acabou.

    A guarda de "já está andando" vive AQUI e não dentro de `engine.enroll`: inscrição manual
    pela tela do funil deve continuar fazendo exatamente o que o usuário mandar, sem recusar
    em silêncio. Só o caminho automático precisa dessa contenção — senão preencher o
    formulário duas vezes reiniciaria a jornada do zero.
    """
    if source not in AUTO_ENROLL_SOURCES:
        return
    with tenant_session(tenant_id) as db:
        profile = settings_service.get_profile(db, tenant_id)
        if not profile.default_entry_funnel_id:
            return
        if _ja_esta_andando(
            db, funnel_id=profile.default_entry_funnel_id, client_id=client_id
        ):
            return
        try:
            engine.enroll(
                db, tenant_id=tenant_id, actor="sistema:auto-enroll",
                funnel_id=profile.default_entry_funnel_id, client_id=client_id,
            )
        except service.FunnelError:
            logger.warning(
                "[funnels:on_client_returned] reinscrição falhou tenant=%s funil=%s cliente=%s",
                tenant_id, profile.default_entry_funnel_id, client_id,
            )
            return
        record_event(
            db, tenant_id=tenant_id, client_id=client_id, kind=CRM_FUNIL_INSCRITO,
            title="Reinscrito no funil de entrada", actor="sistema:auto-enroll",
        )
        db.commit()


def register() -> None:
    """Liga os assinantes do barramento. Chamado uma vez no boot (app.main)."""
    events.subscribe(EVENT_CLIENT_CREATED, on_client_created)
    events.subscribe(EVENT_CLIENT_RETURNED, on_client_returned)
