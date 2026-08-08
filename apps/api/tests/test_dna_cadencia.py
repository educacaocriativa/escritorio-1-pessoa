"""A cadência: uma pergunta por dia, pulada em quarentena, escolha determinística."""
from datetime import UTC, date, datetime

from sqlalchemy.orm import Session

from app.modules.dna import cadencia, catalog, service
from app.modules.dna.models import SOURCE_GANCHO, DnaAnswer

TENANT = "t1"
HOJE = date(2026, 8, 8)
GANCHO_CARD = "briefing.ausencia.comercial.card.parado"


def _linha(db: Session, key: str, *, valor, quando: datetime) -> None:
    db.add(
        DnaAnswer(
            tenant_id=TENANT, question_key=key, value=valor,
            answered_at=quando, answered_by="u1", source=SOURCE_GANCHO,
        )
    )
    db.commit()


def test_devolve_a_pergunta_do_gancho_quando_nada_foi_respondido(db: Session):
    p = cadencia.pendente(db, gancho=GANCHO_CARD, hoje=HOJE)
    assert p is not None
    assert p.key == "ritmo.card_parado_dias"


def test_nao_devolve_pergunta_ja_respondida(db: Session):
    _linha(db, "ritmo.card_parado_dias", valor=5,
           quando=datetime(2026, 7, 1, tzinfo=UTC))
    assert cadencia.pendente(db, gancho=GANCHO_CARD, hoje=HOJE) is None


def test_uma_pergunta_por_dia_no_produto_inteiro(db: Session):
    """Qualquer resposta de HOJE cala todos os ganchos — não é uma por tela, é uma."""
    _linha(db, "oferta.o_que_vende", valor="misto",
           quando=datetime(2026, 8, 8, 9, 0, tzinfo=UTC))
    assert cadencia.pendente(db, gancho=GANCHO_CARD, hoje=HOJE) is None


def test_resposta_das_22h_em_sao_paulo_gasta_a_cota_DAQUELE_dia(db: Session):
    """`answered_at` é timestamptz: 22h de 08/08 em UTC−3 é 01h de 09/08 em UTC.

    Lida crua, a data do carimbo seria 09/08 e a cota de 08/08 pareceria intacta — o dono
    responderia às 22h e seria perguntado de novo às 22h05. É a mesma classe de bug que a
    correção de fuso de 2026-08-05 eliminou do sistema inteiro.
    """
    _linha(db, "oferta.o_que_vende", valor="misto",
           quando=datetime(2026, 8, 9, 1, 0, tzinfo=UTC))
    assert cadencia.pendente(
        db, gancho=GANCHO_CARD, hoje=HOJE, fuso="America/Sao_Paulo"
    ) is None
    # E o mesmo instante, num tenant que de fato vive em UTC, é amanhã: a cota de hoje sobrou.
    assert cadencia.pendente(db, gancho=GANCHO_CARD, hoje=HOJE, fuso="UTC") is not None


def test_resposta_de_ontem_nao_cala_hoje(db: Session):
    _linha(db, "oferta.o_que_vende", valor="misto",
           quando=datetime(2026, 8, 7, 23, 0, tzinfo=UTC))
    assert cadencia.pendente(db, gancho=GANCHO_CARD, hoje=HOJE) is not None


def test_pulada_fica_em_quarentena_por_7_dias(db: Session):
    _linha(db, "ritmo.card_parado_dias", valor=None,
           quando=datetime(2026, 8, 5, tzinfo=UTC))
    assert cadencia.pendente(db, gancho=GANCHO_CARD, hoje=HOJE) is None


def test_pulada_volta_depois_da_quarentena(db: Session):
    """Some por uma semana, não para sempre: um 'depois' acidental não pode perder a pergunta."""
    _linha(db, "ritmo.card_parado_dias", valor=None,
           quando=datetime(2026, 7, 20, tzinfo=UTC))
    p = cadencia.pendente(db, gancho=GANCHO_CARD, hoje=HOJE)
    assert p is not None and p.key == "ritmo.card_parado_dias"


def test_escolha_e_deterministica_pela_ordem_do_catalogo(db: Session):
    """Duas elegíveis no mesmo gancho: vence a primeira do catálogo, sempre a mesma."""
    gancho = "quotes.orcamento.criado"
    primeira = cadencia.pendente(db, gancho=gancho, hoje=HOJE)
    assert primeira is not None
    assert primeira.key == "oferta.ticket_tipico"
    assert cadencia.pendente(db, gancho=gancho, hoje=HOJE).key == primeira.key


def test_gancho_desconhecido_devolve_nada(db: Session):
    assert cadencia.pendente(db, gancho="tela.inventada", hoje=HOJE) is None


def test_nucleo_devolve_as_seis_na_ordem_declarada(db: Session):
    faltando = cadencia.faltantes(db, gancho=cadencia.GANCHO_NUCLEO)
    assert [p.key for p in faltando] == list(catalog.NUCLEO)


def test_nucleo_encolhe_conforme_responde(db: Session):
    """O núcleo é sequência anunciada: não obedece ao 'uma por dia' e some item a item."""
    service.responder(db, tenant_id=TENANT, key="oferta.o_que_vende", valor="misto",
                      user_id="u1", source="nucleo")
    faltando = cadencia.faltantes(db, gancho=cadencia.GANCHO_NUCLEO)
    assert "oferta.o_que_vende" not in [p.key for p in faltando]
    assert len(faltando) == 5
