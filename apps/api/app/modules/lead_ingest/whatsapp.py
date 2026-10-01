"""Origem do lead que chega pelo WhatsApp com código (spec §6.3).

Chamado pelo inbox (`whatsapp_inbox/service.py::ingest_webhook_payload`) na 1ª mensagem de um
contato que a PRÓPRIA mensagem criou. **NÃO commita**: roda dentro da transação-por-mensagem do
inbox — tag e fato entram junto com a mensagem, ou nenhum dos dois.

Desligado por padrão: só lê código o tenant que configurou um `produto` (`lead_ingest/config.py`).
Num produto multi-tenant, "código pt-..." numa conversa qualquer não pode virar etiqueta de origem
para quem nunca pôs link com código no ar.
"""
from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy.orm import Session

from app.core import facts
from app.core.facts import COM_ORIGEM_IDENTIFICADA
from app.modules.crm.models import Client
from app.modules.lead_ingest import config
from app.modules.lead_ingest.codigo import CodigoLido, ler_codigo
from app.modules.lead_ingest.tags import somar_tags
from app.modules.settings.models import TenantProfile

ATOR = "whatsapp:inbox"


def aplicar_codigo_da_primeira_mensagem(
    db: Session,
    *,
    tenant_id: str,
    cliente: Client,
    perfil: TenantProfile,
    texto: str | None,
    occurred_at: datetime | None,
) -> CodigoLido | None:
    prefixo = config.produto(perfil)
    if prefixo is None:
        return None
    lido = ler_codigo(texto)
    if lido is None:
        return None
    novas = [f"{prefixo}:lead-whatsapp"]
    if lido.origem is not None:
        novas = [f"origem:{lido.origem}", f"post:{lido.codigo}", *novas]
    cliente.tags, descartadas = somar_tags(cliente.tags, novas)
    facts.record(
        db,
        tenant_id=tenant_id,
        module="comercial",
        kind=COM_ORIGEM_IDENTIFICADA,
        title=f"Chegou pelo WhatsApp com o código {lido.codigo}",
        actor=ATOR,
        body=json.dumps(
            {"codigo": lido.codigo, "origem": lido.origem, "tags_descartadas": descartadas},
            ensure_ascii=False,
            indent=2,
        ),
        client_id=cliente.id,
        subject_type="client",
        subject_id=cliente.id,
        occurred_at=occurred_at,
    )
    return lido
