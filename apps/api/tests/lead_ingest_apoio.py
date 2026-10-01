"""Apoio compartilhado dos testes da ingestão de leads.

Não é coletado pelo pytest (não começa com `test_`). Importe com
`from tests.lead_ingest_apoio import ...`, como `test_fuso_do_processo.py` faz com o conftest.
"""
from __future__ import annotations

import copy
from typing import Any

from app.modules.lead_ingest.schemas import IngestIn

TENANT = "tenant-nexus-0001"

TOQUE: dict[str, Any] = {
    "utm_source": "instagram",
    "utm_medium": "organic_social",
    "utm_campaign": "publia-lanc-out26",
    "utm_content": "ig-r-c8abc",
    "utm_term": None,
    "gclid": None,
    "fbclid": "fb.1.abc",
    "landing_path": "/publia-vender",
    "referrer_host": "l.instagram.com",
    "ocorrido_em": "2026-09-30T10:00:00-03:00",
}

# O JSON do §6.1, com valores concretos no lugar das reticências.
EXEMPLO_DA_SPEC: dict[str, Any] = {
    "evento": "compra_aprovada",
    "chave_idempotencia": "kiwify:ord_123:compra_aprovada",
    "ocorrido_em": "2026-10-02T14:31:00-03:00",
    "contato": {
        "nome": "Maria Prefeitura",
        "email": "maria@exemplo.gov.br",
        "telefone": "(11) 99999-8888",
    },
    "tags": [
        "origem:instagram",
        "meio:organico",
        "campanha:publia-lanc-out26",
        "post:ig-r-c8abc",
        "publia:comprou-essencial-anual",
    ],
    "atribuicao": {"situacao": "resolvida", "primeiro_toque": TOQUE, "ultimo_toque": TOQUE},
    "pedido": {
        "provedor": "kiwify",
        "order_id": "ord_123",
        "plano": "essencial",
        "periodo": "anual",
        "valor_bruto_centavos": 49900,
        "valor_liquido_centavos": 44300,
    },
}

LEAD: dict[str, Any] = {
    "evento": "lead",
    "chave_idempotencia": "site:lead:1",
    "ocorrido_em": "2026-10-02T14:31:00-03:00",
    "contato": {
        "nome": "Maria Prefeitura",
        "email": "maria@exemplo.gov.br",
        "telefone": "(11) 99999-8888",
    },
    "tags": ["origem:instagram", "post:ig-r-c8abc"],
    "atribuicao": {
        "situacao": "resolvida",
        "ultimo_toque": {"utm_source": "instagram", "utm_content": "ig-r-c8abc"},
    },
}


def corpo(**sobre: Any) -> dict[str, Any]:
    """O JSON de um `lead`, com os campos de `sobre` substituídos."""
    base = copy.deepcopy(LEAD)
    base.update(sobre)
    return base


def payload(**sobre: Any) -> IngestIn:
    return IngestIn.model_validate(corpo(**sobre))


def usar_sessao_do_teste(db, monkeypatch) -> None:
    """Faz os assinantes do barramento (`automation`) usarem a sessão do teste, não uma nova."""
    from contextlib import contextmanager

    from app.modules.funnels import automation

    @contextmanager
    def _fabrica(_tenant_id):
        yield db

    monkeypatch.setattr(automation, "tenant_session", _fabrica)
