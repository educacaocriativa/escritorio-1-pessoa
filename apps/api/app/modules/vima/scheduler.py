"""O job que gera o briefing no horário de cada usuário — no fuso do tenant.

⚠️ **O relógio é sempre INJETADO** (`agora=`). Um job que lê `datetime.now()` por conta própria só
é testável esperando o relógio da máquina chegar na hora certa, e o teste que sobra é o que não
pega a inversão de fuso. Mesma disciplina de `funnels.engine.tick` e `payables.promote_scheduled`.

⚠️ **"Já chegou o horário?" é comparação com a hora LOCAL do tenant**, nunca com UTC. Às 07:05 UTC
ainda são 04:05 em São Paulo: comparar em UTC entregaria o briefing das 7h às 4 da manhã, todo
dia, para todo tenant brasileiro.

**Assinatura por TENANT, e não a `tick(db_factory)` do plano.** O worker já itera tenants e abre
uma sessão por etapa, com isolamento de falha por tenant (uma falha não trava as demais). Um
segundo laço de tenants aqui dentro duplicaria essa estrutura e teria o seu próprio — e diferente
— tratamento de falha.
"""
from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.tenancy import CurrentUser
from app.core.tz import tenant_zone
from app.modules.auth.models import User
from app.modules.settings.service import hoje_do_tenant, tenant_timezone
from app.modules.vima import service
from app.modules.vima.models import Briefing

logger = logging.getLogger("e1p.vima")

# Usado quando `briefing_hour` está ilegível no banco. As rotas validam por regex, então isto só
# alcança linha escrita fora da API — e ficar de fora do briefing em silêncio seria pior do que
# recebê-lo no horário padrão.
HORA_PADRAO = "07:00"


def tick(db: Session, *, tenant_id: str, agora: datetime) -> int:
    """Gera o briefing de hoje de cada usuário deste tenant cujo horário já chegou.

    Devolve quantos foram **gerados agora** — não quantos existem. Rodar de novo no mesmo dia é
    no-op (a unique key `(tenant, usuário, dia)` já garantia a idempotência; aqui ela não é nem
    exercitada, porque o briefing existente é lido antes).
    """
    fuso = tenant_timezone(db)
    local = agora.astimezone(tenant_zone(fuso))
    hoje = hoje_do_tenant(db, now=agora)

    gerados = 0
    for user in _usuarios_ativos(db, tenant_id):
        if not _ja_chegou(user.briefing_hour, local):
            continue

        existente = db.scalar(
            select(Briefing).where(
                Briefing.user_id == user.id, Briefing.reference_date == hoje
            )
        )
        if existente is None:
            service.gerar_ou_ler(db, user=_como_ator(user), hoje=hoje)
            gerados += 1

    db.commit()
    return gerados


def _usuarios_ativos(db: Session, tenant_id: str) -> list[User]:
    """⚠️ `users` é tabela GLOBAL, SEM RLS — o filtro por `tenant_id` aqui é explícito e
    obrigatório. É a exceção documentada da Regra de Ouro nº 1, a mesma de
    `whatsapp_inbox.service._e_telefone_da_equipe`."""
    return list(
        db.scalars(
            select(User)
            .where(User.tenant_id == tenant_id)
            .where(User.is_active.is_(True))
            .order_by(User.created_at, User.id)
        ).all()
    )


def _como_ator(user: User) -> CurrentUser:
    """O `CurrentUser` que o serviço espera. O `allowed_modules` vem do BANCO, não de um token:
    é ele que recorta quais fatos entram no briefing deste usuário (`vima/permissions.py`), e um
    token não existe num job."""
    return CurrentUser(
        user_id=user.id,
        tenant_id=user.tenant_id,
        role=user.role,
        allowed_modules=list(user.allowed_modules or []),
        is_platform_admin=user.is_platform_admin,
    )


def _ja_chegou(hora: str | None, local: datetime) -> bool:
    return _minutos(hora) <= local.hour * 60 + local.minute


def _minutos(hora: str | None) -> int:
    try:
        h, m = (hora or HORA_PADRAO).split(":")
        return int(h) * 60 + int(m)
    except (AttributeError, ValueError):
        logger.warning("[vima] briefing_hour ilegível (%r) — usando %s", hora, HORA_PADRAO)
        h, m = HORA_PADRAO.split(":")
        return int(h) * 60 + int(m)


__all__ = ["HORA_PADRAO", "tick"]
