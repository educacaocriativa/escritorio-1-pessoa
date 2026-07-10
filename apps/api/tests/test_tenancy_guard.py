"""Guarda de regressão ESTÁTICA (Story 1.2, Task 1 / AC1).

Varre `apps/api/app/modules/**/router.py` e falha se algum módulo FORA da allowlist referenciar
`get_db` (a sessão GLOBAL, sem tenant). Módulos de negócio comuns (agenda, crm, receivables,
payables, products, stock, funnels, marketing, juridico, attachments, notifications, settings,
cockpit) DEVEM usar `get_tenant_db` (RLS) — nunca `get_db` — para não vazar dados cross-tenant.

Não substitui a RLS; é uma rede de segurança barata (sem ferramenta externa) contra a regressão
"alguém acessou `users`/dados sem escopo de tenant via get_db".

Allowlist (usos legítimos, documentados com guarda explícita no próprio código):
  - auth      → autenticação, inerentemente global sobre `users` (login por e-mail).
  - platform  → Super Admin (Master), toda rota sob `require_platform_admin` (cross-tenant).
  - contracts → só a rota pública `public_view` lê `published_contracts` (snapshot global).
  - pages     → idem, `public_view` lê `published_pages`.
  - quotes    → idem, aceite público lê `published_proposals`.
  - wallet    → rotas de Master (earnings/split-rates) sob `require_platform_admin`.
"""
from __future__ import annotations

import pathlib

MODULES_DIR = pathlib.Path(__file__).resolve().parents[1] / "app" / "modules"

# Módulos onde `get_db` (sessão global) é um uso legítimo e já auditado (ver docstring acima).
ALLOWLIST = {"auth", "platform", "contracts", "pages", "quotes", "wallet"}


def _module_routers() -> list[pathlib.Path]:
    routers = sorted(MODULES_DIR.glob("*/router.py"))
    assert routers, f"Nenhum router.py encontrado em {MODULES_DIR} — teste desatualizado?"
    return routers


def test_no_business_module_uses_get_db():
    """Nenhum módulo de negócio fora da allowlist pode referenciar `get_db`."""
    offenders: list[str] = []
    for router in _module_routers():
        module = router.parent.name
        if module in ALLOWLIST:
            continue
        source = router.read_text(encoding="utf-8")
        if "get_db" in source:
            offenders.append(module)

    assert not offenders, (
        "Módulo(s) de negócio referenciando get_db (sessão GLOBAL, sem tenant) — risco de "
        f"vazamento cross-tenant: {sorted(offenders)}. Use get_tenant_db (RLS). Se o uso for "
        "legítimo (rota pública sobre snapshot global / rota de Master), documente e adicione à "
        "ALLOWLIST em tests/test_tenancy_guard.py."
    )


def test_allowlist_entries_still_exist():
    """A allowlist não pode apodrecer: todo módulo listado deve existir como pasta real."""
    missing = [m for m in ALLOWLIST if not (MODULES_DIR / m / "router.py").exists()]
    assert not missing, f"Allowlist referencia módulos inexistentes: {sorted(missing)}"
