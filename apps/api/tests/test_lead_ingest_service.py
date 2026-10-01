"""`lead_ingest.service.ingest`: contato, tags, fato e idempotência (spec §6.2).

Etapa do Kanban e funil por evento: `test_lead_ingest_etapa_funil.py`.
"""
import json

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import events
from app.core.facts import Fact
from app.modules.crm.models import Client
from app.modules.lead_ingest import registro as registro_service
from app.modules.lead_ingest import service
from app.modules.lead_ingest.models import LeadIngestRecord
from app.modules.settings import service as settings_service
from tests.lead_ingest_apoio import TENANT, payload


@pytest.fixture(autouse=True)
def _sem_assinantes():
    # O barramento é global ao processo; sem isto, um assinante registrado no import de
    # `app.main` tentaria abrir conexão Postgres real ao receber `crm.client.*`.
    events.clear()
    yield
    events.clear()


def _ingere(db: Session, **sobre):
    return service.ingest(db, tenant_id=TENANT, dados=payload(**sobre))


def _fatos(db: Session, client_id: str, kind: str) -> list[Fact]:
    return list(
        db.scalars(select(Fact).where(Fact.client_id == client_id, Fact.kind == kind)).all()
    )


def _produto(db: Session, nome: str = "publia") -> None:
    perfil = settings_service.get_profile(db, TENANT)
    perfil.lead_ingest_config = {"produto": nome}
    db.commit()


def test_lead_novo_cria_contato_api_com_tags_e_fato(db: Session):
    r = _ingere(db)
    assert r.processado is True
    contato = db.get(Client, r.contato_id)
    assert contato.source == "api"
    assert contato.tags == ["origem:instagram", "post:ig-r-c8abc"]
    [fato] = _fatos(db, contato.id, "comercial.lead.recebido")
    assert fato.title == "Deixou o contato no site"
    corpo = json.loads(fato.body)
    assert corpo["atribuicao"]["situacao"] == "resolvida"
    assert corpo["atribuicao"]["ultimo_toque"]["utm_content"] == "ig-r-c8abc"
    assert corpo["tags_descartadas"] == []


def test_mesma_chave_repetida_e_no_op(db: Session):
    primeiro = _ingere(db)
    segundo = _ingere(db, tags=["outra:tag"])
    assert segundo.processado is False
    assert segundo.contato_id == primeiro.contato_id
    assert db.scalar(select(func.count(Client.id))) == 1
    assert len(_fatos(db, primeiro.contato_id, "comercial.lead.recebido")) == 1
    assert "outra:tag" not in db.get(Client, primeiro.contato_id).tags


def test_retoma_chave_reivindicada_que_nao_concluiu(db: Session):
    """Queda entre o commit do contato e o das tags: a próxima tentativa processa."""
    dados = payload()
    registro_service.reivindicar(
        db, tenant_id=TENANT, chave=dados.chave_idempotencia, evento=dados.evento,
        ocorrido_em=dados.ocorrido_em, payload={},
    )
    db.commit()
    r = service.ingest(db, tenant_id=TENANT, dados=dados)
    assert r.processado is True
    assert db.scalar(select(func.count(LeadIngestRecord.id))) == 1
    assert db.scalar(select(LeadIngestRecord.concluido_em)) is not None


def test_fato_nao_guarda_dinheiro_mas_o_registro_bruto_guarda(db: Session):
    r = _ingere(
        db, evento="compra_aprovada", chave_idempotencia="kiwify:ord_1:compra_aprovada",
        pedido={
            "provedor": "kiwify", "order_id": "ord_1", "plano": "essencial", "periodo": "anual",
            "valor_bruto_centavos": 49900, "valor_liquido_centavos": 44300,
            "taxa_centavos": 5600,
        },
    )
    [fato] = _fatos(db, r.contato_id, "comercial.compra.aprovada")
    assert json.loads(fato.body)["pedido"] == {
        "provedor": "kiwify", "order_id": "ord_1", "plano": "essencial", "periodo": "anual",
    }
    assert "49900" not in fato.body and "44300" not in fato.body and "5600" not in fato.body
    assert db.scalar(select(LeadIngestRecord)).payload["pedido"]["valor_bruto_centavos"] == 49900


def test_dedup_por_telefone_em_formato_diferente(db: Session):
    primeiro = _ingere(db)
    segundo = _ingere(
        db, chave_idempotencia="site:lead:2",
        contato={"nome": "Maria", "telefone": "5511999998888"},
    )
    assert segundo.contato_id == primeiro.contato_id
    assert db.scalar(select(func.count(Client.id))) == 1


def test_mesmo_email_com_telefone_diferente_nao_cria_card_nem_troca_telefone(db: Session):
    primeiro = _ingere(db)
    segundo = _ingere(
        db, chave_idempotencia="site:lead:2",
        contato={
            "nome": "Maria", "email": "MARIA@exemplo.gov.br", "telefone": "(21) 98888-7777",
        },
    )
    assert segundo.contato_id == primeiro.contato_id
    assert db.scalar(select(func.count(Client.id))) == 1
    assert db.get(Client, primeiro.contato_id).phone == "(11) 99999-8888"


def test_telefone_de_um_e_email_de_outro_fica_com_o_dono_do_telefone(db: Session):
    maria = _ingere(db)
    joao = _ingere(
        db, chave_idempotencia="site:lead:2",
        contato={"nome": "João", "email": "joao@exemplo.gov.br", "telefone": "(21) 98888-7777"},
    )
    misto = _ingere(
        db, chave_idempotencia="site:lead:3",
        contato={"nome": "?", "email": "maria@exemplo.gov.br", "telefone": "(21) 98888-7777"},
    )
    assert misto.contato_id == joao.contato_id
    assert misto.contato_id != maria.contato_id


def test_tags_somam_entre_eventos_sem_duplicar(db: Session):
    r = _ingere(db)
    _ingere(
        db, chave_idempotencia="site:lead:2",
        tags=["origem:instagram", "campanha:publia-lanc-out26"],
    )
    assert db.get(Client, r.contato_id).tags == [
        "origem:instagram", "post:ig-r-c8abc", "campanha:publia-lanc-out26",
    ]


def test_tags_acima_do_limite_nao_derrubam_e_ficam_registradas(db: Session):
    longa = "campanha:" + "x" * 32  # 41 caracteres
    r = _ingere(db, tags=[f"t:{i:02d}" for i in range(60)] + [longa])
    assert r.processado is True
    contato = db.get(Client, r.contato_id)
    assert len(contato.tags) == 50
    esperadas = [f"t:{i:02d}" for i in range(50, 60)] + [longa]
    [fato] = _fatos(db, contato.id, "comercial.lead.recebido")
    assert json.loads(fato.body)["tags_descartadas"] == esperadas
    assert db.scalar(select(LeadIngestRecord)).tags_descartadas == esperadas


@pytest.mark.parametrize(
    ("evento", "tag", "kind"),
    [
        ("reembolso", "publia:reembolso", "comercial.compra.reembolsada"),
        ("chargeback", "publia:chargeback", "comercial.compra.contestada"),
        ("cancelamento", "publia:cancelou", "comercial.assinatura.cancelada"),
    ],
)
def test_pos_venda_aplica_tag_de_produto_sem_passar_pelo_voltou(db: Session, evento, tag, kind):
    _produto(db)
    compra = _ingere(db, evento="compra_aprovada", chave_idempotencia="kiwify:ord_1:compra")
    depois = _ingere(db, evento=evento, chave_idempotencia=f"kiwify:ord_1:{evento}", tags=[])
    assert depois.contato_id == compra.contato_id
    assert tag in db.get(Client, compra.contato_id).tags
    assert len(_fatos(db, compra.contato_id, kind)) == 1
    assert _fatos(db, compra.contato_id, "crm.lead.retornou") == []


def test_renovacao_so_registra(db: Session):
    _produto(db)
    compra = _ingere(db, evento="compra_aprovada", chave_idempotencia="kiwify:ord_1:compra")
    antes = list(db.get(Client, compra.contato_id).tags)
    _ingere(db, evento="renovacao", chave_idempotencia="kiwify:ord_1:renovacao:2026-11", tags=[])
    assert db.get(Client, compra.contato_id).tags == antes
    assert len(_fatos(db, compra.contato_id, "comercial.assinatura.renovada")) == 1


def test_sem_produto_configurado_nao_inventa_tag(db: Session):
    r = _ingere(db, evento="reembolso", chave_idempotencia="kiwify:ord_9:reembolso", tags=[])
    assert not any(t.endswith(":reembolso") for t in db.get(Client, r.contato_id).tags)


def test_pos_venda_de_quem_nunca_chegou_cria_o_contato(db: Session):
    _produto(db)
    r = _ingere(
        db, evento="chargeback", chave_idempotencia="kiwify:ord_7:chargeback",
        contato={"nome": "Ana", "email": "ana@exemplo.gov.br"}, tags=[],
    )
    contato = db.get(Client, r.contato_id)
    assert contato.source == "api"
    assert contato.tags == ["publia:chargeback"]


def test_contato_so_com_email_usa_o_email_como_nome(db: Session):
    r = _ingere(db, contato={"email": "sem.nome@exemplo.gov.br"})
    assert db.get(Client, r.contato_id).name == "sem.nome@exemplo.gov.br"

def test_find_lead_sem_telefone_nem_email_devolve_none(db: Session):
    from app.modules.crm import service as crm_service

    _ingere(db)
    assert crm_service.find_lead(db, phone=None, email=None) is None
