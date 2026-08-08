"""A porta de escrita do DNA: valida contra o catálogo, faz upsert, e pular é gravar nulo."""
import pytest
from sqlalchemy.orm import Session

from app.modules.dna import service
from app.modules.dna.models import SOURCE_CONFIG, SOURCE_GANCHO, DnaAnswer

TENANT = "t1"


def test_responder_grava_e_commita(db: Session):
    service.responder(
        db, tenant_id=TENANT, key="oferta.o_que_vende", valor="servico_projeto",
        user_id="u1", source=SOURCE_CONFIG,
    )
    linha = db.query(DnaAnswer).one()
    assert linha.value == "servico_projeto"
    assert linha.answered_by == "u1"


def test_responder_de_novo_faz_upsert_e_nao_cria_segunda_linha(db: Session):
    """DNA é estado atual, não história — duas linhas fariam toda leitura ter que escolher."""
    service.responder(
        db, tenant_id=TENANT, key="oferta.o_que_vende", valor="servico_projeto",
        user_id="u1", source=SOURCE_CONFIG,
    )
    service.responder(
        db, tenant_id=TENANT, key="oferta.o_que_vende", valor="produto_digital",
        user_id="u1", source=SOURCE_CONFIG,
    )
    assert db.query(DnaAnswer).count() == 1
    assert db.query(DnaAnswer).one().value == "produto_digital"


def test_chave_desconhecida_e_recusada(db: Session):
    with pytest.raises(service.DnaError, match="não existe"):
        service.responder(
            db, tenant_id=TENANT, key="oferta.inventada", valor="x",
            user_id="u1", source=SOURCE_CONFIG,
        )


def test_valor_fora_das_opcoes_e_recusado(db: Session):
    """Sem isso o JSON vira depósito e o resolver quebra na leitura, longe de quem escreveu."""
    with pytest.raises(service.DnaError, match="opções"):
        service.responder(
            db, tenant_id=TENANT, key="oferta.o_que_vende", valor="nao_existe",
            user_id="u1", source=SOURCE_CONFIG,
        )


def test_escolha_multipla_aceita_lista_e_recusa_item_invalido(db: Session):
    service.responder(
        db, tenant_id=TENANT, key="cliente.como_chega", valor=["indicacao", "busca"],
        user_id="u1", source=SOURCE_CONFIG,
    )
    assert db.query(DnaAnswer).one().value == ["indicacao", "busca"]

    with pytest.raises(service.DnaError, match="opções"):
        service.responder(
            db, tenant_id=TENANT, key="cliente.como_chega", valor=["indicacao", "telepatia"],
            user_id="u1", source=SOURCE_CONFIG,
        )


def test_texto_longo_demais_e_recusado(db: Session):
    with pytest.raises(service.DnaError, match="longo"):
        service.responder(
            db, tenant_id=TENANT, key="limites.nunca_faco", valor="x" * 2001,
            user_id="u1", source=SOURCE_CONFIG,
        )


def test_calibracao_aceita_none_so_onde_a_opcao_existe(db: Session):
    """Topo seco pode ser desligado; as outras cinco não têm opção de desligamento."""
    service.responder(
        db, tenant_id=TENANT, key="cliente.topo_seco_dias", valor=None,
        user_id="u1", source=SOURCE_CONFIG,
    )
    assert db.query(DnaAnswer).one().value is None

    with pytest.raises(service.DnaError, match="opções"):
        service.responder(
            db, tenant_id=TENANT, key="ritmo.card_parado_dias", valor=None,
            user_id="u1", source=SOURCE_CONFIG,
        )


def test_pular_grava_linha_com_valor_nulo(db: Session):
    service.pular(
        db, tenant_id=TENANT, key="limites.nunca_faco", user_id="u1", source=SOURCE_GANCHO,
    )
    linha = db.query(DnaAnswer).one()
    assert linha.value is None
    assert linha.source == SOURCE_GANCHO


def test_respostas_ignora_puladas_mas_linhas_as_inclui(db: Session):
    """A distinção que sustenta a quarentena: 'pulei' não é resposta, mas é registro."""
    service.responder(
        db, tenant_id=TENANT, key="oferta.o_que_vende", valor="misto",
        user_id="u1", source=SOURCE_CONFIG,
    )
    service.pular(db, tenant_id=TENANT, key="limites.nunca_faco", user_id="u1",
                  source=SOURCE_CONFIG)

    assert service.respostas(db) == {"oferta.o_que_vende": "misto"}
    assert set(service.linhas(db)) == {"oferta.o_que_vende", "limites.nunca_faco"}


def test_responder_nao_emite_fato(db: Session):
    """O feed do briefing é sobre o NEGÓCIO, não sobre a configuração do produto.

    Um "você respondeu uma pergunta" no resumo de amanhã seria ruído auto-referente. A trilha de
    quem mudou o quê é trabalho de `core/audit.py`.
    """
    from app.core.facts import Fact

    service.responder(
        db, tenant_id=TENANT, key="oferta.o_que_vende", valor="misto",
        user_id="u1", source=SOURCE_CONFIG,
    )
    assert db.query(Fact).count() == 0


def test_pular_e_depois_responder_vira_resposta(db: Session):
    service.pular(db, tenant_id=TENANT, key="oferta.o_que_vende", user_id="u1",
                  source=SOURCE_GANCHO)
    service.responder(
        db, tenant_id=TENANT, key="oferta.o_que_vende", valor="misto",
        user_id="u1", source=SOURCE_CONFIG,
    )
    assert db.query(DnaAnswer).count() == 1
    assert service.respostas(db) == {"oferta.o_que_vende": "misto"}
