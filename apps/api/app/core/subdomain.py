"""Resolução de tenant a partir do subdomínio (white-label por subdomínio — Story 4.4).

⚠️ SEGURANÇA (Regra de Ouro nº 1 — CLAUDE.md §3.1): o slug extraído do header `Host`
NUNCA deve alimentar a GUC `app.current_tenant_id` nem substituir o tenant vindo do JWT
validado (`app.core.tenancy.get_tenant_db`/`get_current_user`). O `Host` é um header
CONTROLADO PELO CLIENTE (qualquer requisição pode enviar `Host: outrotenant.e1p.com`,
independente do proxy), então usá-lo para autorização/isolamento de dados quebraria a RLS.

Este módulo serve APENAS para branding/UX em rotas PÚBLICAS (pré-selecionar o tenant
correto sem exigir o path `/p/:slug` completo). O isolamento de dados continua 100% no
JWT + RLS — `get_tenant_by_subdomain` jamais deve ser usado para autorizar leitura/escrita
de dado sensível.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.session import get_db

if TYPE_CHECKING:
    from app.modules.auth.models import Tenant


def extract_tenant_slug(host: str, root_domain: str) -> str | None:
    """Extrai o slug do tenant de um header `Host`, se ele for um subdomínio de `root_domain`.

    Retorna o primeiro rótulo (ex.: `joaosilva.e1p.com` → `"joaosilva"`) quando o host
    termina em `.{root_domain}` e não é o domínio raiz exato nem `www`. Caso contrário
    devolve `None` — preservando o comportamento atual (domínio único IV1/IV3), em que o
    `Host` não influencia o roteamento.

    Regras de parsing:
    - Case-insensitive (host e root_domain são normalizados para minúsculas).
    - Remove a porta se houver (`joaosilva.e1p.com:8000` → `"joaosilva"`), cobrindo dev local.
    - Domínio raiz exato (`e1p.com`) e `www.e1p.com` → `None`.
    - Domínio totalmente diferente (`outrapagina.com`) → `None`.
    - Subdomínio de dois níveis (`a.b.e1p.com`) → primeiro rótulo `"a"` (escolha simples;
      o produto não suporta subdomínios aninhados — não há orientação técnica em contrário).
    - `host`/`root_domain` vazios → `None` (fail-safe).
    """
    if not host or not root_domain:
        return None
    host = host.strip().lower()
    # Remove a porta (o host pode vir como `slug.e1p.com:8000` em dev/local).
    host = host.rsplit(":", 1)[0]
    root = root_domain.strip().lower().rstrip(".")
    if not host or not root or host == root:
        return None
    suffix = "." + root
    if not host.endswith(suffix):
        return None
    label = host[: -len(suffix)].split(".")[0]
    if not label or label == "www":
        return None
    return label


def get_tenant_by_subdomain(
    request: Request, db: Session = Depends(get_db)
) -> Tenant | None:
    """Dependency OPCIONAL: resolve o `Tenant` pelo subdomínio do `Host` (branding/UX).

    NÃO seta a GUC de tenant nem substitui `get_tenant_db` — ver o aviso de segurança no
    topo do módulo. Consulta a tabela GLOBAL `tenants` (sem RLS), a mesma já usada em
    `app/modules/auth/service.py`. Uso previsto: rotas públicas (`/public/...`) que, quando
    acessadas via `<slug>.e1p.com`, querem pré-selecionar o tenant para exibição — nunca
    para autorizar operações fora do fluxo público já validado por `public_slug`.
    """
    from app.modules.auth.models import Tenant

    slug = extract_tenant_slug(request.headers.get("host", ""), settings.root_domain)
    if not slug:
        return None
    return db.scalar(select(Tenant).where(Tenant.slug == slug))


__all__ = ["extract_tenant_slug", "get_tenant_by_subdomain"]
