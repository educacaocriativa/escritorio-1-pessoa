"""Guarda de regressão ESTÁTICA (Story 1.2, Task 1 / AC1).

Varre `apps/api/app/modules/**/router.py` e falha se algum módulo FORA da allowlist referenciar
`get_db` (a sessão GLOBAL, sem tenant). Módulos de negócio comuns (agenda, crm, receivables,
payables, products, stock, funnels, marketing, juridico, attachments, notifications, settings,
cockpit) DEVEM usar `get_tenant_db` (RLS) — nunca `get_db` — para não vazar dados cross-tenant.

Não substitui a RLS; é uma rede de segurança barata (sem ferramenta externa) contra a regressão
"alguém acessou `users`/dados sem escopo de tenant via get_db".

Allowlist (usos legítimos, documentados com guarda explícita no próprio código):
  - auth        → autenticação, inerentemente global sobre `users` (login por e-mail).
  - platform    → Super Admin (Master), toda rota sob `require_platform_admin` (cross-tenant).
  - contracts   → só a rota pública `public_view` lê `published_contracts` (snapshot global).
  - pages       → idem, `public_view` lê `published_pages`.
  - quotes      → idem, aceite público lê `published_proposals`.
  - wallet      → rotas de Master (earnings/split-rates) sob `require_platform_admin`.
  - attachments → só a rota pública `serve_public_image` lê `public_images` (tabela GLOBAL sem
                  RLS, imagens intencionalmente públicas — Story 4.2). `Attachment` permanece
                  100% RLS via `get_tenant_db`; nenhuma rota pública toca boletos/contratos.
  - integrations → idem, `capture_lead` (API pública de captura de lead) resolve a chave via
                  `public_integration_keys` (snapshot GLOBAL sem RLS) antes de abrir a
                  tenant_session real — mesmo padrão de pages/quotes/contracts.
  - whatsapp_inbox → idem, `verify_webhook`/`receive_webhook` (webhook público da Meta) resolvem
                  o tenant via `public_whatsapp_accounts` (snapshot GLOBAL sem RLS) pelo
                  `phone_number_id`/`verify_token` antes de abrir a tenant_session real — mesmo
                  padrão de pages/quotes/contracts/integrations.
  - device_tokens  → tabela GLOBAL sem RLS (nenhuma proteção por tenant). Isolamento vem do
                  filtro explícito por `user_id` do JWT nas rotas (`get_current_user` fornece o
                  `user_id` dos claims). Tabela contém apenas o hash sha256 do token (não o token
                  em si — sha256 é hash, não criptografia; não é reversível) e metadata —
                  nenhum dado de negócio.
"""
from __future__ import annotations

import pathlib

MODULES_DIR = pathlib.Path(__file__).resolve().parents[1] / "app" / "modules"

# Módulos onde `get_db` (sessão global) é um uso legítimo e já auditado (ver docstring acima).
ALLOWLIST = {
    "auth", "platform", "contracts", "pages", "quotes", "wallet", "attachments", "integrations",
    "whatsapp_inbox", "device_tokens",
}


def _module_routers() -> list[pathlib.Path]:
    """Todo arquivo de ROTA de um módulo — não só o que se chama exatamente `router.py`.

    ⚠️ **Corrigido no re-gate do Epic 8 (2026-07-30).** O glob era `*/router.py`, que não casava
    com `app/modules/payables/receipts_router.py` — um router **real e montado**
    (`app/modules/__init__.py:31`), invisível para esta guarda. A docstring do módulo sempre disse
    `**/router.py`; era a implementação que discordava dela.

    Provado por mutação: com `from app.db.session import get_db` dentro de `receipts_router.py`,
    esta suíte passava (`2 passed`). Hoje **não há violação** — aquele arquivo usa `get_tenant_db`
    e `get_receipt_db` (que abre `tenant_session(user.tenant_id)`) —, então ampliar o alcance é
    grátis: verificado que nenhum módulo fora da ALLOWLIST cita `get_db`, inclusive se a varredura
    cobrisse **todo** `.py` de `app/modules/`.

    O ponto cego que **permanece**: a guarda só olha arquivos de rota. Um `service.py` que abrisse
    sessão global continuaria passando. Registrado como follow-up no gate — hoje ninguém o faz, e
    ampliar para todo `.py` traria falso positivo de docstring (a guarda é substring, não sabe
    distinguir código de prosa: `platform/service.py:269` e `whatsapp_inbox/service.py:86` citam
    `get_db` em texto, e só não trombam porque os dois módulos estão na ALLOWLIST).
    """
    routers = sorted(
        p
        for p in MODULES_DIR.rglob("*.py")
        if "router" in p.name and "__pycache__" not in p.parts
    )
    assert routers, f"Nenhum arquivo de rota encontrado em {MODULES_DIR} — teste desatualizado?"
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
