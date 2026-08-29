"""A self-chat da Vima roteia para `vima/whatsapp_conversa`, não para o inbox normal — e as
outras três formas de `from_me`/`da_equipe` continuam se comportando como antes (regressão)."""
from sqlalchemy import select

from app.core.whatsapp.inbound import InboundMessage
from app.modules.auth.models import User
from app.modules.crm.models import Client
from app.modules.vima import whatsapp_conversa as vc
from app.modules.whatsapp_inbox import service as inbox_service
from app.modules.whatsapp_inbox.models import WhatsappChat, WhatsappMessage

TENANT_ID = "22222222-2222-2222-2222-222222222222"


def _self_chat_msg(**over) -> InboundMessage:
    base = dict(
        wa_message_id="self.1", from_phone="5511988889999", kind="text",
        text_body="quanto tenho a receber?", media_ref=None, push_name="Dono",
        from_me=True, chat_jid="5511988889999@s.whatsapp.net",
    )
    base.update(over)
    return InboundMessage(**base)


def test_self_chat_roteia_para_vima_sem_gravar_no_crm(db, monkeypatch):
    user = User(
        tenant_id=TENANT_ID, email="dono@example.com", name="Dono", password_hash="x",
        phone="5511988889999",
    )
    db.add(user)
    db.commit()

    chamada = {}

    def _fake_responder(db, *, tenant_id, phone, wa_message_id, texto, profile):
        chamada.update(
            tenant_id=tenant_id, phone=phone, wa_message_id=wa_message_id, texto=texto,
        )

    monkeypatch.setattr(vc, "responder", _fake_responder)

    inbox_service.ingest_webhook_payload(db, tenant_id=TENANT_ID, messages=[_self_chat_msg()])

    assert chamada == {
        "tenant_id": TENANT_ID, "phone": "5511988889999",
        "wa_message_id": "self.1", "texto": "quanto tenho a receber?",
    }
    assert db.scalar(select(WhatsappMessage)) is None
    assert db.scalar(select(WhatsappChat)) is None
    assert db.scalar(select(Client)) is None


def test_audio_na_self_chat_roteia_para_responder_audio(db, monkeypatch):
    user = User(
        tenant_id=TENANT_ID, email="dono2@example.com", name="Dono", password_hash="x",
        phone="5511988880001",
    )
    db.add(user)
    db.commit()

    chamada = {}

    def _fake_responder_audio(
        db, *, tenant_id, phone, wa_message_id, audio_bytes, audio_mime_type, profile,
    ):
        chamada.update(
            tenant_id=tenant_id, phone=phone, wa_message_id=wa_message_id,
            audio_bytes=audio_bytes, audio_mime_type=audio_mime_type,
        )

    monkeypatch.setattr(vc, "responder_audio", _fake_responder_audio)

    inbox_service.ingest_webhook_payload(
        db, tenant_id=TENANT_ID,
        messages=[_self_chat_msg(
            wa_message_id="self.audio", kind="audio", text_body="",
            from_phone="5511988880001", chat_jid="5511988880001@s.whatsapp.net",
            media_bytes=b"\x00\x01audio-bytes", media_mime_type="audio/ogg",
        )],
    )

    assert chamada == {
        "tenant_id": TENANT_ID, "phone": "5511988880001", "wa_message_id": "self.audio",
        "audio_bytes": b"\x00\x01audio-bytes", "audio_mime_type": "audio/ogg",
    }
    assert db.scalar(select(WhatsappMessage)) is None  # não gravou no inbox normal
    assert db.scalar(select(Client)) is None  # não virou lead


def test_imagem_na_self_chat_continua_no_caminho_normal_sem_erro(db, monkeypatch):
    # Só texto e áudio viram pergunta à Vima; outra mídia (imagem/documento/vídeo) continua
    # caindo no comportamento JÁ EXISTENTE (grava mensagem, sem virar lead) — o ponto de
    # extensão que a fatia de texto deixou marcado, agora restrito ao que não é áudio.
    user = User(
        tenant_id=TENANT_ID, email="dono2b@example.com", name="Dono", password_hash="x",
        phone="5511988880009",
    )
    db.add(user)
    db.commit()

    chamado = {"n": 0}
    monkeypatch.setattr(vc, "responder", lambda *a, **kw: chamado.update(n=chamado["n"] + 1))
    monkeypatch.setattr(
        vc, "responder_audio", lambda *a, **kw: chamado.update(n=chamado["n"] + 1)
    )

    inbox_service.ingest_webhook_payload(
        db, tenant_id=TENANT_ID,
        messages=[_self_chat_msg(
            wa_message_id="self.imagem", kind="image", text_body="",
            from_phone="5511988880009", chat_jid="5511988880009@s.whatsapp.net",
        )],
    )

    assert chamado["n"] == 0  # não roteou para a Vima
    row = db.scalar(select(WhatsappMessage).where(WhatsappMessage.wa_message_id == "self.imagem"))
    assert row is not None  # gravou normalmente, como antes desta feature
    assert db.scalar(select(Client)) is None


def test_dono_respondendo_cliente_pelo_proprio_celular_nao_e_self_chat(db, monkeypatch):
    # from_me=True, mas a CONTRAPARTE é um cliente, não um usuário do tenant — não é self-chat.
    chamado = {"n": 0}
    monkeypatch.setattr(vc, "responder", lambda *a, **kw: chamado.update(n=chamado["n"] + 1))

    existing = Client(
        tenant_id=TENANT_ID, name="Cliente", phone="5511977776666", source="manual",
    )
    db.add(existing)
    db.commit()

    inbox_service.ingest_webhook_payload(
        db, tenant_id=TENANT_ID,
        messages=[_self_chat_msg(
            wa_message_id="reply.cliente", from_phone="5511977776666", text_body="já te retorno",
            chat_jid="5511977776666@s.whatsapp.net",
        )],
    )

    assert chamado["n"] == 0
    row = db.scalar(
        select(WhatsappMessage).where(WhatsappMessage.wa_message_id == "reply.cliente")
    )
    assert row is not None
    assert row.direction == "out"  # comportamento pré-existente, inalterado


def test_cliente_comum_nao_aciona_a_vima(db, monkeypatch):
    chamado = {"n": 0}
    monkeypatch.setattr(vc, "responder", lambda *a, **kw: chamado.update(n=chamado["n"] + 1))

    inbox_service.ingest_webhook_payload(
        db, tenant_id=TENANT_ID,
        messages=[_self_chat_msg(
            wa_message_id="cliente.1", from_phone="5511966665555", from_me=False,
            text_body="oi, quero saber do produto", chat_jid="5511966665555@s.whatsapp.net",
        )],
    )

    assert chamado["n"] == 0
    client = db.scalar(select(Client).where(Client.phone == "5511966665555"))
    assert client is not None  # vira lead normalmente, como sempre
