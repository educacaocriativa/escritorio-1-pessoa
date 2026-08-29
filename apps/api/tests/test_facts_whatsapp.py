"""Mensagem recebida vira fato — e a do próprio time não vira lead.

O guard de telefone da equipe fecha um bug que já existe hoje (o dono que escreve para o
próprio número entra no funil de vendas) e que o opt-in do briefing por botão na Meta (Onda 4)
tornaria diário.
"""
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.facts import COM_MENSAGEM_RECEBIDA, Fact
from app.core.whatsapp.inbound import InboundMessage
from app.modules.auth.models import Tenant, User
from app.modules.crm.models import Client
from app.modules.whatsapp_inbox import service as inbox

REGISTER = {
    "legal_name": "Estúdio Ana", "document": "11222333000181", "slug": "estudioana",
    "email": "ana@example.com", "name": "Ana", "password": "senha-bem-comprida",
}


@pytest.fixture()
def tenant_id(client: TestClient, db) -> str:
    client.post("/auth/register", json=REGISTER)
    return db.scalar(select(Tenant.id))


def _msg(telefone: str, texto: str, *, wa_id: str = "MSG1") -> InboundMessage:
    return InboundMessage(
        wa_message_id=wa_id, from_phone=telefone, kind="text", text_body=texto,
        media_ref=None, push_name="Contato",
        chat_jid=f"{telefone}@s.whatsapp.net",
    )


def test_mensagem_de_contato_vira_fato(client: TestClient, db, tenant_id):
    inbox.ingest_webhook_payload(
        db, tenant_id=tenant_id, messages=[_msg("5511999998888", "oi, tudo bem?")]
    )

    fato = db.query(Fact).filter(Fact.kind == COM_MENSAGEM_RECEBIDA).one()
    assert fato.module == "comercial"
    assert fato.client_id is not None
    assert fato.subject_type == "whatsapp_chat"
    assert "escreveu no WhatsApp" in fato.title


def test_mensagem_do_proprio_time_nao_vira_lead_nem_fato(client: TestClient, db, tenant_id):
    """Pelo caminho normal, `_get_or_create_client` criaria um contato para o dono — e ele
    apareceria no próprio funil de vendas e no painel de inadimplência."""
    dono = db.scalar(select(User).where(User.tenant_id == tenant_id))
    dono.phone = "5511977776666"
    db.commit()

    antes = db.query(Client).count()
    inbox.ingest_webhook_payload(
        db, tenant_id=tenant_id, messages=[_msg(dono.phone, "Ver briefing", wa_id="BTN1")]
    )

    assert db.query(Client).count() == antes
    assert db.query(Fact).filter(Fact.kind == COM_MENSAGEM_RECEBIDA).count() == 0


def test_fato_usa_o_instante_real_da_mensagem_nao_o_do_processamento(
    client: TestClient, db, tenant_id
):
    """A dívida registrada em CLAUDE.md: sem `occurred_at` vindo do provider, o fato sempre
    nascia com `now()` — uma mensagem de 23h59 processada à 00h01 entrava no briefing do dia
    seguinte em vez do dia dela."""
    instante_real = datetime(2026, 8, 27, 23, 59, 0, tzinfo=UTC)
    inbox.ingest_webhook_payload(
        db, tenant_id=tenant_id,
        messages=[InboundMessage(
            wa_message_id="MSG-TS", from_phone="5511999998888", kind="text",
            text_body="boa noite", media_ref=None, push_name="Contato",
            chat_jid="5511999998888@s.whatsapp.net", occurred_at=instante_real,
        )],
    )

    # SQLite (a suíte inteira roda contra ele) não preserva tzinfo na volta do banco — o
    # `DateTime(timezone=True)` da coluna é honrado só no Postgres real. `.replace(tzinfo=UTC)`
    # reafirma o que a coluna já promete, não uma suposição nova.
    fato = db.query(Fact).filter(Fact.kind == COM_MENSAGEM_RECEBIDA).one()
    assert fato.occurred_at.replace(tzinfo=UTC) == instante_real


def test_fato_sem_carimbo_do_provider_cai_no_agora(client: TestClient, db, tenant_id):
    """`occurred_at=None` (provider não entregou) não é erro — `facts.record` cai no
    `datetime.now(UTC)` de sempre. Controle: `_msg` (acima) não passa `occurred_at`."""
    antes = datetime.now(UTC)
    inbox.ingest_webhook_payload(
        db, tenant_id=tenant_id, messages=[_msg("5511999998888", "oi")]
    )
    depois = datetime.now(UTC)

    fato = db.query(Fact).filter(Fact.kind == COM_MENSAGEM_RECEBIDA).one()
    assert antes <= fato.occurred_at.replace(tzinfo=UTC) <= depois


def test_mensagem_espelhada_do_dono_nao_vira_fato(client: TestClient, db, tenant_id):
    """`from_me` é o que o dono digitou no aparelho dele, espelhado pelo Baileys.

    Reportar de volta no briefing o que ele mesmo escreveu é eco, não notícia.
    """
    espelhada = InboundMessage(
        wa_message_id="MIRROR1", from_phone="5511999998888", kind="text",
        text_body="já respondi", media_ref=None, push_name="Ana", from_me=True,
        chat_jid="5511999998888@s.whatsapp.net",
    )
    inbox.ingest_webhook_payload(db, tenant_id=tenant_id, messages=[espelhada])

    assert db.query(Fact).filter(Fact.kind == COM_MENSAGEM_RECEBIDA).count() == 0
