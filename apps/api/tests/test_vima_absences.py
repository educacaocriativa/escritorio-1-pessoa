"""Ausência = estado em aberto + relógio. Não vem do log, então funciona no dia 1."""
from datetime import UTC, date, datetime

import pytest
from sqlalchemy.orm import Session

from app.core.tenancy import CurrentUser
from app.modules.crm.models import Client, PipelineStage
from app.modules.payables.models import STATUS_OPEN, Payable
from app.modules.vima.absences import LIMIARES_PADRAO, coletar
from app.modules.whatsapp_inbox.models import (
    CHAT_KIND_DIRECT,
    DIRECTION_IN,
    WhatsappChat,
    WhatsappMessage,
)

TENANT = "t1"
HOJE = date(2026, 8, 6)


@pytest.fixture()
def usuario_owner() -> CurrentUser:
    return CurrentUser(
        user_id="u1", tenant_id=TENANT, role="owner",
        allowed_modules=[], is_platform_admin=False,
    )


@pytest.fixture()
def usuario_so_crm() -> CurrentUser:
    return CurrentUser(
        user_id="u2", tenant_id=TENANT, role="sub_user",
        allowed_modules=["crm"], is_platform_admin=False,
    )


@pytest.fixture()
def conta_vencendo_amanha(db: Session) -> Payable:
    conta = Payable(
        tenant_id=TENANT, description="Aluguel da sala", supplier="Imobiliária Alfa",
        amount_cents=250_000, due_date=date(2026, 8, 7), status=STATUS_OPEN,
    )
    db.add(conta)
    db.commit()
    return conta


def _chat(db: Session, *, jid: str, titulo: str) -> WhatsappChat:
    chat = WhatsappChat(
        tenant_id=TENANT, chat_jid=jid, kind=CHAT_KIND_DIRECT, title=titulo
    )
    db.add(chat)
    db.flush()
    return chat


@pytest.fixture()
def conversa_esperando_resposta(db: Session) -> WhatsappChat:
    """Última mensagem é `in`, posterior ao corte de autoria, e mais velha que o limiar."""
    chat = _chat(db, jid="5511999998888@s.whatsapp.net", titulo="Carlos")
    db.add(
        WhatsappMessage(
            tenant_id=TENANT, chat_id=chat.id, direction=DIRECTION_IN,
            text_body="Bom dia, conseguiu ver aquilo?",
            created_at=datetime(2026, 8, 5, 10, 0, tzinfo=UTC),
        )
    )
    db.commit()
    return chat


@pytest.fixture()
def conversa_antiga_toda_in(db: Session) -> WhatsappChat:
    """Conversa inteira anterior ao corte — gravada como `in` por defeito, não por autoria."""
    chat = _chat(db, jid="5511977776666@s.whatsapp.net", titulo="Marta")
    for dia in (18, 19, 20):
        db.add(
            WhatsappMessage(
                tenant_id=TENANT, chat_id=chat.id, direction=DIRECTION_IN,
                text_body="mensagem legada",
                created_at=datetime(2026, 7, dia, 9, 0, tzinfo=UTC),
            )
        )
    db.commit()
    return chat


@pytest.fixture()
def card_parado_ha_12_dias(db: Session) -> Client:
    etapa = PipelineStage(tenant_id=TENANT, name="Em contato", position=1)
    db.add(etapa)
    db.flush()
    card = Client(
        id="c1", tenant_id=TENANT, name="Carlos", stage_id=etapa.id,
        stage_entered_at=datetime(2026, 7, 25, 12, 0, tzinfo=UTC),
    )
    db.add(card)
    db.commit()
    return card


@pytest.fixture()
def briefing_de_ontem_com_o_card() -> dict[str, int]:
    """O que o briefing anterior já reportou: chave `{kind}:{subject_id}` → `dias` de então."""
    return {"comercial.card.parado:c1": 12}


def test_boleto_que_vence_amanha_aparece(db, usuario_owner, conta_vencendo_amanha):
    ausencias = coletar(db, user=usuario_owner, hoje=HOJE).ditas
    kinds = [a.kind for a in ausencias]
    assert "financeiro.conta.vencendo" in kinds


def test_sub_usuario_de_crm_nao_recebe_ausencia_financeira(
    db, usuario_so_crm, conta_vencendo_amanha
):
    """A regra financeira NÃO RODA para ele — não é calculada e escondida."""
    ausencias = coletar(db, user=usuario_so_crm, hoje=HOJE).ditas
    assert all(a.module != "financeiro" for a in ausencias)


def test_contato_sem_resposta_nossa_aparece(db, usuario_owner, conversa_esperando_resposta):
    """A última mensagem é `in` e passaram mais horas que o limiar."""
    ausencias = coletar(db, user=usuario_owner, hoje=HOJE).ditas
    assert any(a.kind == "comercial.contato.esperando_resposta" for a in ausencias)


def test_ignora_mensagens_anteriores_a_correcao_de_autoria(
    db, usuario_owner, conversa_antiga_toda_in
):
    """As mensagens gravadas antes da correção entraram TODAS como `in` e não têm conserto
    retroativo — `fromMe` nunca foi persistido. Lê-las como direção real produziria ausência
    falsa em toda conversa antiga."""
    ausencias = coletar(db, user=usuario_owner, hoje=HOJE).ditas
    assert not any(a.kind == "comercial.contato.esperando_resposta" for a in ausencias)


def test_card_parado_usa_stage_entered_at(db, usuario_owner, card_parado_ha_12_dias):
    """Mesma coluna que ordena a fila do Kanban (0068), segundo propósito, campo nenhum novo."""
    ausencias = coletar(db, user=usuario_owner, hoje=HOJE).ditas
    parado = next(a for a in ausencias if a.kind == "comercial.card.parado")
    assert parado.dias == 12


def test_topo_seco_quando_nao_ha_formulario_na_janela(db, usuario_owner):
    ausencias = coletar(db, user=usuario_owner, hoje=HOJE).ditas
    assert any(a.kind == "comercial.topo.sem_lead" for a in ausencias)


def test_limiares_sao_injetaveis(db, usuario_owner, card_parado_ha_12_dias):
    """O V2 (DNA da Empresa) substitui os defaults — 'você gosta de responder rápido?' É o
    limiar de 'você esqueceu de responder Carlos'."""
    ausencias = coletar(
        db, user=usuario_owner, hoje=HOJE,
        limiares={**LIMIARES_PADRAO, "card_parado_dias": 30},
    ).ditas
    assert not any(a.kind == "comercial.card.parado" for a in ausencias)


def test_ausencia_ja_reportada_nao_reincide(db, usuario_owner, card_parado_ha_12_dias,
                                            briefing_de_ontem_com_o_card):
    """A regra do silêncio: reportada ao CRUZAR o limiar, não enquanto permanece cruzada.

    Se o briefing repetir as mesmas pendências todo dia, em duas semanas virou papel de parede
    e o dono lê por cima — inclusive no dia em que aparece a quinta. É a Regra 7 do Epic 8 em
    outro domínio: "dentro da banda: verde e SILÊNCIO".
    """
    ausencias = coletar(db, user=usuario_owner, hoje=HOJE,
                        ja_reportadas=briefing_de_ontem_com_o_card).ditas
    assert not any(a.kind == "comercial.card.parado" for a in ausencias)


def test_ausencia_reincide_quando_escala(db, usuario_owner, card_parado_ha_12_dias,
                                         briefing_de_ontem_com_o_card):
    """Escalada é notícia nova: cruzou 3 dias, agora são 12."""
    ausencias = coletar(
        db, user=usuario_owner, hoje=HOJE,
        ja_reportadas={**briefing_de_ontem_com_o_card, "comercial.card.parado:c1": 3},
    ).ditas
    assert any(a.kind == "comercial.card.parado" for a in ausencias)


def test_conta_a_pagar_usa_o_limiar_proprio_e_nao_o_do_prazo(db: Session, usuario_owner):
    """Prazo de entrega se quer saber em cima; boleto, com folga para ter o dinheiro.

    Um número só para as duas coisas é a fusão que o DNA torna insustentável ao perguntar em
    voz alta.
    """
    db.add(
        Payable(
            tenant_id=TENANT, description="Aluguel", amount_cents=250_000,
            due_date=date(2026, 8, 11), status=STATUS_OPEN,
        )
    )
    db.commit()

    # Antecedência curta: a conta de daqui a 5 dias ainda não é notícia.
    curto = coletar(
        db, user=usuario_owner, hoje=HOJE,
        limiares={"prazo_vencendo_dias": 7, "dinheiro_com_data_dias": 1},
    ).ditas
    assert not [a for a in curto if a.kind == "financeiro.conta.vencendo"]

    # Antecedência longa: agora é.
    longo = coletar(
        db, user=usuario_owner, hoje=HOJE,
        limiares={"prazo_vencendo_dias": 0, "dinheiro_com_data_dias": 7},
    ).ditas
    assert [a for a in longo if a.kind == "financeiro.conta.vencendo"]


def test_topo_seco_desligado_nao_roda_a_regra(db: Session, usuario_owner):
    """`None` = regra NÃO EXECUTADA, não "limiar infinito".

    É a mesma forma do filtro de permissão do V1: não roda em vez de calcular e esconder. Se o
    `None` chegasse a `timedelta(days=...)`, o briefing estouraria com TypeError para todo dono
    que desligasse o aviso — e desligar é justamente o que a única pergunta com essa opção
    oferece.
    """
    ligado = coletar(db, user=usuario_owner, hoje=HOJE).ditas
    assert [a for a in ligado if a.kind == "comercial.topo.sem_lead"]

    desligado = coletar(
        db, user=usuario_owner, hoje=HOJE, limiares={"topo_sem_lead_dias": None}
    ).ditas
    assert not [a for a in desligado if a.kind == "comercial.topo.sem_lead"]
