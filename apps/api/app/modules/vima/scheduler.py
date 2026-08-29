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
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.phone import normalize_br
from app.core.tenancy import CurrentUser
from app.core.tz import day_window_utc, tenant_zone
from app.core.whatsapp import capabilities
from app.modules.auth.models import User
from app.modules.notifications import service as notifications
from app.modules.notifications.models import Notification
from app.modules.settings.models import TenantProfile
from app.modules.settings.service import hoje_do_tenant, tenant_timezone
from app.modules.vima import delivery, service
from app.modules.vima.models import Briefing
from app.modules.whatsapp_templates.models import (
    PAYLOAD_BOTAO_BRIEFING,
    PURPOSE_VIMA_BRIEFING,
    PURPOSE_VIMA_BRIEFING_TEXTO,
    WhatsappTemplate,
)

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

    ⚠️ **A entrega por WhatsApp acontece SÓ quando este tick gerou o briefing.** É o que impede o
    dono de receber a mesma mensagem a cada passada do sweep (que roda de minutos em minutos) até
    a meia-noite, sem precisar de coluna nova nem de aritmética de janela sobre `created_at`.
    O caso que isso deixa de fora é estreito e a troca é deliberada: quem abriu o app antes do
    próprio horário já teve o briefing gerado na tela — e a tela o marca como lido ao montar, que
    é exatamente quando mandar de novo seria eco.
    """
    fuso = tenant_timezone(db)
    local = agora.astimezone(tenant_zone(fuso))
    hoje = hoje_do_tenant(db, now=agora)

    gerados = 0
    for user in usuarios_ativos(db, tenant_id):
        if not _ja_chegou(user.briefing_hour, local):
            continue

        existente = db.scalar(
            select(Briefing).where(
                Briefing.user_id == user.id, Briefing.reference_date == hoje
            )
        )
        if existente is None:
            briefing = service.gerar_ou_ler(db, user=como_ator(user), hoje=hoje)
            gerados += 1
            _entregar_no_whatsapp(db, user=user, briefing=briefing)

    db.commit()
    return gerados


def usuarios_ativos(db: Session, tenant_id: str) -> list[User]:
    """⚠️ `users` é tabela GLOBAL, SEM RLS — o filtro por `tenant_id` aqui é explícito e
    obrigatório. É a exceção documentada da Regra de Ouro nº 1, a mesma de
    `whatsapp_inbox.service._e_telefone_da_equipe`.

    Pública porque tem dois consumidores desde a fatia do canal WhatsApp da Vima
    (`vima/whatsapp_conversa.py`) — antes disso, só este módulo a usava."""
    return list(
        db.scalars(
            select(User)
            .where(User.tenant_id == tenant_id)
            .where(User.is_active.is_(True))
            .order_by(User.created_at, User.id)
        ).all()
    )


def como_ator(user: User) -> CurrentUser:
    """O `CurrentUser` que o serviço espera. O `allowed_modules` vem do BANCO, não de um token:
    é ele que recorta quais fatos entram no briefing deste usuário (`vima/permissions.py`), e um
    token não existe num job.

    Pública pelo mesmo motivo de `usuarios_ativos` acima."""
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


def _entregar_no_whatsapp(db: Session, *, user: User, briefing: Briefing) -> None:
    """Enfileira o briefing no WhatsApp — em um passo ou dois, conforme o transporte.

    **Dia sem novidade não sai.** Um "bom dia, nada aconteceu" diário é a forma mais rápida de ser
    silenciado, e um canal silenciado não entrega o dia em que importa. A TELA continua dizendo
    que está tranquilo; é só o WhatsApp que fica quieto.

    Nunca levanta: uma falha de enfileiramento não pode custar o briefing dos usuários seguintes
    do mesmo tenant. O sweep já isola falha por TENANT (`worker.run_sweep`); aqui o isolamento é
    por USUÁRIO, um nível abaixo.
    """
    if not user.briefing_whatsapp_enabled or briefing.vazio:
        return

    # Mesmo veredito que a tela de preferências usa (`auth/router.py`). Cobre "sem telefone" e
    # "tenant Meta ainda sem template aprovado" — se divergissem, a tela diria "ligado" e o job
    # não mandaria nada, falha silenciosa dos dois lados.
    entrega = delivery.avaliar(db, phone=user.phone)
    if not entrega.disponivel:
        logger.info(
            "[vima] briefing de %s não sai no whatsapp: %s", user.id, entrega.motivo
        )
        return

    profile = db.scalar(select(TenantProfile))
    try:
        if capabilities.for_profile(profile).briefing_needs_optin:
            _aviso_com_botao(db, user=user, entrega=entrega)
        else:
            # Evolution: sem template e sem janela. O briefing INTEIRO, como texto livre.
            notifications.enqueue(
                db,
                tenant_id=user.tenant_id,
                channel="whatsapp",
                recipient=user.phone or "",
                message=briefing.texto,
                purpose=PURPOSE_VIMA_BRIEFING_TEXTO,
            )
    except Exception:  # noqa: BLE001 — ver docstring: isola a falha por usuário
        logger.exception("[vima] falha ao enfileirar o briefing de %s", user.id)


def _aviso_com_botao(db: Session, *, user: User, entrega: delivery.Entrega) -> None:
    """Meta, primeiro passo: o AVISO, não o briefing.

    Uma linha, sem quebra — parâmetro de template da Cloud API **não aceita `\\n`**, e o briefing
    tem várias. O que destrava o texto inteiro é o BOTÃO: o toque conta como mensagem do contato,
    abre a janela de 24h, e aí o texto sai livre (`responder_optin`).
    """
    template = db.get(WhatsappTemplate, entrega.template_id)
    if template is None:  # `avaliar` já garantiu que existe; guarda contra corrida de desvínculo
        return
    primeiro_nome = (user.name or "").split(" ")[0] or "você"
    notifications.enqueue(
        db,
        tenant_id=user.tenant_id,
        channel="whatsapp",
        recipient=user.phone or "",
        # O corpo renderizado é o que a tela de histórico mostra E o que sai como texto livre se
        # o tenant migrar para a Evolution antes da entrega (`process_pending` cai em `send_text`
        # quando o transporte não tem template).
        message=_render(template.body_text, [primeiro_nome]),
        purpose=PURPOSE_VIMA_BRIEFING,
        whatsapp_template_name=template.name,
        whatsapp_template_language=template.language,
        whatsapp_template_variables=[primeiro_nome],
    )


def _render(corpo: str, variaveis: list[str]) -> str:
    for i, valor in enumerate(variaveis, start=1):
        corpo = corpo.replace(f"{{{{{i}}}}}", valor)
    return corpo


def responder_optin(db: Session, *, tenant_id: str, phone: str | None) -> bool:
    """O dono tocou o botão: a janela de 24h abriu — manda o briefing inteiro, em texto livre.

    Chamado por `whatsapp_inbox.service.ingest_webhook_payload` quando reconhece o toque. Devolve
    se algo foi enfileirado.

    **Não commita.** Roda dentro da transação-por-mensagem do ingest, que commita a mensagem e o
    opt-in juntos — se o commit falhar, nenhum dos dois fica pela metade.

    ⚠️ **O toque precisa vir do telefone de um USUÁRIO deste tenant.** O payload do botão é uma
    constante conhecida, e um cliente qualquer poderia repeti-la: sem o vínculo com um usuário, o
    briefing do dono sairia para quem escrevesse a string certa. É a mesma guarda que impede o
    dono de virar lead do próprio funil (`whatsapp_inbox._e_telefone_da_equipe`), usada aqui para
    o outro lado da mesma decisão.
    """
    chave = normalize_br(phone) if phone else None
    if chave is None:
        return False

    user = next(
        (
            u
            for u in usuarios_ativos(db, tenant_id)
            if u.phone and normalize_br(u.phone) == chave
        ),
        None,
    )
    if user is None:
        return False

    briefing = db.scalar(
        select(Briefing).where(
            Briefing.user_id == user.id,
            Briefing.reference_date == hoje_do_tenant(db),
        )
    )
    # Toque atrasado (aviso de ontem, respondido hoje) não tem briefing de hoje para liberar — e
    # mandar o de ontem seria pior do que não mandar nada.
    if briefing is None or briefing.vazio:
        return False

    ja_saiu = db.scalar(
        select(Notification.id).where(
            Notification.purpose == PURPOSE_VIMA_BRIEFING_TEXTO,
            Notification.recipient == user.phone,
            Notification.created_at >= _inicio_do_dia(db, briefing.reference_date),
        )
    )
    # Dedo escorregando no celular não pode custar duas mensagens iguais.
    if ja_saiu is not None:
        return False

    notifications.enqueue(
        db,
        tenant_id=tenant_id,
        channel="whatsapp",
        recipient=user.phone or "",
        message=briefing.texto,
        purpose=PURPOSE_VIMA_BRIEFING_TEXTO,
    )
    return True


def _inicio_do_dia(db: Session, dia: date) -> datetime:
    """Meia-noite do tenant, em UTC — a fronteira certa para "já saiu hoje?"."""
    inicio, _fim = day_window_utc(dia, tenant_timezone(db))
    return inicio


__all__ = ["HORA_PADRAO", "PAYLOAD_BOTAO_BRIEFING", "responder_optin", "tick"]
