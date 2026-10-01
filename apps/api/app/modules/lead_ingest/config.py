"""Configuração da ingestão por tenant: `tenant_profiles.lead_ingest_config` (JSON).

Formato: `{"produto": "publia", "funis": {"lead": "<funnel_id>", ...}}`.

**Por que `produto` é configuração, e não `"publia"` no código.** A spec (§6.2/§6.3) fala em
`publia:reembolso`, `publia:cancelou`, `publia:lead-whatsapp` — tags do tenant Nexus. O e1p é
multi-tenant: cravar o produto de um cliente no núcleo faria toda empresa do produto receber
tag de outra. O prefixo vira dado do tenant; sem ele, essas tags simplesmente não existem.

**Por que o funil padrão NÃO vale para pós-venda.** "Sem mapeamento, vale o comportamento atual
(`default_entry_funnel_id`)" (spec §6.4) é sobre quem ENTRA: lead, carrinho, compra. Aplicar ao pé
da letra a renovação, reembolso, chargeback e cancelamento poria quem pediu o dinheiro de volta
na jornada de boas-vindas. Pós-venda só entra em funil se o dono mapear explicitamente.
"""
from __future__ import annotations

import re

from app.modules.settings.models import TenantProfile

EVENTOS = (
    "lead",
    "carrinho_abandonado",
    "compra_aprovada",
    "renovacao",
    "reembolso",
    "chargeback",
    "cancelamento",
)
EVENTOS_DE_ENTRADA = frozenset({"lead", "carrinho_abandonado", "compra_aprovada"})

# Cabe em `<produto>:lead-whatsapp` dentro dos 40 caracteres de tag do CRM.
_PRODUTO_VALIDO = re.compile(r"^[a-z0-9][a-z0-9-]{0,19}$")


def _config(perfil: TenantProfile) -> dict:
    valor = perfil.lead_ingest_config
    return valor if isinstance(valor, dict) else {}


def produto(perfil: TenantProfile) -> str | None:
    """O slug do produto, ou `None` (tag de produto e leitura de código desligadas)."""
    valor = _config(perfil).get("produto")
    if isinstance(valor, str) and _PRODUTO_VALIDO.match(valor):
        return valor
    return None


def validar_produto(valor: str) -> str:
    limpo = valor.strip().lower()
    if not _PRODUTO_VALIDO.match(limpo):
        raise ValueError(
            "produto deve ter de 1 a 20 caracteres: letras minúsculas, dígitos e hífen "
            "(ex.: publia)"
        )
    return limpo


def funil_do_evento(perfil: TenantProfile, evento: str) -> str | None:
    funis = _config(perfil).get("funis")
    mapeado = funis.get(evento) if isinstance(funis, dict) else None
    if isinstance(mapeado, str) and mapeado:
        return mapeado
    if evento in EVENTOS_DE_ENTRADA:
        return perfil.default_entry_funnel_id
    return None
