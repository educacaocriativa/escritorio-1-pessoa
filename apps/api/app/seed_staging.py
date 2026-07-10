"""Semeia dados SINTÉTICOS para o ambiente de STAGING. Idempotente. Story 3.1.

Objetivo: dar ao ambiente de staging o mínimo de dados para o smoke test da esteira de
deploy (login + Agenda + CRM + Cockpit + Contas a Receber) ANTES de promover à produção,
sem tocar em dado real.

GATE DE SEGURANÇA (único): só roda quando `settings.seed_synthetic_data` é True — flag
`SEED_SYNTHETIC_DATA`, ausente/false em produção por padrão. Deliberadamente NÃO depende de
`settings.is_production`: staging roda com `ENVIRONMENT=production` (para espelhar 100% o
comportamento de produção — ver docs/stories/3.1.story.md, "Decisão de ENVIRONMENT em
staging"), então `is_production` seria sempre True e não serviria como gate.

RLS: o tenant e o usuário vivem em tabelas GLOBAIS (`tenants`/`users`, sem RLS) — criados
via `SessionLocal`, igual ao `app.seed`. Os registros de NEGÓCIO (Client, AgendaEvent,
Charge) são tabelas com RLS, então são criados dentro de `tenant_session(tenant_id)`, que
fixa a GUC `app.current_tenant_id` — sem isso o INSERT falharia (fail-closed) no Postgres
real, onde a app conecta como o papel não-superusuário `e1p_app`. Rode após as migrations e
o seed do Super Admin: `python -m app.seed_staging`.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select

from app.config import settings
from app.core.security import hash_password
from app.db.session import SessionLocal, tenant_session
from app.modules.agenda.models import (
    KIND_REUNIAO,
    STATUS_SCHEDULED,
    AgendaEvent,
)
from app.modules.auth.models import Tenant, User
from app.modules.crm.models import Client
from app.modules.crm.service import ensure_stages
from app.modules.receivables.models import METHOD_PIX, STATUS_OPEN, Charge

# Sentinelas de idempotência — reconhecemos o que já foi semeado por estes valores fixos.
STAGING_TENANT_SLUG = "staging-demo"
STAGING_OWNER_EMAIL = "owner@staging-demo.e1p.com"
STAGING_OWNER_PASSWORD = "staging-demo-owner"  # noqa: S105 (conta sintética de staging, não-prod)
STAGING_CLIENT_EMAIL = "cliente@staging-demo.e1p.com"
STAGING_EVENT_REF = "staging-seed-reuniao"
STAGING_CHARGE_REF = "staging-seed-cobranca"


def _ensure_tenant_and_owner() -> str:
    """Cria (idempotente) o tenant sintético + 1 usuário owner. Retorna o tenant_id.

    Tabelas globais (sem RLS) → sessão simples, mesmo padrão de `app.seed`.
    """
    db = SessionLocal()
    try:
        tenant = db.scalar(select(Tenant).where(Tenant.slug == STAGING_TENANT_SLUG))
        if tenant is None:
            tenant = Tenant(
                slug=STAGING_TENANT_SLUG,
                legal_name="Escritório Demo (staging)",
                document="00000000000",
            )
            db.add(tenant)
            db.flush()

        owner = db.scalar(select(User).where(User.email == STAGING_OWNER_EMAIL))
        if owner is None:
            db.add(
                User(
                    tenant_id=tenant.id,
                    email=STAGING_OWNER_EMAIL,
                    name="Dono Demo (staging)",
                    password_hash=hash_password(STAGING_OWNER_PASSWORD),
                    role="owner",
                    allowed_modules=[],
                    is_active=True,
                    is_platform_admin=False,
                    document="00000000191",  # CPF sentinela; único por tenant, sem colisão
                    phone="+5511999999999",
                    # Conta sintética de smoke test: NÃO força troca de senha, para o
                    # operador logar direto com STAGING_OWNER_PASSWORD durante a validação.
                    must_reset_password=False,
                )
            )
        db.commit()
        return tenant.id
    finally:
        db.close()


def _ensure_business_data(tenant_id: str) -> None:
    """Cria (idempotente) os registros mínimos de negócio dentro do tenant sintético.

    Tabelas de NEGÓCIO (RLS) → `tenant_session` fixa a GUC do tenant. Usamos o ORM (não
    INSERT cru) e o helper `ensure_stages` do CRM para respeitar os mesmos invariantes do
    resto do sistema. Volume deliberadamente MÍNIMO (só o necessário para o smoke test da
    AC2), para não virar um segundo catálogo de seed a manter a cada novo módulo.
    """
    with tenant_session(tenant_id) as db:
        # CRM: garante o funil padrão e coloca o cliente sintético na 1ª etapa (Entrada).
        stages = ensure_stages(db, tenant_id)
        entry_stage_id = stages[0].id if stages else None

        client = db.scalar(select(Client).where(Client.email == STAGING_CLIENT_EMAIL))
        if client is None:
            client = Client(
                tenant_id=tenant_id,
                name="Cliente Demo",
                email=STAGING_CLIENT_EMAIL,
                phone="+5511988888888",
                notes="Cliente sintético para o smoke test de staging (Story 3.1).",
                source="import",
                stage_id=entry_stage_id,
            )
            db.add(client)
            db.flush()

        # Agenda: 1 reunião amanhã (aparece no calendário do smoke test).
        existing_event = db.scalar(
            select(AgendaEvent).where(AgendaEvent.external_ref == STAGING_EVENT_REF)
        )
        if existing_event is None:
            start = datetime.now(UTC).replace(
                hour=14, minute=0, second=0, microsecond=0
            ) + timedelta(days=1)
            db.add(
                AgendaEvent(
                    tenant_id=tenant_id,
                    title="Reunião Demo (staging)",
                    description="Evento sintético para o smoke test de staging (Story 3.1).",
                    kind=KIND_REUNIAO,
                    status=STATUS_SCHEDULED,
                    source="manual",
                    starts_at=start,
                    ends_at=start + timedelta(hours=1),
                    external_ref=STAGING_EVENT_REF,
                )
            )

        # Contas a Receber: 1 cobrança em aberto ligada ao cliente sintético.
        existing_charge = db.scalar(
            select(Charge).where(Charge.external_ref == STAGING_CHARGE_REF)
        )
        if existing_charge is None:
            db.add(
                Charge(
                    tenant_id=tenant_id,
                    client_id=client.id,
                    description="Cobrança sintética para o smoke test de staging (Story 3.1).",
                    kind="service",
                    method=METHOD_PIX,
                    amount_cents=15000,  # R$150,00
                    due_date=date.today() + timedelta(days=7),
                    status=STATUS_OPEN,
                    external_ref=STAGING_CHARGE_REF,
                )
            )


def seed_synthetic_data() -> None:
    if not settings.seed_synthetic_data:
        print("[seed_staging] SEED_SYNTHETIC_DATA=false — nada a fazer.")
        return

    tenant_id = _ensure_tenant_and_owner()
    _ensure_business_data(tenant_id)
    print(f"[seed_staging] Dados sintéticos garantidos (tenant {STAGING_TENANT_SLUG}).")


if __name__ == "__main__":
    seed_synthetic_data()
