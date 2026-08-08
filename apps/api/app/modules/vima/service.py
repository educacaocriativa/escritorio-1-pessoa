"""Monta o briefing do dia: coleta, compõe, narra e grava — uma vez por usuário por dia.

A idempotência é a razão de a tabela existir. Sem ela, cada F5 da tela seria uma narração
paga, e o texto mudaria a cada leitura — o dono não conseguiria voltar ao briefing que leu de
manhã e reencontrar as mesmas palavras.

⚠️ "Hoje" vem SEMPRE de `hoje_do_tenant(db)`. `datetime.now(UTC).date()` aqui devolveria o dia
seguinte entre 21h e meia-noite, e o briefing das 21h30 seria gravado como o de amanhã —
apagando o de amanhã de verdade por causa da unique key.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.facts import Fact
from app.core.tenancy import CurrentUser
from app.modules.dna import resolver as dna_resolver
from app.modules.payables.models import Payable
from app.modules.quotes.models import Quote
from app.modules.receivables.models import Charge
from app.modules.settings.service import hoje_do_tenant
from app.modules.vima import absences, composer, narrator, trends
from app.modules.vima.models import Briefing
from app.modules.vima.permissions import modulos_permitidos

# Teto da janela de leitura. Quem passou duas semanas sem abrir a tela não quer duas semanas de
# fatos — quer saber o que importa agora. Sem o teto, o primeiro briefing após as férias seria
# o mais caro e o menos legível de todos.
_JANELA_MAXIMA = timedelta(days=7)


class VimaError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def gerar_ou_ler(db: Session, *, user: CurrentUser, hoje: date | None = None) -> Briefing:
    """Devolve o briefing de hoje deste usuário, gerando-o se ainda não existir."""
    dia = hoje or hoje_do_tenant(db)
    existente = db.scalar(
        select(Briefing).where(
            Briefing.user_id == user.user_id, Briefing.reference_date == dia
        )
    )
    if existente is not None:
        return existente

    agora = datetime.now(UTC)
    desde = _inicio_da_janela(db, user=user, agora=agora)
    fatos = _fatos_da_janela(db, user=user, desde=desde)

    payload = composer.compor(
        fatos=fatos,
        ausencias=absences.coletar(
            db, user=user, hoje=dia, agora=agora,
            # O DNA da Empresa entra aqui, e só aqui. Sem resposta, o dicionário vem vazio e os
            # defaults conservadores do V1 continuam valendo.
            limiares=dna_resolver.limiares(db),
            ja_reportadas=_ja_reportadas(db, user=user),
        ),
        tendencias=trends.coletar(db, user=user, hoje=dia),
        valores=_valores_da_origem(db, fatos),
        referencia=agora,
        desde=desde,
    )
    narracao = narrator.narrar(
        db, tenant_id=user.tenant_id, payload=payload, nome_do_usuario=_primeiro_nome(db, user)
    )

    briefing = Briefing(
        tenant_id=user.tenant_id,
        user_id=user.user_id,
        reference_date=dia,
        payload=json.dumps(_serializar(payload), ensure_ascii=False),
        texto=narracao.texto,
        por_ia=narracao.por_ia,
        vazio=payload.sem_acontecimentos(),
    )
    db.add(briefing)
    db.commit()
    db.refresh(briefing)
    return briefing


def marcar_lido(db: Session, *, briefing_id: str, user: CurrentUser) -> Briefing:
    briefing = db.get(Briefing, briefing_id)
    # Um briefing de OUTRO usuário do mesmo tenant não é deste usuário para marcar: a RLS isola
    # tenants, não pessoas dentro do tenant.
    if briefing is None or briefing.user_id != user.user_id:
        raise VimaError("Briefing não encontrado", 404)
    if briefing.read_at is None:
        briefing.read_at = datetime.now(UTC)
        db.commit()
        db.refresh(briefing)
    return briefing


# ── Janela ──────────────────────────────────────────────────────────────────────────────


def _inicio_da_janela(db: Session, *, user: CurrentUser, agora: datetime) -> datetime:
    """Desde o último briefing que o usuário LEU, com teto de `_JANELA_MAXIMA`.

    É o briefing **lido**, e não o último gerado, porque um briefing gerado e não aberto não
    entregou notícia nenhuma: descontá-lo da janela perderia para sempre o que ele continha.
    """
    piso = agora - _JANELA_MAXIMA
    ultimo_lido = db.scalar(
        select(Briefing.created_at)
        .where(Briefing.user_id == user.user_id, Briefing.read_at.is_not(None))
        .order_by(Briefing.created_at.desc())
        .limit(1)
    )
    if ultimo_lido is None:
        return piso
    if ultimo_lido.tzinfo is None:  # SQLite devolve sem fuso; a comparação é sempre em UTC.
        ultimo_lido = ultimo_lido.replace(tzinfo=UTC)
    return max(piso, ultimo_lido)


def _fatos_da_janela(db: Session, *, user: CurrentUser, desde: datetime) -> list[Fact]:
    consulta = select(Fact).where(Fact.occurred_at >= desde)
    permitidos = modulos_permitidos(user)
    if permitidos is not None:
        # Filtra na CONSULTA, não na saída: um fato proibido que nunca é carregado não pode
        # vazar por esquecimento de filtro mais adiante (mesma disciplina de `absences`).
        consulta = consulta.where(Fact.module.in_(permitidos))
    return list(db.scalars(consulta.order_by(Fact.occurred_at.desc())).all())


def _ja_reportadas(db: Session, *, user: CurrentUser) -> dict[str, int]:
    """As ausências que o briefing anterior deste usuário já disse — a regra do silêncio.

    ⚠️ **Recalibrar zera o registro.** Se o dono aperta "card parado" de 10 para 5 dias e o
    briefing continua calado porque já disse aquilo ontem, a configuração parece quebrada — e a
    próxima que ele mexer, ele não acredita.

    A limpeza é GROSSA de propósito: derruba o silêncio de todas as regras, não só da que mudou.
    Mesma linha do fator 2 da escalada, "arbitrário e deliberadamente grosso". Discriminar por
    regra exigiria um mapa `kind`→limiar que existiria só para isto, e recalibrar é raro.
    """
    anterior = db.scalar(
        select(Briefing)
        .where(Briefing.user_id == user.user_id)
        .order_by(Briefing.reference_date.desc())
        .limit(1)
    )
    if anterior is None:
        return {}
    if dna_resolver.recalibrado_apos(db, anterior.reference_date):
        return {}
    try:
        dados = json.loads(anterior.payload)
    except (TypeError, ValueError):  # payload corrompido não pode calar o briefing de hoje
        return {}
    return {str(k): int(v) for k, v in (dados.get("ausencias_ditas") or {}).items()}


# ── Valores lidos da origem (Invariante 2) ──────────────────────────────────────────────


def _brl(cents: int) -> str:
    return f"R$ {cents / 100:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


def _valores_da_origem(db: Session, fatos: list[Fact]) -> dict[tuple[str, str], str]:
    """Lê o dinheiro de `charges`/`payables`/`quotes` pelo par `(subject_type, subject_id)`.

    O fato nunca guardou o valor (Invariante 2 de `core/facts`); é aqui que ele entra, na
    leitura, a partir da linha viva. Uma cobrança editada depois do fato aparece com o valor
    de agora — que é o certo: o briefing descreve o negócio, não um retrato congelado.

    Só os três tipos de sujeito que carregam dinheiro são resolvidos. `bank_transaction` ainda
    não tem emissor de fato nenhum; quando tiver, entra nesta tabela.
    """
    origens = {"charge": Charge, "payable": Payable, "quote": Quote}
    por_tipo: dict[str, set[str]] = {}
    for f in fatos:
        if f.subject_type in origens and f.subject_id:
            por_tipo.setdefault(f.subject_type, set()).add(f.subject_id)

    valores: dict[tuple[str, str], str] = {}
    for tipo, ids in por_tipo.items():
        modelo = origens[tipo]
        for linha in db.scalars(select(modelo).where(modelo.id.in_(ids))).all():
            valor = getattr(linha, "amount_cents", None)
            if valor is None:
                valor = getattr(linha, "total_cents", None)
            if valor is not None:
                valores[(tipo, linha.id)] = _brl(int(valor))
    return valores


# ── Serialização ────────────────────────────────────────────────────────────────────────


def _serializar(payload: composer.Payload) -> dict:
    """A evidência do que a IA recebeu, mais o que precisa sobreviver até o briefing seguinte.

    `ausencias_ditas` existe para a regra do silêncio: sem guardar quantos dias cada ausência
    tinha quando foi reportada, amanhã não há como saber se ela escalou.
    """
    return {
        "referencia": payload.referencia.isoformat() if payload.referencia else None,
        "desde": payload.desde.isoformat() if payload.desde else None,
        "excedente": payload.excedente,
        "linhas": [asdict(linha) for linha in payload.linhas],
        "ausencias_ditas": payload.ausencias_ditas,
    }


def _primeiro_nome(db: Session, user: CurrentUser) -> str:
    """O nome do dono para o cumprimento. Falha em silêncio para um genérico — um briefing não
    deixa de sair porque o cumprimento não resolveu."""
    from app.modules.auth.models import User

    try:
        pessoa = db.get(User, user.user_id)
    except Exception:  # noqa: BLE001
        return "você"
    if pessoa is None or not pessoa.name:
        return "você"
    return pessoa.name.split()[0]
