"""A self-chat da Vima roteia para `vima/whatsapp_conversa`, não para o inbox normal — e as
outras três formas de `from_me`/`da_equipe` continuam se comportando como antes (regressão).

O gatilho de self-chat compara `from_phone` contra `whatsapp_session.connected_phone` — o
telefone REALMENTE conectado via Evolution (lido do `ownerJid`), não contra `User.role` nem
contra "qualquer usuário ativo do tenant". `_conectado` abaixo simula essa resposta sem bater
na rede de verdade; cada teste escolhe qual telefone está "conectado" para o cenário dele."""
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


def _conectado(monkeypatch, phone: str | None) -> None:
    monkeypatch.setattr(
        inbox_service.whatsapp_session_service, "connected_phone", lambda tenant_id: phone,
    )


def test_self_chat_roteia_para_vima_sem_gravar_no_crm(db, monkeypatch):
    user = User(
        tenant_id=TENANT_ID, email="dono@example.com", name="Dono", password_hash="x",
        phone="5511988889999",
    )
    db.add(user)
    db.commit()
    _conectado(monkeypatch, "5511988889999")

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


def test_self_chat_grava_pergunta_e_resposta_quando_a_vima_respondeu(db, monkeypatch):
    """`responder` devolveu um `Resultado` (perguntou e respondeu de verdade, não foi eco nem
    reentrega) — a troca precisa aparecer na tela de Conversas, senão o dono não tem como saber
    o que a Vima andou dizendo pelo self-chat (achado ao investigar o loop de #280: a self-chat
    inteira era invisível pro banco)."""
    user = User(
        tenant_id=TENANT_ID, email="dono4@example.com", name="Dono", password_hash="x",
        phone="5511988889001",
    )
    db.add(user)
    db.commit()
    _conectado(monkeypatch, "5511988889001")

    monkeypatch.setattr(
        vc, "responder",
        lambda *a, **kw: vc.Resultado(
            pergunta="quanto tenho a receber?", resposta="Você tem R$ 500,00 a receber.",
        ),
    )

    inbox_service.ingest_webhook_payload(
        db, tenant_id=TENANT_ID,
        messages=[_self_chat_msg(
            wa_message_id="self.grava", from_phone="5511988889001",
            text_body="quanto tenho a receber?", chat_jid="5511988889001@s.whatsapp.net",
        )],
    )

    chat = db.scalar(
        select(WhatsappChat).where(WhatsappChat.chat_jid == "5511988889001@s.whatsapp.net")
    )
    assert chat is not None
    assert chat.client_id is None  # self-chat continua sem virar contato do CRM

    mensagens = db.scalars(
        select(WhatsappMessage).where(WhatsappMessage.chat_id == chat.id)
        .order_by(WhatsappMessage.created_at)
    ).all()
    assert [(m.direction, m.text_body) for m in mensagens] == [
        ("out", "quanto tenho a receber?"),
        ("out", "Você tem R$ 500,00 a receber."),
    ]
    assert mensagens[0].wa_message_id == "self.grava"
    assert mensagens[0].client_id is None
    assert mensagens[1].client_id is None
    assert db.scalar(select(Client)) is None  # ainda não vira lead


def test_self_chat_nao_grava_nada_quando_responder_devolve_none(db, monkeypatch):
    # Eco da própria resposta, reentrega, ou telefone sem usuário — `responder` devolve `None` e
    # não há nada de novo a gravar (regressão: não pode duplicar nem criar ruído na conversa).
    user = User(
        tenant_id=TENANT_ID, email="dono5@example.com", name="Dono", password_hash="x",
        phone="5511988889002",
    )
    db.add(user)
    db.commit()
    _conectado(monkeypatch, "5511988889002")

    monkeypatch.setattr(vc, "responder", lambda *a, **kw: None)

    inbox_service.ingest_webhook_payload(
        db, tenant_id=TENANT_ID,
        messages=[_self_chat_msg(
            wa_message_id="self.nada", from_phone="5511988889002",
            chat_jid="5511988889002@s.whatsapp.net",
        )],
    )

    assert db.scalar(select(WhatsappMessage)) is None
    assert db.scalar(select(WhatsappChat)) is None


def test_audio_na_self_chat_grava_pergunta_com_kind_audio(db, monkeypatch):
    user = User(
        tenant_id=TENANT_ID, email="dono6@example.com", name="Dono", password_hash="x",
        phone="5511988889003",
    )
    db.add(user)
    db.commit()
    _conectado(monkeypatch, "5511988889003")

    monkeypatch.setattr(
        vc, "responder_audio",
        lambda *a, **kw: vc.Resultado(
            pergunta="quanto tenho a receber?",
            resposta='🎤 "quanto tenho a receber?" — R$ 500,00',
        ),
    )

    inbox_service.ingest_webhook_payload(
        db, tenant_id=TENANT_ID,
        messages=[_self_chat_msg(
            wa_message_id="self.audio.grava", kind="audio", text_body="",
            from_phone="5511988889003", chat_jid="5511988889003@s.whatsapp.net",
            media_bytes=b"\x00\x01audio-bytes", media_mime_type="audio/ogg",
        )],
    )

    chat = db.scalar(
        select(WhatsappChat).where(WhatsappChat.chat_jid == "5511988889003@s.whatsapp.net")
    )
    assert chat is not None
    mensagens = db.scalars(
        select(WhatsappMessage).where(WhatsappMessage.chat_id == chat.id)
        .order_by(WhatsappMessage.created_at)
    ).all()
    assert [m.kind for m in mensagens] == ["audio", "text"]
    assert mensagens[0].text_body == "quanto tenho a receber?"
    assert mensagens[1].text_body == '🎤 "quanto tenho a receber?" — R$ 500,00'


def test_audio_na_self_chat_roteia_para_responder_audio(db, monkeypatch):
    user = User(
        tenant_id=TENANT_ID, email="dono2@example.com", name="Dono", password_hash="x",
        phone="5511988880001",
    )
    db.add(user)
    db.commit()
    _conectado(monkeypatch, "5511988880001")

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
    _conectado(monkeypatch, "5511988880009")

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
    # from_me=True, mas a CONTRAPARTE é um cliente, não o número conectado — não é self-chat.
    _conectado(monkeypatch, "5511988889999")
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
    _conectado(monkeypatch, "5511988889999")
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


def test_conversa_com_sub_user_cadastrado_mas_nao_conectado_nao_e_self_chat(db, monkeypatch):
    """`from_me=True` e a contraparte é telefone de um `sub_user` ATIVO do tenant — mas o
    número REALMENTE conectado via Evolution (`connected_phone`) é outro (o do `owner`, neste
    cenário). Isso não é self-chat: é o dono conversando NORMALMENTE com um colega de equipe
    pelo mesmo WhatsApp. Achado ao vivo em produção 2026-08-31: bater com QUALQUER telefone de
    equipe cadastrado (em vez do telefone REALMENTE conectado) fazia a Vima sequestrar essa
    conversa e responder no lugar da pessoa."""
    owner = User(
        tenant_id=TENANT_ID, email="dono3@example.com", name="Dono", password_hash="x",
        phone="5511988880099", role="owner",
    )
    sub_user = User(
        tenant_id=TENANT_ID, email="colega@example.com", name="Colega", password_hash="x",
        phone="5511977778888", role="sub_user",
    )
    db.add_all([owner, sub_user])
    db.commit()
    _conectado(monkeypatch, "5511988880099")  # o número conectado é o do OWNER, não o do colega

    chamado = {"n": 0}
    monkeypatch.setattr(vc, "responder", lambda *a, **kw: chamado.update(n=chamado["n"] + 1))

    inbox_service.ingest_webhook_payload(
        db, tenant_id=TENANT_ID,
        messages=[_self_chat_msg(
            wa_message_id="colega.1", from_phone="5511977778888",
            text_body="te mandei o link do produto", chat_jid="5511977778888@s.whatsapp.net",
        )],
    )

    assert chamado["n"] == 0  # não roteou para a Vima
    row = db.scalar(select(WhatsappMessage).where(WhatsappMessage.wa_message_id == "colega.1"))
    assert row is not None  # grava normalmente, como qualquer conversa com a equipe
    assert row.direction == "out"


def test_self_chat_funciona_para_sub_user_cujo_telefone_e_o_conectado(db, monkeypatch):
    """O espelho do teste acima: quando o número REALMENTE conectado é o de um `sub_user`
    (cenário real de produção: o WhatsApp do tenant está no celular de um funcionário, não do
    `owner` cadastrado), a self-chat DELE funciona normalmente — `role` não entra na decisão,
    só o telefone conectado."""
    sub_user = User(
        tenant_id=TENANT_ID, email="funcionario@example.com", name="Funcionário",
        password_hash="x", phone="5511977778888", role="sub_user",
    )
    db.add(sub_user)
    db.commit()
    _conectado(monkeypatch, "5511977778888")  # o WhatsApp conectado é o do sub_user

    chamada = {}
    monkeypatch.setattr(
        vc, "responder",
        lambda db, *, tenant_id, phone, wa_message_id, texto, profile: chamada.update(
            phone=phone, texto=texto,
        ),
    )

    inbox_service.ingest_webhook_payload(
        db, tenant_id=TENANT_ID,
        messages=[_self_chat_msg(
            wa_message_id="funcionario.1", from_phone="5511977778888",
            text_body="quanto tenho a receber?", chat_jid="5511977778888@s.whatsapp.net",
        )],
    )

    assert chamada == {"phone": "5511977778888", "texto": "quanto tenho a receber?"}
