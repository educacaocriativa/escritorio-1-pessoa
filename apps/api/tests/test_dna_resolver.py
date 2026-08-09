"""O resolver é a ÚNICA porta de leitura do DNA."""
from datetime import UTC, date, datetime

from sqlalchemy.orm import Session

from app.modules.dna import resolver, service
from app.modules.dna.models import SOURCE_CONFIG, DnaAnswer
from app.modules.vima.absences import LIMIARES_PADRAO

TENANT = "t1"


def test_sem_resposta_devolve_dicionario_vazio(db: Session):
    """Vazio, não os defaults: quem mescla é `coletar`, e duas fontes de default divergem."""
    assert resolver.limiares(db) == {}


def test_calibracao_respondida_vira_limiar(db: Session):
    service.responder(db, tenant_id=TENANT, key="ritmo.card_parado_dias", valor=5,
                      user_id="u1", source=SOURCE_CONFIG)
    assert resolver.limiares(db) == {"card_parado_dias": 5}


def test_retrato_nunca_entra_nos_limiares(db: Session):
    """O contrato das classes vive ou morre aqui."""
    service.responder(db, tenant_id=TENANT, key="oferta.o_que_vende", valor="misto",
                      user_id="u1", source=SOURCE_CONFIG)
    assert resolver.limiares(db) == {}
    assert resolver.retrato(db) == {"oferta.o_que_vende": "misto"}


def test_calibracao_nunca_entra_no_retrato(db: Session):
    service.responder(db, tenant_id=TENANT, key="ritmo.card_parado_dias", valor=5,
                      user_id="u1", source=SOURCE_CONFIG)
    assert resolver.retrato(db) == {}


def test_desligar_topo_seco_vira_none_e_nao_some(db: Session):
    """`None` = regra não executada. Sumir do dicionário faria o default de 5 dias voltar."""
    service.responder(db, tenant_id=TENANT, key="cliente.topo_seco_dias", valor=None,
                      user_id="u1", source=SOURCE_CONFIG)
    assert resolver.limiares(db) == {"topo_sem_lead_dias": None}


def test_valor_que_saiu_do_catalogo_cai_no_default(db: Session):
    """Trocar o `valor` de uma opção deixa resposta órfã. Ela não pode derrubar o briefing."""
    db.add(
        DnaAnswer(
            tenant_id=TENANT, question_key="ritmo.card_parado_dias", value=999,
            answered_at=datetime.now(UTC), answered_by="u1", source=SOURCE_CONFIG,
        )
    )
    db.commit()
    assert "card_parado_dias" not in resolver.limiares(db)


def test_toda_chave_devolvida_existe_em_limiares_padrao(db: Session):
    service.responder(db, tenant_id=TENANT, key="ritmo.card_parado_dias", valor=5,
                      user_id="u1", source=SOURCE_CONFIG)
    assert set(resolver.limiares(db)) <= set(LIMIARES_PADRAO)


def test_recalibrado_apos_olha_so_calibracao(db: Session):
    """Responder Retrato não pode limpar o silêncio — nada no comportamento mudou."""
    service.responder(db, tenant_id=TENANT, key="oferta.o_que_vende", valor="misto",
                      user_id="u1", source=SOURCE_CONFIG)
    assert resolver.recalibrado_apos(db, date(2026, 1, 1)) is False

    service.responder(db, tenant_id=TENANT, key="ritmo.card_parado_dias", valor=5,
                      user_id="u1", source=SOURCE_CONFIG)
    assert resolver.recalibrado_apos(db, date(2026, 1, 1)) is True
