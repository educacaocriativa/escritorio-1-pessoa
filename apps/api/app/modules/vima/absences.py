"""As cinco famílias de Ausência: o que NÃO aconteceu.

Ausência não vem do log — vem do **estado em aberto mais um relógio**. Isso tem uma
consequência boa: ela funciona no dia 1, sem depender de backfill nenhum. O briefing nasce
fraco em Fato e completo em Ausência.

`hoje` é PARÂMETRO OBRIGATÓRIO, nunca lido do relógio aqui dentro — mesma disciplina de
`payables.is_overdue`, que exige `today`. Um default que lê o relógio é exatamente por onde o
fuso errado volta.

Os limiares são injetáveis porque o V2 (DNA da Empresa) vai substituí-los: "você gosta de
responder rápido?" é literalmente o limiar de `contato.esperando_resposta`. Os defaults são
conservadores de propósito — pela assimetria de credibilidade, uma regra que dispara demais
custa mais caro que uma que não dispara.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.facts import COM_FORMULARIO_RECEBIDO, Fact
from app.core.tenancy import CurrentUser
from app.modules.agenda.models import (
    KIND_PRAZO,
    STATUS_CANCELLED,
    STATUS_DONE,
    AgendaEvent,
)
from app.modules.crm.models import Client, PipelineStage
from app.modules.payables.models import STATUS_OPEN as PAYABLE_ABERTA
from app.modules.payables.models import Payable
from app.modules.receivables.models import STATUS_OPEN as COBRANCA_ABERTA
from app.modules.receivables.models import Charge
from app.modules.vima.permissions import pode_ver
from app.modules.whatsapp_inbox.models import (
    DIRECTION_IN,
    WhatsappChat,
    WhatsappMessage,
)

# A correção de autoria (`fromMe` → `direction`) entrou nesta data. Mensagens anteriores estão
# TODAS gravadas como `in` e não têm conserto retroativo. Ler direção sobre elas produziria
# ausência falsa em toda conversa antiga do sistema.
CORTE_AUTORIA = datetime(2026, 8, 5, tzinfo=UTC)

LIMIARES_PADRAO: dict[str, int] = {
    "sem_resposta_nossa_horas": 24,
    "contato_sumido_dias": 30,
    "card_parado_dias": 10,
    "topo_sem_lead_dias": 5,
    "prazo_vencendo_dias": 1,
    # Nasce com o MESMO valor de `prazo_vencendo_dias` porque hoje as duas regras dividem
    # aquele número. Quem passa a lê-lo é `_dinheiro_com_data` — aqui a chave existe para que
    # o catálogo do DNA possa apontar para ela.
    "dinheiro_com_data_dias": 1,
}


@dataclass(frozen=True)
class Ausencia:
    module: str
    kind: str
    title: str
    dias: int
    subject_type: str | None = None
    subject_id: str | None = None
    client_id: str | None = None


def _brl(cents: int) -> str:
    """Ausência lê o valor da ORIGEM no instante da leitura, então pode carregá-lo no título.

    É o oposto do `Fact`, cuja Invariante 2 proíbe dinheiro no `title` justamente porque o fato
    é texto congelado: guardá-lo ali criaria uma segunda versão da verdade sobre dinheiro. Aqui
    o número nasce e morre nesta função, a partir da linha viva de `payables`/`charges`.
    """
    return f"R$ {cents / 100:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


def coletar(
    db: Session,
    *,
    user: CurrentUser,
    hoje: date,
    limiares: dict[str, int] | None = None,
    ja_reportadas: dict[str, int] | None = None,
    agora: datetime | None = None,
) -> list[Ausencia]:
    """Roda apenas as regras dos módulos que o usuário pode ver.

    `agora` existe porque um dos limiares é em HORAS ("ninguém respondeu o Carlos há 24h") e
    `hoje` sozinho não o resolve. O default é o fim de `hoje` — o instante mais tardio
    compatível com a data de referência —, e o serviço passa o relógio real. Como todo o resto
    deste módulo, o relógio entra por parâmetro: nada aqui dentro chama `now()`.
    """
    lim: dict[str, int | None] = {**LIMIARES_PADRAO, **(limiares or {})}
    instante = agora or datetime.combine(hoje, time.max, tzinfo=UTC)
    fora: list[Ausencia] = []

    if pode_ver(user, "agenda"):
        fora.extend(_prazos_estourados(db, hoje, lim))
    if pode_ver(user, "financeiro"):
        fora.extend(_dinheiro_com_data(db, hoje, lim))
    if pode_ver(user, "comercial"):
        fora.extend(_silencio_nosso(db, hoje, lim, instante))
        fora.extend(_contato_sumido(db, hoje, lim))
        fora.extend(_cards_parados(db, hoje, lim))
        # `None` significa REGRA NÃO EXECUTADA, não "limiar infinito" — mesma forma do filtro
        # de permissão, que não roda a regra em vez de calcular e esconder. Só topo seco pode
        # ser desligado, porque é a única que dispara sobre o VAZIO: sem cards não há card
        # parado, mas sem lead nenhum ela cutuca todo dia, para sempre.
        if lim.get("topo_sem_lead_dias") is not None:
            fora.extend(_topo_seco(db, hoje, lim))

    return [a for a in fora if not _ja_dita(a, ja_reportadas)]


def _ja_dita(ausencia: Ausencia, ja_reportadas: dict[str, int] | None) -> bool:
    """A regra do silêncio: reportada ao CRUZAR o limiar, não enquanto permanece cruzada.

    Escalada é notícia nova — quando os dias DOBRAM desde a última vez que a ausência foi dita,
    ela volta. O fator 2 é arbitrário e deliberadamente grosso: "parado há 3 dias" virando
    "parado há 4" não é informação, virando "parado há 12" é.
    """
    if not ja_reportadas:
        return False
    anterior = ja_reportadas.get(f"{ausencia.kind}:{ausencia.subject_id}")
    if anterior is None:
        return False
    return ausencia.dias < anterior * 2


# ── Agenda ──────────────────────────────────────────────────────────────────────────────


def _prazos_estourados(db: Session, hoje: date, lim: dict[str, int]) -> list[Ausencia]:
    """Prazo é a ausência mais cara do produto: perder um é irreversível."""
    limite = hoje + timedelta(days=lim["prazo_vencendo_dias"])
    eventos = db.scalars(
        select(AgendaEvent)
        .where(
            AgendaEvent.kind == KIND_PRAZO,
            AgendaEvent.status.notin_((STATUS_CANCELLED, STATUS_DONE)),
        )
        .order_by(AgendaEvent.starts_at)
    ).all()

    fora: list[Ausencia] = []
    for ev in eventos:
        # Evento de dia inteiro é gravado à meia-noite UTC da data de vencimento: compara-se por
        # DATA DE CALENDÁRIO, nunca por horário local (lição já paga pela Agenda — ver CLAUDE.md).
        dia = ev.starts_at.date()
        if dia > limite:
            continue
        dias = (hoje - dia).days
        quando = "venceu" if dias > 0 else "vence"
        fora.append(
            Ausencia(
                module="agenda", kind="agenda.prazo.estourado",
                title=f"Prazo “{ev.title}” {quando} em {dia.strftime('%d/%m')}",
                dias=dias, subject_type="agenda_event", subject_id=ev.id,
            )
        )
    return fora


# ── Financeiro ──────────────────────────────────────────────────────────────────────────


def _dinheiro_com_data(db: Session, hoje: date, lim: dict[str, int]) -> list[Ausencia]:
    """Conta a pagar e cobrança a receber que a data alcançou.

    ⚠️ As duas direções NÃO seguem a mesma regra, apesar de morarem juntas: conta a pagar tem
    antecedência (`due_date <= hoje + limiar`), cobrança a receber só aparece DEPOIS de vencida
    (`due_date < hoje`, sem limiar). Um recebimento que vence amanhã não é dito por ninguém —
    dívida registrada no spec do V2, e o motivo de a pergunta do DNA falar só de conta a pagar.

    O limiar é `dinheiro_com_data_dias`, próprio, e não mais o `prazo_vencendo_dias` da agenda:
    prazo de entrega se quer saber em cima, boleto se quer saber com folga para ter o dinheiro.
    """
    limite = hoje + timedelta(days=lim["dinheiro_com_data_dias"])
    fora: list[Ausencia] = []

    contas = db.scalars(
        select(Payable)
        .where(Payable.status == PAYABLE_ABERTA, Payable.due_date <= limite)
        .order_by(Payable.due_date)
    ).all()
    for conta in contas:
        dias = (hoje - conta.due_date).days
        quando = "venceu" if dias > 0 else "vence"
        alvo = conta.supplier or conta.description or "conta"
        fora.append(
            Ausencia(
                module="financeiro", kind="financeiro.conta.vencendo",
                title=f"{alvo} — {_brl(conta.amount_cents)} {quando} "
                      f"em {conta.due_date.strftime('%d/%m')}",
                dias=dias, subject_type="payable", subject_id=conta.id,
            )
        )

    cobrancas = db.scalars(
        select(Charge)
        .where(Charge.status == COBRANCA_ABERTA, Charge.due_date < hoje)
        .order_by(Charge.due_date)
    ).all()
    for cobranca in cobrancas:
        dias = (hoje - cobranca.due_date).days
        fora.append(
            Ausencia(
                module="financeiro", kind="financeiro.cobranca.vencida",
                title=f"{cobranca.description or 'Cobrança'} — {_brl(cobranca.amount_cents)} "
                      f"venceu há {dias} dia(s) e não foi paga",
                dias=dias, subject_type="charge", subject_id=cobranca.id,
                client_id=cobranca.client_id,
            )
        )
    return fora


# ── Comercial ───────────────────────────────────────────────────────────────────────────


def _ultimas_mensagens(db: Session) -> list[tuple[WhatsappChat, WhatsappMessage]]:
    """A última mensagem de cada conversa, ignorando o que é anterior ao corte de autoria.

    O corte vale para as duas regras que dependem desta leitura: antes dele nenhuma mensagem
    distingue as duas pontas da conversa, então tanto "ninguém respondeu" quanto "sumiu" seriam
    calculados sobre um dado que não existe.
    """
    ultima = (
        select(
            WhatsappMessage.chat_id.label("chat_id"),
            func.max(WhatsappMessage.created_at).label("quando"),
        )
        .where(
            WhatsappMessage.created_at >= CORTE_AUTORIA,
            WhatsappMessage.chat_id.is_not(None),
        )
        .group_by(WhatsappMessage.chat_id)
        .subquery()
    )
    linhas = db.execute(
        select(WhatsappChat, WhatsappMessage)
        .join(ultima, ultima.c.chat_id == WhatsappChat.id)
        .join(
            WhatsappMessage,
            (WhatsappMessage.chat_id == ultima.c.chat_id)
            & (WhatsappMessage.created_at == ultima.c.quando),
        )
    ).all()

    # Empate no instante devolveria a mesma conversa duas vezes; a primeira decide.
    vistas: dict[str, tuple[WhatsappChat, WhatsappMessage]] = {}
    for chat, msg in linhas:
        vistas.setdefault(chat.id, (chat, msg))
    return list(vistas.values())


def _nome_da_conversa(chat: WhatsappChat) -> str:
    return chat.title or "Contato não identificado"


def _silencio_nosso(
    db: Session, hoje: date, lim: dict[str, int], agora: datetime
) -> list[Ausencia]:
    """A última palavra foi do contato, e faz tempo. É a ausência de uma resposta NOSSA."""
    corte = agora - timedelta(hours=lim["sem_resposta_nossa_horas"])
    fora: list[Ausencia] = []
    for chat, msg in _ultimas_mensagens(db):
        if msg.direction != DIRECTION_IN:
            continue
        if _naive(msg.created_at) >= _naive(corte):
            continue
        dias = (hoje - msg.created_at.date()).days
        fora.append(
            Ausencia(
                module="comercial", kind="comercial.contato.esperando_resposta",
                title=f"{_nome_da_conversa(chat)} escreveu e ainda não foi respondido",
                dias=dias, subject_type="whatsapp_chat", subject_id=chat.id,
                client_id=chat.client_id,
            )
        )
    return fora


def _contato_sumido(db: Session, hoje: date, lim: dict[str, int]) -> list[Ausencia]:
    """Conversa que simplesmente parou — de qualquer lado."""
    fora: list[Ausencia] = []
    for chat, msg in _ultimas_mensagens(db):
        dias = (hoje - msg.created_at.date()).days
        if dias < lim["contato_sumido_dias"]:
            continue
        fora.append(
            Ausencia(
                module="comercial", kind="comercial.contato.sumido",
                title=f"{_nome_da_conversa(chat)} não fala com você há {dias} dias",
                dias=dias, subject_type="whatsapp_chat", subject_id=chat.id,
                client_id=chat.client_id,
            )
        )
    return fora


def _cards_parados(db: Session, hoje: date, lim: dict[str, int]) -> list[Ausencia]:
    """Card parado na mesma etapa. Etapa terminal (ganho/perdido) não conta: acabou."""
    limite = hoje - timedelta(days=lim["card_parado_dias"])
    cards = db.execute(
        select(Client, PipelineStage)
        .join(PipelineStage, PipelineStage.id == Client.stage_id)
        .where(
            PipelineStage.is_won.is_(False),
            PipelineStage.is_lost.is_(False),
            PipelineStage.is_archived.is_(False),
        )
        .order_by(Client.stage_entered_at)
    ).all()

    fora: list[Ausencia] = []
    for card, etapa in cards:
        entrou = card.stage_entered_at.date()
        if entrou > limite:
            continue
        dias = (hoje - entrou).days
        fora.append(
            Ausencia(
                module="comercial", kind="comercial.card.parado",
                title=f"{card.name} está em “{etapa.name}” há {dias} dias",
                dias=dias, subject_type="client", subject_id=card.id,
                client_id=card.id,
            )
        )
    return fora


def _topo_seco(db: Session, hoje: date, lim: dict[str, int]) -> list[Ausencia]:
    """Nenhum formulário na janela. É a única ausência que lê o log em vez do estado.

    Consequência assumida: enquanto o registro de fatos for novo, ela dispara por falta de
    histórico e não por falta de lead. É o preço de a regra existir no dia 1 — e ela se corrige
    sozinha assim que a janela de `topo_sem_lead_dias` couber inteira depois da implantação.
    """
    dias = lim["topo_sem_lead_dias"]
    desde = datetime.combine(hoje - timedelta(days=dias), time.min, tzinfo=UTC)
    quantos = db.scalar(
        select(func.count())
        .select_from(Fact)
        .where(Fact.kind == COM_FORMULARIO_RECEBIDO, Fact.occurred_at >= desde)
    )
    if quantos:
        return []
    return [
        Ausencia(
            module="comercial", kind="comercial.topo.sem_lead",
            title=f"Nenhum formulário recebido nos últimos {dias} dias",
            dias=dias, subject_type="tenant", subject_id="topo",
        )
    ]


def _naive(quando: datetime) -> datetime:
    """SQLite devolve datetime sem fuso; Postgres devolve com. Compara-se em UTC, sempre."""
    if quando.tzinfo is None:
        return quando
    return quando.astimezone(UTC).replace(tzinfo=None)
