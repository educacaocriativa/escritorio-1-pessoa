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

from app.core import events
from app.db.session import tenant_session
from app.modules.crm.service import EVENT_CLIENT_CREATED
from app.modules.funnels import engine, service
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


def register() -> None:
    """Liga os assinantes do barramento. Chamado uma vez no boot (app.main)."""
    events.subscribe(EVENT_CLIENT_CREATED, on_client_created)
