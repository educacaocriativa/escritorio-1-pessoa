"""`absorb_lead`: o lead que volta complementa o contato, não abre um card novo."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.modules.crm import service
from app.modules.crm.models import Client, ClientEvent, PipelineStage
from app.modules.crm.schemas import ClientCreate

REGISTER = {
    "legal_name": "Estúdio Ana",
    "document": "11222333000181",
    "slug": "estudioana",
    "email": "ana@example.com",
    "name": "Ana",
    "password": "senha-bem-comprida",
}


@pytest.fixture()
def tenant_id(client: TestClient) -> str:
    resp = client.post("/auth/register", json=REGISTER)
    return resp.json()["tenant"]["id"]


def _absorve(db, tenant_id: str, **campos):
    return service.absorb_lead(
        db, tenant_id=tenant_id, actor="pagina:lead", data=ClientCreate(**campos)
    )


def _kinds(db, client_id: str) -> list[str]:
    return [
        e.kind
        for e in db.scalars(
            select(ClientEvent)
            .where(ClientEvent.client_id == client_id)
            .order_by(ClientEvent.created_at, ClientEvent.id)
        ).all()
    ]


def _stage(db, nome: str) -> PipelineStage:
    return db.scalar(select(PipelineStage).where(PipelineStage.name == nome))


def test_lead_desconhecido_cria_contato(db, tenant_id):
    contato, novo = _absorve(
        db, tenant_id, name="Flavio Kato", phone="(11) 99999-8888", source="landing"
    )
    assert novo is True
    assert _kinds(db, contato.id) == ["lead_created"]


def test_mesmo_telefone_em_formato_diferente_nao_cria_segundo_card(db, tenant_id):
    primeiro, _ = _absorve(
        db, tenant_id, name="Flavio Kato", phone="(11) 99999-8888", source="landing"
    )
    segundo, novo = _absorve(
        db, tenant_id, name="Flavio Kato", phone="5511999998888", source="landing"
    )
    assert novo is False
    assert segundo.id == primeiro.id
    assert db.scalar(select(Client).where(Client.id != primeiro.id)) is None


def test_mesmo_email_sem_telefone_nao_cria_segundo_card(db, tenant_id):
    primeiro, _ = _absorve(
        db, tenant_id, name="Flavio Kato", email="flavio@example.com", source="landing"
    )
    segundo, novo = _absorve(
        db, tenant_id, name="Flavio K.", email="FLAVIO@EXAMPLE.COM", source="landing"
    )
    assert novo is False
    assert segundo.id == primeiro.id


def test_retorno_grava_lead_return_com_o_texto_desta_vez(db, tenant_id):
    contato, _ = _absorve(
        db, tenant_id, name="Flavio Kato", phone="(11) 99999-8888", source="landing"
    )
    _absorve(
        db, tenant_id, name="Flavio Kato", phone="(11) 99999-8888", source="landing",
        notes="Quero orçamento para 50 convidados",
    )
    eventos = list(
        db.scalars(
            select(ClientEvent)
            .where(ClientEvent.client_id == contato.id, ClientEvent.kind == "lead_return")
        ).all()
    )
    assert len(eventos) == 1
    assert "50 convidados" in eventos[0].body


def test_retorno_preenche_campo_vazio_mas_nao_sobrescreve(db, tenant_id):
    contato, _ = _absorve(
        db, tenant_id, name="Flavio Kato", phone="(11) 99999-8888",
        email="antigo@example.com", source="landing",
    )
    _absorve(
        db, tenant_id, name="Flavio Kato", phone="(11) 99999-8888",
        email="novo@example.com", document="52998224725", source="landing",
    )
    db.refresh(contato)
    assert contato.email == "antigo@example.com"   # já tinha: não toca
    assert contato.document == "52998224725"       # estava vazio: preenche


def test_retorno_nao_apaga_as_observacoes_do_dono(db, tenant_id):
    contato, _ = _absorve(
        db, tenant_id, name="Flavio Kato", phone="(11) 99999-8888", source="landing"
    )
    contato.notes = "Cliente exigente, cobrar adiantado"
    db.commit()
    _absorve(
        db, tenant_id, name="Flavio Kato", phone="(11) 99999-8888", source="landing",
        notes="texto novo do formulario",
    )
    db.refresh(contato)
    assert contato.notes == "Cliente exigente, cobrar adiantado"


def test_retorno_nao_move_card_de_coluna_do_meio(db, tenant_id):
    contato, _ = _absorve(
        db, tenant_id, name="Flavio Kato", phone="(11) 99999-8888", source="landing"
    )
    proposta = _stage(db, "Proposta")
    contato.stage_id = proposta.id
    db.commit()

    _absorve(db, tenant_id, name="Flavio Kato", phone="(11) 99999-8888", source="landing")
    db.refresh(contato)
    assert contato.stage_id == proposta.id
    assert "reopened" not in _kinds(db, contato.id)


@pytest.mark.parametrize("coluna", ["Ganho", "Perda"])
def test_retorno_reabre_card_em_coluna_terminal(db, tenant_id, coluna):
    contato, _ = _absorve(
        db, tenant_id, name="Flavio Kato", phone="(11) 99999-8888", source="landing"
    )
    terminal = _stage(db, coluna)
    contato.stage_id = terminal.id
    db.commit()

    _absorve(db, tenant_id, name="Flavio Kato", phone="(11) 99999-8888", source="landing")
    db.refresh(contato)
    entrada = _stage(db, "Entrada")
    assert contato.stage_id == entrada.id
    assert "reopened" in _kinds(db, contato.id)


def test_multiplos_candidatos_escolhe_o_mais_antigo(db, tenant_id):
    """Os duplicados legados não foram mesclados — o retorno precisa cair sempre no mesmo."""
    antigo = Client(
        tenant_id=tenant_id, name="Flavio 1", phone="(11) 99999-8888",
        phone_key="5511999998888", source="landing",
    )
    db.add(antigo)
    db.flush()
    novo = Client(
        tenant_id=tenant_id, name="Flavio 2", phone="(11) 99999-8888",
        phone_key="5511999998888", source="landing",
    )
    db.add(novo)
    db.commit()

    achado, criou = _absorve(
        db, tenant_id, name="Flavio", phone="(11) 99999-8888", source="landing"
    )
    assert criou is False
    assert achado.id == antigo.id


def test_retorno_emite_evento_no_barramento(db, tenant_id):
    from app.core import events

    recebidos = []
    events.subscribe(service.EVENT_CLIENT_RETURNED, lambda **kw: recebidos.append(kw))

    _absorve(db, tenant_id, name="Flavio Kato", phone="(11) 99999-8888", source="landing")
    _absorve(db, tenant_id, name="Flavio Kato", phone="(11) 99999-8888", source="landing")

    assert len(recebidos) == 1
    assert recebidos[0]["source"] == "landing"
