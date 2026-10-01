"""Código de origem na 1ª mensagem de WhatsApp de um contato novo (spec §6.3)."""
import json

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import events
from app.core.facts import Fact
from app.core.whatsapp.inbound import InboundMessage
from app.modules.crm.models import Client
from app.modules.settings import service as settings_service
from app.modules.whatsapp_inbox import service as inbox_service

TENANT = "11111111-1111-1111-1111-111111111111"
FONE = "5511977776666"


@pytest.fixture(autouse=True)
def _sem_assinantes():
    events.clear()
    yield
    events.clear()


def _produto(db: Session, produto: str = "publia") -> None:
    perfil = settings_service.get_profile(db, TENANT)
    perfil.lead_ingest_config = {"produto": produto}
    db.commit()


def _recebe(db: Session, texto: str, *, msg_id: str = "wamid.1") -> None:
    inbox_service.ingest_webhook_payload(
        db, tenant_id=TENANT,
        messages=[InboundMessage(
            wa_message_id=msg_id, from_phone=FONE, kind="text", text_body=texto,
            media_ref=None, push_name="Maria",
        )],
    )


def _contato(db: Session) -> Client:
    return db.scalar(select(Client).where(Client.phone_key == FONE))


def _fatos_de_origem(db: Session, client_id: str) -> list[Fact]:
    return list(db.scalars(
        select(Fact).where(
            Fact.client_id == client_id, Fact.kind == "comercial.origem.identificada"
        )
    ).all())


def test_primeira_mensagem_com_codigo_aplica_origem_post_e_lead_whatsapp(db: Session):
    _produto(db)
    _recebe(db, "Olá! Quero saber da Publ.IA (código ig-r-c8abc)")
    contato = _contato(db)
    assert contato.source == "whatsapp"
    assert contato.tags == ["origem:instagram", "post:ig-r-c8abc", "publia:lead-whatsapp"]
    [fato] = _fatos_de_origem(db, contato.id)
    assert json.loads(fato.body)["codigo"] == "ig-r-c8abc"


def test_codigo_em_maiusculas_e_com_espacos_e_lido(db: Session):
    _produto(db)
    _recebe(db, "Olá!   CODIGO    IG-S-OUT26A  obrigado")
    assert "post:ig-s-out26a" in _contato(db).tags


def test_np_lp_marca_lead_whatsapp_sem_inventar_origem(db: Session):
    _produto(db)
    _recebe(db, "Olá! Quero saber da Publ.IA (código np-lp)")
    assert _contato(db).tags == ["publia:lead-whatsapp"]


def test_contato_que_ja_existia_nao_e_relido(db: Session):
    _produto(db)
    db.add(Client(tenant_id=TENANT, name="Maria", phone=FONE, phone_key=FONE, source="landing"))
    db.commit()
    _recebe(db, "Oi de novo (código ig-r-c8abc)")
    contato = _contato(db)
    assert contato.tags == []
    assert _fatos_de_origem(db, contato.id) == []


def test_segunda_mensagem_do_contato_novo_nao_troca_a_origem(db: Session):
    _produto(db)
    _recebe(db, "Olá (código ig-r-c8abc)", msg_id="wamid.1")
    _recebe(db, "achei também pelo google (código gg-s-xyz1)", msg_id="wamid.2")
    tags = _contato(db).tags
    assert "post:ig-r-c8abc" in tags
    assert "post:gg-s-xyz1" not in tags


def test_sem_produto_configurado_a_leitura_fica_desligada(db: Session):
    _recebe(db, "Olá (código ig-r-c8abc)")
    contato = _contato(db)
    assert contato.tags == []
    assert _fatos_de_origem(db, contato.id) == []


def test_mensagem_sem_codigo_so_cria_o_contato(db: Session):
    _produto(db)
    _recebe(db, "Oi, quanto custa?")
    contato = _contato(db)
    assert contato is not None
    assert contato.tags == []


def test_texto_vazio_ou_ausente_nao_atribui_nem_quebra(db: Session):
    _produto(db)
    inbox_service.ingest_webhook_payload(
        db, tenant_id=TENANT,
        messages=[InboundMessage(
            wa_message_id="wamid.vazio", from_phone=FONE, kind="text", text_body=None,
            media_ref=None, push_name="Maria",
        )],
    )
    contato = _contato(db)
    assert contato is not None
    assert contato.tags == []
    assert _fatos_de_origem(db, contato.id) == []


def test_falha_na_atribuicao_nao_perde_a_mensagem(db: Session, monkeypatch):
    from app.core import facts as facts_mod
    from app.modules.lead_ingest import whatsapp as aplicador
    from app.modules.whatsapp_inbox.models import WhatsappMessage

    _produto(db)
    original = facts_mod.record

    def explode_so_na_origem(*args, **kwargs):
        if kwargs.get("kind") == "comercial.origem.identificada":
            raise RuntimeError("falha injetada")
        return original(*args, **kwargs)

    monkeypatch.setattr(aplicador.facts, "record", explode_so_na_origem)
    _recebe(db, "Olá (código ig-r-c8abc)")
    contato = _contato(db)
    assert contato is not None
    assert contato.tags == []
    assert _fatos_de_origem(db, contato.id) == []
    assert db.scalar(
        select(WhatsappMessage).where(WhatsappMessage.wa_message_id == "wamid.1")
    ) is not None
    recebida = db.scalars(select(Fact).where(
        Fact.client_id == contato.id, Fact.kind == "comercial.mensagem.recebida"
    )).all()
    assert len(recebida) == 1
