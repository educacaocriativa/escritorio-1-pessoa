"""`absorb_lead`: o lead que volta complementa o contato, não abre um card novo."""
from datetime import UTC, datetime

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
    """Os duplicados legados não foram mesclados — o retorno precisa cair sempre no mesmo.

    Os `created_at` são explícitos porque `Client.created_at` é `server_default=func.now()`:
    duas linhas criadas no mesmo segundo (SQLite) ou na mesma transação (Postgres) recebem
    timestamp IDÊNTICO, e aí "o mais antigo" não é uma propriedade observável — o desempate
    cai no `id`, que é uuid aleatório. Sem estas datas o teste seria uma moeda.
    """
    antigo = Client(
        tenant_id=tenant_id, name="Flavio 1", phone="(11) 99999-8888",
        phone_key="5511999998888", source="landing",
        created_at=datetime(2026, 7, 1, 10, 0, tzinfo=UTC),
    )
    novo = Client(
        tenant_id=tenant_id, name="Flavio 2", phone="(11) 99999-8888",
        phone_key="5511999998888", source="landing",
        created_at=datetime(2026, 8, 1, 10, 0, tzinfo=UTC),
    )
    db.add_all([antigo, novo])
    db.commit()

    achado, criou = _absorve(
        db, tenant_id, name="Flavio", phone="(11) 99999-8888", source="landing"
    )
    assert criou is False
    assert achado.id == antigo.id


def test_multiplos_candidatos_com_a_mesma_data_e_deterministico(db, tenant_id):
    """Empate de `created_at` não pode fazer o retorno alternar entre cards.

    Quando o timestamp empata, "o mais antigo" deixa de existir como fato — o que a garantia
    precisa entregar então é ESTABILIDADE: a mesma escolha em toda chamada, para o histórico
    não se partir entre os duplicados. Isso vem do `id` como segundo critério de ordenação.
    """
    mesma_data = datetime(2026, 7, 1, 10, 0, tzinfo=UTC)
    for nome in ("Flavio 1", "Flavio 2", "Flavio 3"):
        db.add(Client(
            tenant_id=tenant_id, name=nome, phone="(11) 99999-8888",
            phone_key="5511999998888", source="landing", created_at=mesma_data,
        ))
    db.commit()

    escolhidos = {
        _absorve(db, tenant_id, name="Flavio", phone="(11) 99999-8888", source="landing")[0].id
        for _ in range(3)
    }
    assert len(escolhidos) == 1


def test_retorno_emite_evento_no_barramento(db, tenant_id):
    from app.core import events

    recebidos = []
    events.subscribe(service.EVENT_CLIENT_RETURNED, lambda **kw: recebidos.append(kw))

    _absorve(db, tenant_id, name="Flavio Kato", phone="(11) 99999-8888", source="landing")
    _absorve(db, tenant_id, name="Flavio Kato", phone="(11) 99999-8888", source="landing")

    assert len(recebidos) == 1
    assert recebidos[0]["source"] == "landing"


# ── Editar o telefone na ficha do CRM ────────────────────────────────────────
# `phone_key` é derivado de `phone`, e derivado que não é recalculado vira mentira. `create_client`
# e `absorb_lead` sempre recalcularam; `update_client` não — ele faz `setattr` genérico sobre o
# payload, e `phone_key` não está no `ClientUpdate` (nem deve estar: é derivado, não é campo de
# entrada). O efeito não aparece na tela de edição: aparece no PRÓXIMO lead, como um card
# duplicado — exatamente o que a jornada única do contato existe para impedir.


def _edita(db, tenant_id: str, client_id: str, **campos):
    from app.modules.crm.schemas import ClientUpdate

    return service.update_client(
        db, client_id=client_id, tenant_id=tenant_id, actor="dono",
        data=ClientUpdate(**campos),
    )


def test_editar_telefone_recalcula_a_chave(db, tenant_id):
    contato, _ = _absorve(
        db, tenant_id, name="Flavio Kato", phone="(11) 99999-8888", source="landing"
    )
    editado = _edita(db, tenant_id, contato.id, phone="(43) 98407-4017")
    assert editado.phone_key == "5543984074017"


def test_lead_com_o_telefone_corrigido_cai_no_mesmo_card(db, tenant_id):
    """A consequência que importa: sem recálculo, o lead seguinte não encontra o contato pela
    chave velha e abre um card novo."""
    contato, _ = _absorve(
        db, tenant_id, name="Flavio Kato", phone="(11) 99999-8888", source="landing"
    )
    _edita(db, tenant_id, contato.id, phone="(43) 98407-4017")

    de_volta, novo = _absorve(
        db, tenant_id, name="Flavio Kato", phone="5543984074017", source="landing"
    )
    assert novo is False
    assert de_volta.id == contato.id
    assert db.scalar(select(Client).where(Client.id != contato.id)) is None


def test_editar_outro_campo_nao_mexe_na_chave(db, tenant_id):
    """`exclude_unset=True`: quem não mandou telefone não teve telefone alterado, e a chave
    derivada dele não pode se mover sozinha."""
    contato, _ = _absorve(
        db, tenant_id, name="Flavio Kato", phone="(11) 99999-8888", source="landing"
    )
    antes = contato.phone_key
    editado = _edita(db, tenant_id, contato.id, name="Flávio Kato")
    assert editado.phone_key == antes == "5511999998888"


def test_apagar_o_telefone_apaga_a_chave(db, tenant_id):
    """Chave órfã seria pior que chave ausente: casaria um lead futuro com um contato que já não
    tem aquele telefone."""
    contato, _ = _absorve(
        db, tenant_id, name="Flavio Kato", phone="(11) 99999-8888", source="landing"
    )
    editado = _edita(db, tenant_id, contato.id, phone=None)
    assert editado.phone_key is None


def test_telefone_invalido_nao_deixa_chave_velha_para_tras(db, tenant_id):
    """`normalize_br` devolve `None` para o que não é telefone BR. O contato fica sem chave — e
    sem chave é honesto; com a chave ANTIGA seria um casamento errado."""
    contato, _ = _absorve(
        db, tenant_id, name="Flavio Kato", phone="(11) 99999-8888", source="landing"
    )
    editado = _edita(db, tenant_id, contato.id, phone="não é telefone")
    assert editado.phone_key is None
