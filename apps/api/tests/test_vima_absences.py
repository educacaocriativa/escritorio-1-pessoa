"""Ausência = estado em aberto + relógio. Não vem do log, então funciona no dia 1."""
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.core.tenancy import CurrentUser
from app.modules.bank.models import (
    KIND_CHECKING,
    ORIGIN_MANUAL,
    BankAccount,
    BankBalanceCheckpoint,
)
from app.modules.crm.models import Client, PipelineStage
from app.modules.payables.models import STATUS_OPEN, Payable
from app.modules.receivables.models import STATUS_OPEN as CHARGE_OPEN
from app.modules.receivables.models import Charge
from app.modules.vima.absences import LIMIARES_PADRAO, clientes_em_atencao, coletar
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


def test_silencio_e_sumido_contam_certo_perto_da_meia_noite_utc(db, usuario_owner):
    """Mesmo achado de `test_card_parado_conta_certo_perto_da_meia_noite_utc`, agora para as
    duas regras que leem `WhatsappMessage.created_at` — 01h UTC de 06/08 é 22h de 05/08 em São
    Paulo (UTC-3): dia de calendário DIFERENTE do de `.date()` cru sobre o instante UTC.

    Precisa vir DEPOIS de `CORTE_AUTORIA` (05/08/2026, ver `_ultimas_mensagens`) para não ser
    filtrada por um motivo alheio a este teste — por isso `hoje`/`agora` ficam bem à frente
    (15/09), com folga sobre os dois limiares padrão (30 dias de `contato_sumido_dias`, 24h de
    `sem_resposta_nossa_horas`)."""
    chat = _chat(db, jid="5511955554444@s.whatsapp.net", titulo="Roberto")
    db.add(
        WhatsappMessage(
            tenant_id=TENANT, chat_id=chat.id, direction=DIRECTION_IN,
            text_body="oi, tudo bem?", created_at=datetime(2026, 8, 6, 1, 0, tzinfo=UTC),
        )
    )
    db.commit()

    ausencias = coletar(
        db, user=usuario_owner, hoje=date(2026, 9, 15),
        agora=datetime(2026, 9, 15, 2, 0, tzinfo=UTC),
    ).ditas

    # 15/09 - 05/08 (local) = 41, não 40 (15/09 - 06/08 UTC)
    silencio = next(a for a in ausencias if a.kind == "comercial.contato.esperando_resposta")
    assert silencio.dias == 41
    sumido = next(a for a in ausencias if a.kind == "comercial.contato.sumido")
    assert sumido.dias == 41


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


def test_card_parado_conta_certo_perto_da_meia_noite_utc(db, usuario_owner):
    """01h UTC de 25/07 é 22h de 24/07 em São Paulo (UTC-3, o fuso padrão) — dia de calendário
    DIFERENTE do de `stage_entered_at.date()` cru. Achado ao vivo no CI (madrugada de
    2026-09-01): comparar por essa data crua em vez de convertê-la pro fuso do tenant fazia a
    conta sair 1 dia curta (mesma janela de 3h se repete toda madrugada, `America/Sao_Paulo`)."""
    etapa = PipelineStage(tenant_id=TENANT, name="Em contato", position=1)
    db.add(etapa)
    db.flush()
    db.add(Client(
        id="c-madrugada", tenant_id=TENANT, name="Carlos", stage_id=etapa.id,
        stage_entered_at=datetime(2026, 7, 25, 1, 0, tzinfo=UTC),
    ))
    db.commit()
    ausencias = coletar(db, user=usuario_owner, hoje=HOJE).ditas
    parado = next(a for a in ausencias if a.kind == "comercial.card.parado")
    assert parado.dias == 13  # 06/08 - 24/07 (local) = 13, não 12 (06/08 - 25/07 UTC)


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


def _cobranca(db: Session, *, due: date, desc: str = "Mensalidade agosto") -> Charge:
    cobranca = Charge(
        tenant_id=TENANT, description=desc,
        kind="service", method="pix", amount_cents=200_000,
        due_date=due, status=CHARGE_OPEN,
    )
    db.add(cobranca)
    db.commit()
    return cobranca


def test_cobranca_avisa_antes_de_vencer(db: Session, usuario_owner):
    """A dívida que o V2 expôs: o dono era avisado do que DEVE e surpreendido pelo que não
    recebeu. Numa empresa de uma pessoa, é o dinheiro que entra que um toque antes do
    vencimento ainda salva."""
    _cobranca(db, due=date(2026, 8, 9))  # vence em 3 dias

    ausencias = coletar(db, user=usuario_owner, hoje=HOJE).ditas
    cobrancas = [a for a in ausencias if a.kind == "financeiro.cobranca.vencendo"]
    assert len(cobrancas) == 1
    assert "vence em 09/08" in cobrancas[0].title
    assert cobrancas[0].dias == -3


def test_cobranca_que_vence_hoje_diz_hoje(db: Session, usuario_owner):
    _cobranca(db, due=HOJE)

    (cobranca,) = [
        a
        for a in coletar(db, user=usuario_owner, hoje=HOJE).ditas
        if a.kind == "financeiro.cobranca.vencendo"
    ]
    assert "vence hoje" in cobranca.title
    assert cobranca.dias == 0


def test_cobranca_vencida_mantem_a_voz_de_vencida(db: Session, usuario_owner):
    """"não foi paga" é o estado que muda o que o dono faz, e continua distinto de propósito."""
    _cobranca(db, due=date(2026, 8, 3))

    (cobranca,) = [
        a
        for a in coletar(db, user=usuario_owner, hoje=HOJE).ditas
        if a.kind == "financeiro.cobranca.vencendo"
    ]
    assert "venceu há 3 dia(s) e não foi paga" in cobranca.title
    assert cobranca.dias == 3


def test_a_antecedencia_da_cobranca_tem_limiar_proprio(db: Session, usuario_owner):
    """Cutucar cliente e juntar dinheiro para pagar um boleto são intenções diferentes, e o
    dono responde as duas perguntas separadamente no DNA."""
    _cobranca(db, due=date(2026, 8, 12))  # vence em 6 dias

    curto = coletar(
        db, user=usuario_owner, hoje=HOJE,
        limiares={"cobranca_antecedencia_dias": 3, "dinheiro_com_data_dias": 7},
    ).ditas
    assert not [a for a in curto if a.kind == "financeiro.cobranca.vencendo"]

    longo = coletar(
        db, user=usuario_owner, hoje=HOJE,
        limiares={"cobranca_antecedencia_dias": 7, "dinheiro_com_data_dias": 0},
    ).ditas
    assert [a for a in longo if a.kind == "financeiro.cobranca.vencendo"]


def test_a_cadencia_inteira_de_uma_cobranca(db: Session, usuario_owner):
    """Aviso, vencimento, e depois dobrando: -3 -> 0 -> 1 -> 2 -> 4 -> 8.

    É a cadência que o dono do produto escolheu, e a prova de que os três ramos de
    `_proximo_marco` se encadeiam sobre um caso real de dinheiro.
    """
    _cobranca(db, due=date(2026, 8, 20))
    marcos: dict[str, int] = {}
    falados: list[date] = []

    for offset in range(-4, 17):
        hoje = date(2026, 8, 20) + timedelta(days=offset)
        coleta = coletar(db, user=usuario_owner, hoje=hoje, ja_reportadas=marcos)
        ditas = [a for a in coleta.ditas if a.kind == "financeiro.cobranca.vencendo"]
        marcos = dict(coleta.marcos_anteriores)
        for a in ditas:
            falados.append(hoje)
            marcos[f"{a.kind}:{a.subject_id}"] = a.dias

    assert falados == [
        date(2026, 8, 17),  # cruzou a antecedência de 3 dias
        date(2026, 8, 20),  # venceu
        date(2026, 8, 21),  # 1 dia
        date(2026, 8, 22),  # 2 dias
        date(2026, 8, 24),  # 4 dias
        date(2026, 8, 28),  # 8 dias
        date(2026, 9, 5),   # 16 dias
    ]


# ── O saldo do mês (o ciclo da conferência, Epic 8) ──────────────────────────────────────────


def _conta_bancaria(
    db: Session, *, nome: str = "Itaú PJ", abertura: date = date(2026, 6, 1), arquivada=None
) -> BankAccount:
    """Uma conta ativa aberta ANTES do mês fechado — senão ela não deve saldo daquele mês."""
    conta = BankAccount(
        tenant_id=TENANT, name=nome, kind=KIND_CHECKING,
        opening_balance_cents=100_000, opening_balance_is_known=True,
        opening_date=abertura, archived_at=arquivada,
    )
    db.add(conta)
    db.commit()
    return conta


def _saldo_declarado(db: Session, conta: BankAccount, *, quando: date) -> None:
    db.add(
        BankBalanceCheckpoint(
            tenant_id=TENANT, bank_account_id=conta.id,
            reference_date=quando, balance_cents=100_000, created_by="u1",
            origin=ORIGIN_MANUAL,
        )
    )
    db.commit()


def _kinds(db, usuario, *, hoje=HOJE, marcos=None) -> list[str]:
    return [a.kind for a in coletar(db, user=usuario, hoje=hoje, ja_reportadas=marcos).ditas]


def test_mes_fechado_sem_saldo_declarado_aparece(db, usuario_owner):
    """MEMBRO: conta ativa aberta em junho, julho fechado, nenhum saldo informado em julho."""
    _conta_bancaria(db)

    assert "financeiro.conferencia.saldo_do_mes" in _kinds(db, usuario_owner)


def test_nao_aparece_com_o_saldo_do_mes_declarado(db, usuario_owner):
    """NÃO-MEMBRO: o saldo de 31/07 já foi informado."""
    conta = _conta_bancaria(db)
    _saldo_declarado(db, conta, quando=date(2026, 7, 31))

    assert "financeiro.conferencia.saldo_do_mes" not in _kinds(db, usuario_owner)


def test_nao_aparece_para_conta_aberta_depois_do_mes(db, usuario_owner):
    """NÃO-MEMBRO: conta cadastrada em 02/08 não deve o saldo de julho — ela não era do dono."""
    _conta_bancaria(db, abertura=date(2026, 8, 2))

    assert "financeiro.conferencia.saldo_do_mes" not in _kinds(db, usuario_owner)


def test_nao_aparece_para_conta_arquivada(db, usuario_owner):
    """NÃO-MEMBRO: arquivada sai de `list_accounts`, e cobrar saldo dela seria pedir um ato que o
    dono decidiu não fazer mais."""
    _conta_bancaria(db, arquivada=datetime(2026, 8, 1, tzinfo=UTC))

    assert "financeiro.conferencia.saldo_do_mes" not in _kinds(db, usuario_owner)


def test_sub_usuario_de_crm_nao_recebe_o_saldo_do_mes(db, usuario_so_crm):
    """O filtro decide quais REGRAS RODAM, não quais resultados aparecem."""
    _conta_bancaria(db)

    assert "financeiro.conferencia.saldo_do_mes" not in _kinds(db, usuario_so_crm)


def test_o_mes_entra_no_sujeito_e_o_aviso_do_mes_novo_nao_e_calado(db, usuario_owner):
    """⚠️ O ponto da chave composta.

    Com o id da conta sozinho no `subject_id`, o marco de julho sobreviveria à virada, `dias`
    voltaria a zero em agosto e `_calada` engoliria o aviso do mês novo — o silêncio permanente que
    a correção de 2026-08-09 acabou de desfazer no eixo do dinheiro.
    """
    _conta_bancaria(db)

    julho = [
        a
        for a in coletar(db, user=usuario_owner, hoje=HOJE).ditas
        if a.kind == "financeiro.conferencia.saldo_do_mes"
    ][0]
    assert julho.subject_id.endswith(":2026-07")

    # O mapa de marcos como o briefing o gravaria, e a virada para setembro (agosto fechado).
    marcos = {f"{julho.kind}:{julho.subject_id}": 8}
    agosto = [
        a
        for a in coletar(
            db, user=usuario_owner, hoje=date(2026, 9, 3), ja_reportadas=marcos
        ).ditas
        if a.kind == "financeiro.conferencia.saldo_do_mes"
    ]

    assert agosto, "o mês novo é notícia nova — o marco do mês anterior não pode calá-lo"
    assert agosto[0].subject_id.endswith(":2026-08")


def test_a_regra_do_silencio_vale_dentro_do_mesmo_mes(db, usuario_owner):
    """Dito no dia 6, não repete no dia 7: só volta quando os dias dobram (`_proximo_marco`)."""
    conta = _conta_bancaria(db)
    dito = [
        a
        for a in coletar(db, user=usuario_owner, hoje=HOJE).ditas
        if a.kind == "financeiro.conferencia.saldo_do_mes"
    ][0]
    assert dito.dias == 6, "dias desde o fechamento de julho até 06/08"

    marcos = {f"{dito.kind}:{dito.subject_id}": dito.dias}
    assert "financeiro.conferencia.saldo_do_mes" not in _kinds(
        db, usuario_owner, hoje=date(2026, 8, 7), marcos=marcos
    )
    # Controle positivo: quando dobra, volta a ser notícia.
    assert "financeiro.conferencia.saldo_do_mes" in _kinds(
        db, usuario_owner, hoje=date(2026, 8, 13), marcos=marcos
    )
    assert conta.id


def test_nenhum_limiar_novo_foi_introduzido():
    """A Ausência do saldo do mês é **sem limiar**, e isso é a decisão.

    Um limiar exigiria a 8ª pergunta de Calibração (`test_todo_limiar_tem_pergunta` reprova limiar
    sem pergunta) e ela seria um número sem evidência — Artigo IV. Não precisa: a declaração
    retroativa existe, então avisar depois do fechamento não perde nada.
    """
    assert "saldo_do_mes_dias" not in LIMIARES_PADRAO


# ── clientes_em_atencao (Vima: consultar_clientes_atencao) ─────────────────────────────────

AGORA = datetime(2026, 8, 6, 23, 59, 59, tzinfo=UTC)


@pytest.fixture()
def conversa_sumida(db: Session) -> WhatsappChat:
    """Última mensagem é posterior ao corte de autoria e, na data de referência do teste que a
    usa (10/09), já passou o limiar padrão de 30 dias sem falar."""
    chat = _chat(db, jid="5511955554444@s.whatsapp.net", titulo="Renata")
    db.add(
        WhatsappMessage(
            tenant_id=TENANT, chat_id=chat.id, direction=DIRECTION_IN,
            text_body="Oi, tudo bem?",
            created_at=datetime(2026, 8, 6, 9, 0, tzinfo=UTC),
        )
    )
    db.commit()
    return chat


def test_clientes_em_atencao_junta_as_tres_familias_comerciais(
    db, conversa_esperando_resposta, conversa_sumida, card_parado_ha_12_dias,
):
    # Data de referência própria: "sumido" só cruza o limiar de 30 dias bem depois do corte de
    # autoria (05/08) — HOJE/AGORA do módulo (06/08) não deixam essa janela existir.
    hoje = date(2026, 9, 10)
    agora = datetime(2026, 9, 10, 23, 59, 59, tzinfo=UTC)
    kinds = {a.kind for a in clientes_em_atencao(db, hoje=hoje, agora=agora)}
    assert kinds == {
        "comercial.contato.esperando_resposta",
        "comercial.contato.sumido",
        "comercial.card.parado",
    }


def test_clientes_em_atencao_nao_traz_familias_de_fora_do_comercial(
    db, conta_vencendo_amanha,
):
    """Financeiro e Agenda não são "atenção ao cliente" — ficam de fora por escopo, não por
    permissão (esta função não recebe `user`; quem gateia é o `Ferramenta.modulo` da Vima)."""
    kinds = {a.kind for a in clientes_em_atencao(db, hoje=HOJE, agora=AGORA)}
    assert not any(k.startswith("financeiro.") or k.startswith("agenda.") for k in kinds)


def test_clientes_em_atencao_nao_aplica_o_silencio_do_briefing(db, card_parado_ha_12_dias):
    """Diferente de `coletar`, não existe `ja_reportadas` aqui: quem pergunta agora quer o
    estado inteiro, não só a escalada desde o último briefing."""
    ausencias = clientes_em_atencao(db, hoje=HOJE, agora=AGORA)
    assert any(a.kind == "comercial.card.parado" for a in ausencias)


def test_clientes_em_atencao_respeita_limiares_injetados(db, card_parado_ha_12_dias):
    ausencias = clientes_em_atencao(
        db, hoje=HOJE, agora=AGORA, limiares={**LIMIARES_PADRAO, "card_parado_dias": 30},
    )
    assert not any(a.kind == "comercial.card.parado" for a in ausencias)


def test_clientes_em_atencao_sem_nada_pendente_devolve_lista_vazia(db):
    assert clientes_em_atencao(db, hoje=HOJE, agora=AGORA) == []
    assert not [k for k in LIMIARES_PADRAO if "conferencia" in k or "saldo" in k]
