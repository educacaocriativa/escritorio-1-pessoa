"""Mescla de contatos duplicados: o card some, o histórico não.

Contexto real (tenant do fundador, 2026-08-05): SEIS cards "Flavio Kato" com o mesmo
`phone_key`. O funil inscreveu um (`source=api`, zero conversas) enquanto a conversa do WhatsApp
estava pendurada em outro (`source=whatsapp`) — a mensagem foi entregue e mesmo assim não
apareceu no fio, porque `get_timeline` ancora os avisos automáticos em `chat.client_id`.
"""
from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.facts import Fact
from app.modules.crm import merge, service
from app.modules.crm.models import Client
from app.modules.crm.schemas import ClientCreate
from app.modules.receivables.models import Charge

REGISTER = {
    "legal_name": "Doro Eventos",
    "document": "11222333000181",
    "slug": "doro",
    "email": "doro@example.com",
    "name": "Doro",
    "password": "senha-bem-comprida",
}


@pytest.fixture()
def tenant_id(client: TestClient) -> str:
    return client.post("/auth/register", json=REGISTER).json()["tenant"]["id"]


def _cria(db, tenant_id: str, **campos) -> Client:
    return service.create_client(
        db, tenant_id=tenant_id, actor="dono", data=ClientCreate(**campos)
    )


# ── Descoberta das tabelas ───────────────────────────────────────────────────


def test_descobre_as_tabelas_em_vez_de_listar():
    """Lista escrita à mão esquece o módulo seguinte — e esquecer aqui significa deixar cobrança
    ou conversa apontando para um card recém-apagado."""
    tabelas = merge.tabelas_que_apontam_para_cliente()
    # Uma amostra de módulos independentes entre si: se a descoberta quebrar, alguma some.
    assert {"charges", "quotes", "contracts", "notifications", "whatsapp_chats",
            "whatsapp_messages", "facts"} <= set(tabelas)
    assert "clients" not in tabelas  # a própria tabela não tem `client_id`


# ── O guarda que impede a mescla errada ──────────────────────────────────────


def test_mesmo_telefone_nomes_diferentes_nao_e_duplicado(db, tenant_id):
    """`phone_key` não é único DE PROPÓSITO: marido e mulher compartilham telefone. Juntar duas
    pessoas num card é pior que o duplicado que a mescla existe para resolver."""
    _cria(db, tenant_id, name="Flavio Kato", phone="(43) 98407-4017", source="manual")
    _cria(db, tenant_id, name="Maria Kato", phone="(43) 98407-4017", source="manual")
    assert merge.find_duplicate_groups(db) == []


def test_nome_com_acento_e_caixa_diferentes_ainda_e_a_mesma_pessoa(db, tenant_id):
    _cria(db, tenant_id, name="Flávio Kato", phone="(43) 98407-4017", source="manual")
    _cria(db, tenant_id, name="flavio  kato", phone="5543984074017", source="manual")
    grupos = merge.find_duplicate_groups(db)
    assert len(grupos) == 1
    assert len(grupos[0].absorvidos) == 1


def test_contato_sem_telefone_nunca_entra_num_grupo(db, tenant_id):
    _cria(db, tenant_id, name="Sem Telefone", email="a@x.com", source="manual")
    _cria(db, tenant_id, name="Sem Telefone", email="b@x.com", source="manual")
    assert merge.find_duplicate_groups(db) == []


def test_sobrevivente_e_o_mais_antigo(db, tenant_id):
    """Tem que ser o MESMO critério de `_find_existing`. Se divergisse, `absorb_lead` escolheria
    um card e a mescla outro, e o próximo lead recriaria a divisão.

    `created_at` explícito pela mesma razão de `test_multiplos_candidatos_escolhe_o_mais_antigo`:
    `server_default=func.now()` dá timestamp IDÊNTICO a duas linhas do mesmo segundo (SQLite) ou
    da mesma transação (Postgres), e aí "o mais antigo" deixa de ser observável — o desempate cai
    no uuid e o teste vira moeda."""
    antigo = Client(
        tenant_id=tenant_id, name="Flavio Kato", phone="4384074017",
        phone_key="5543984074017", source="manual",
        created_at=datetime(2026, 7, 1, 10, 0, tzinfo=UTC),
    )
    novo = Client(
        tenant_id=tenant_id, name="Flavio Kato", phone="43984074017",
        phone_key="5543984074017", source="api",
        created_at=datetime(2026, 8, 1, 10, 0, tzinfo=UTC),
    )
    db.add_all([antigo, novo])
    db.commit()

    grupo = merge.find_duplicate_groups(db)[0]
    assert grupo.sobrevivente.id == antigo.id
    assert [c.id for c in grupo.absorvidos] == [novo.id]


# ── A mescla em si ───────────────────────────────────────────────────────────


def test_historico_do_absorvido_migra_para_o_sobrevivente(db, tenant_id):
    sobrevivente = _cria(db, tenant_id, name="Flavio Kato", phone="(43) 98407-4017",
                         source="manual")
    absorvido = _cria(db, tenant_id, name="Flavio Kato", phone="5543984074017", source="api")
    db.add(Charge(
        tenant_id=tenant_id, client_id=absorvido.id, description="Sinal do evento",
        kind="service", method="pix", amount_cents=50_000,
        due_date=date(2026, 9, 1),
    ))
    db.commit()

    resultado = merge.merge_clients(
        db, tenant_id=tenant_id, actor="dono",
        survivor_id=sobrevivente.id, absorbed_ids=[absorvido.id],
    )
    db.commit()

    assert resultado["absorvidos"] == 1
    assert resultado["movidos"]["charges"] == 1
    cobranca = db.scalar(select(Charge))
    assert cobranca.client_id == sobrevivente.id       # a cobrança seguiu o contato...
    assert db.get(Client, absorvido.id) is None        # ...e o card duplicado sumiu


def test_eventos_dos_dois_cards_ficam_na_mesma_linha_do_tempo(db, tenant_id):
    """É a razão de existir da mescla: uma pessoa, uma história."""
    sobrevivente = _cria(db, tenant_id, name="Flavio Kato", phone="(43) 98407-4017",
                         source="manual")
    absorvido = _cria(db, tenant_id, name="Flavio Kato", phone="5543984074017", source="landing")

    merge.merge_clients(db, tenant_id=tenant_id, actor="dono",
                        survivor_id=sobrevivente.id, absorbed_ids=[absorvido.id])
    db.commit()

    eventos = db.scalars(
        select(Fact).where(Fact.client_id == sobrevivente.id)
    ).all()
    assert len(eventos) == 2  # o "crm.lead.criado" de cada card, agora no mesmo fio


def test_complementa_buraco_mas_nunca_sobrescreve(db, tenant_id):
    sobrevivente = _cria(db, tenant_id, name="Flavio Kato", phone="(43) 98407-4017",
                         email="antigo@x.com", source="manual")
    absorvido = _cria(db, tenant_id, name="Flavio Kato", phone="5543984074017",
                      email="novo@x.com", document="52998224725", source="api")

    merge.merge_clients(db, tenant_id=tenant_id, actor="dono",
                        survivor_id=sobrevivente.id, absorbed_ids=[absorvido.id])
    db.commit()
    db.refresh(sobrevivente)

    assert sobrevivente.email == "antigo@x.com"   # tinha valor: intocado
    assert sobrevivente.document == "52998224725"  # estava vazio: complementado


def test_nao_perde_a_observacao_escrita_pelo_dono(db, tenant_id):
    """Texto escrito à mão é o dado mais caro da ficha. Some no card absorvido = some de vez."""
    sobrevivente = _cria(db, tenant_id, name="Flavio Kato", phone="(43) 98407-4017",
                         notes="Prefere contato de manhã", source="manual")
    absorvido = _cria(db, tenant_id, name="Flavio Kato", phone="5543984074017",
                      notes="Indicado pelo Rogério", source="api")

    merge.merge_clients(db, tenant_id=tenant_id, actor="dono",
                        survivor_id=sobrevivente.id, absorbed_ids=[absorvido.id])
    db.commit()
    db.refresh(sobrevivente)

    assert "Prefere contato de manhã" in sobrevivente.notes
    assert "Indicado pelo Rogério" in sobrevivente.notes


def test_junta_as_tags_dos_dois(db, tenant_id):
    sobrevivente = _cria(db, tenant_id, name="Flavio Kato", phone="(43) 98407-4017",
                         tags=["vip"], source="manual")
    absorvido = _cria(db, tenant_id, name="Flavio Kato", phone="5543984074017",
                      tags=["vindo-do-site", "vip"], source="landing")

    merge.merge_clients(db, tenant_id=tenant_id, actor="dono",
                        survivor_id=sobrevivente.id, absorbed_ids=[absorvido.id])
    db.commit()
    db.refresh(sobrevivente)

    assert sobrevivente.tags == ["vindo-do-site", "vip"]  # união, sem repetir


def test_mescla_de_varios_de_uma_vez(db, tenant_id):
    sobrevivente = _cria(db, tenant_id, name="Flavio Kato", phone="(43) 98407-4017",
                         source="manual")
    outros = [
        _cria(db, tenant_id, name="Flavio Kato", phone="5543984074017", source=s)
        for s in ("api", "landing", "whatsapp")
    ]
    merge.merge_clients(db, tenant_id=tenant_id, actor="dono", survivor_id=sobrevivente.id,
                        absorbed_ids=[c.id for c in outros])
    db.commit()
    assert db.scalars(select(Client)).all() == [sobrevivente]


def test_absorbed_ids_vazio_nao_faz_nada(db, tenant_id):
    """Rodar o mesmo comando duas vezes não pode explodir: a segunda passada não acha mais
    duplicado e precisa terminar em silêncio."""
    sobrevivente = _cria(db, tenant_id, name="Flavio Kato", phone="(43) 98407-4017",
                         source="manual")
    resultado = merge.merge_clients(db, tenant_id=tenant_id, actor="dono",
                                    survivor_id=sobrevivente.id, absorbed_ids=[])
    assert resultado == {"movidos": {}, "absorvidos": 0}
    assert db.get(Client, sobrevivente.id) is not None
