"""Grupos de WhatsApp na caixa de entrada (Onda 4).

Defeito de origem, reportado usando a tela com conversas reais: **mensagem de grupo não mostrava
o texto/imagem nem o nome do grupo**. Eram três problemas empilhados:

1. `parse_inbound` só reconhecia `@s.whatsapp.net` — todo `@g.us` virava `from_phone=None`;
2. sem telefone não havia `client_id`, e `client_id` era a ÚNICA identidade de conversa que
   existia, então TODOS os grupos colapsavam no mesmo balde "Não identificados";
3. esse balde tinha `client_id: None` e a tela usava esse nulo como chave de rota — clicar nele
   não abria nada.

Payload de referência: capturado ao vivo da Evolution v2.3.7 em produção (2026-08-04).
"""
from __future__ import annotations

import base64

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core import whatsapp
from app.core.whatsapp.providers import evolution
from app.modules.crm.models import Client
from app.modules.settings import service as settings_service
from app.modules.whatsapp_inbox import service as inbox_service
from app.modules.whatsapp_inbox.models import (
    CHAT_KIND_GROUP,
    WhatsappChat,
    WhatsappMessage,
)
from app.modules.whatsapp_session.models import PublicWhatsappInstance

TENANT_ID = "77777777-7777-7777-7777-777777777777"
GROUP_JID = "120363280378740969@g.us"


def _instancia(db, secret: str) -> None:
    settings_service.get_profile(db, TENANT_ID)
    db.add(PublicWhatsappInstance(
        instance_name="e1p-" + TENANT_ID, tenant_id=TENANT_ID, webhook_secret=secret,
        last_status="connected",
    ))
    db.commit()


def _group_payload(msg_id: str, text: str, *, group_jid: str = GROUP_JID) -> dict:
    """Formato REAL de mensagem de grupo (v2.3.7): `remoteJid` é o grupo, `participant` vem
    mascarado como `@lid` e `participantAlt` traz o telefone de verdade de quem falou."""
    return {
        "data": {
            "key": {
                "remoteJid": group_jid,
                "fromMe": False,
                "id": msg_id,
                "participant": "86170130210977@lid",
                "participantAlt": "555596788686@s.whatsapp.net",
                "addressingMode": "lid",
            },
            "pushName": "Gabriel B",
            "message": {"conversation": text},
        }
    }


# ── parser ───────────────────────────────────────────────────────────────────

def test_parse_group_message_has_no_contact_but_has_a_chat() -> None:
    msg = evolution.parse_inbound(_group_payload("3AB0E02D", "Pessoal, indicação?"))[0]
    assert msg.chat_kind == "group"
    assert msg.chat_jid == GROUP_JID
    # Grupo não tem telefone de conversa e por isso não resolve contato do CRM.
    assert msg.from_phone is None
    # Mas SABEMOS quem falou — de `participantAlt`, não do `@lid` de `participant`.
    assert msg.sender_phone == "555596788686"
    assert msg.sender_name == "Gabriel B"


def test_parse_group_media_keeps_group_identity() -> None:
    payload = _group_payload("3AB0IMG", "")
    payload["data"]["message"] = {
        "imageMessage": {"mimetype": "image/jpeg", "caption": "olha isso"},
        "base64": base64.b64encode(b"bytes").decode(),
    }
    msg = evolution.parse_inbound(payload)[0]
    assert msg.chat_kind == "group"
    assert msg.chat_jid == GROUP_JID
    assert msg.kind == "image"
    assert msg.text_body == "olha isso"


def test_parse_lid_direct_resolves_phone_from_remote_jid_alt() -> None:
    """`remoteJidAlt` é o que tira uma conversa direta do limbo: o `remoteJid` veio mascarado,
    mas o telefone real está ali do lado — eram 60 mensagens em 12h caindo em "Não
    identificados" no tenant do fundador por não lermos este campo."""
    payload = {
        "data": {
            "key": {
                "remoteJid": "86170130210977@lid",
                "remoteJidAlt": "554198746008@s.whatsapp.net",
                "id": "3EB0ALT",
            },
            "pushName": "Contato Real",
            "message": {"conversation": "oi"},
        }
    }
    msg = evolution.parse_inbound(payload)[0]
    assert msg.from_phone == "554198746008"
    # Canônico: a conversa é a MESMA quer o evento chegue como @lid, quer como @s.whatsapp.net.
    assert msg.chat_jid == "554198746008@s.whatsapp.net"
    assert msg.chat_kind == "direct"


def test_parse_lid_without_alt_never_invents_a_phone() -> None:
    payload = {
        "data": {
            "key": {"remoteJid": "86170130210977@lid", "id": "3EB0SEMALT"},
            "pushName": "Sem Numero",
            "message": {"conversation": "oi"},
        }
    }
    msg = evolution.parse_inbound(payload)[0]
    assert msg.from_phone is None  # `@lid` NÃO é telefone, mesmo parecendo um
    assert msg.chat_jid == "86170130210977@lid"  # a conversa existe mesmo assim


# ── ingest ───────────────────────────────────────────────────────────────────

def test_group_message_creates_a_group_chat_and_no_crm_contact(
    client: TestClient, db, monkeypatch
) -> None:
    """A decisão de produto em forma de teste: grupo aparece em Conversas e NUNCA vira contato
    do CRM — senão o funil de vendas e o painel de inadimplência enchem de grupo."""
    monkeypatch.setattr(whatsapp, "fetch_group_subject", lambda **_kw: "Automação Residencial")
    _instancia(db, "segredo-grupo")

    assert client.post(
        "/internal/whatsapp/evolution/webhook/segredo-grupo",
        json=_group_payload("3AB0G1", "Pessoal, indicação de fechadura?"),
    ).status_code == 200

    chat = db.scalar(select(WhatsappChat).where(WhatsappChat.chat_jid == GROUP_JID))
    assert chat is not None
    assert chat.kind == CHAT_KIND_GROUP
    assert chat.title == "Automação Residencial"
    assert chat.client_id is None
    assert db.scalar(select(Client)) is None  # nada foi criado no CRM

    msg = db.scalar(select(WhatsappMessage).where(WhatsappMessage.wa_message_id == "3AB0G1"))
    assert msg.chat_id == chat.id
    assert msg.sender_name == "Gabriel B"
    assert msg.text_body == "Pessoal, indicação de fechadura?"


def test_two_groups_are_two_conversations(client: TestClient, db, monkeypatch) -> None:
    """O defeito reportado: TODOS os grupos caíam na mesma linha."""
    monkeypatch.setattr(whatsapp, "fetch_group_subject", lambda **_kw: None)
    _instancia(db, "segredo-2grupos")
    outro = "5521996087371-1584122764@g.us"

    for i, jid in enumerate((GROUP_JID, outro)):
        assert client.post(
            "/internal/whatsapp/evolution/webhook/segredo-2grupos",
            json=_group_payload(f"3AB0M{i}", f"msg {i}", group_jid=jid),
        ).status_code == 200

    conversas = inbox_service.list_conversations(db, TENANT_ID)
    assert len(conversas) == 2
    assert {c["kind"] for c in conversas} == {"group"}


def test_group_without_a_known_name_says_so(client: TestClient, db, monkeypatch) -> None:
    """A Evolution não respondeu o assunto (desligada, timeout, dono saiu do grupo). O rótulo
    admite que não sabemos em vez de inventar um nome."""
    monkeypatch.setattr(whatsapp, "fetch_group_subject", lambda **_kw: None)
    _instancia(db, "segredo-sem-nome")

    client.post(
        "/internal/whatsapp/evolution/webhook/segredo-sem-nome",
        json=_group_payload("3AB0SN", "oi"),
    )

    conversas = inbox_service.list_conversations(db, TENANT_ID)
    assert conversas[0]["title"] == "Grupo sem nome"


def test_group_name_is_fetched_once_not_per_message(
    client: TestClient, db, monkeypatch
) -> None:
    """Sem o carimbo `title_checked_at`, um grupo cujo nome falhou consultaria a Evolution a
    cada mensagem recebida — chamada de rede no caminho do webhook."""
    chamadas = {"n": 0}

    def _conta(**_kw):
        chamadas["n"] += 1
        return None

    monkeypatch.setattr(whatsapp, "fetch_group_subject", _conta)
    _instancia(db, "segredo-1vez")

    for i in range(3):
        client.post(
            "/internal/whatsapp/evolution/webhook/segredo-1vez",
            json=_group_payload(f"3AB0R{i}", f"msg {i}"),
        )

    assert chamadas["n"] == 1


def test_sender_shows_in_group_timeline_but_not_in_direct(
    client: TestClient, db, monkeypatch
) -> None:
    """Em grupo o autor de cada bolha é informação essencial; em conversa direta seria ruído."""
    monkeypatch.setattr(whatsapp, "fetch_group_subject", lambda **_kw: "Grupo X")
    _instancia(db, "segredo-autor")

    client.post(
        "/internal/whatsapp/evolution/webhook/segredo-autor",
        json=_group_payload("3AB0AU", "quem sabe?"),
    )
    client.post(
        "/internal/whatsapp/evolution/webhook/segredo-autor",
        json={"data": {
            "key": {"remoteJid": "5511988887777@s.whatsapp.net", "id": "3EB0DIR"},
            "pushName": "Maria", "message": {"conversation": "oi"},
        }},
    )

    grupo = db.scalar(select(WhatsappChat).where(WhatsappChat.chat_jid == GROUP_JID))
    direta = db.scalar(
        select(WhatsappChat).where(WhatsappChat.chat_jid == "5511988887777@s.whatsapp.net")
    )
    assert inbox_service.get_timeline(db, chat_id=grupo.id)[0]["sender_name"] == "Gabriel B"
    assert inbox_service.get_timeline(db, chat_id=direta.id)[0]["sender_name"] is None


def test_group_preview_names_who_spoke(client: TestClient, db, monkeypatch) -> None:
    monkeypatch.setattr(whatsapp, "fetch_group_subject", lambda **_kw: "Grupo X")
    _instancia(db, "segredo-preview")
    client.post(
        "/internal/whatsapp/evolution/webhook/segredo-preview",
        json=_group_payload("3AB0PV", "bom dia"),
    )
    conversas = inbox_service.list_conversations(db, TENANT_ID)
    assert conversas[0]["last_message_preview"] == "Gabriel B: bom dia"


# ── resposta ─────────────────────────────────────────────────────────────────

def test_reply_to_group_goes_to_the_group_jid(db, monkeypatch) -> None:
    """A Evolution aceita o JID inteiro no campo `number` — responder no grupo é mandar pro
    `@g.us`, não pro telefone de ninguém."""
    settings_service.get_profile(db, TENANT_ID)
    chat = WhatsappChat(
        tenant_id=TENANT_ID, chat_jid=GROUP_JID, kind=CHAT_KIND_GROUP, title="Grupo X",
    )
    db.add(chat)
    db.commit()

    capturado = {}
    monkeypatch.setattr(
        whatsapp, "send_text", lambda **kw: (capturado.update(kw), "sent")[1]
    )
    msg = inbox_service.send_reply_text(
        db, tenant_id=TENANT_ID, actor="user-1", chat_id=chat.id, text="Tenho uma indicação",
    )

    assert capturado["to"] == GROUP_JID
    assert msg.direction == "out"
    assert msg.chat_id == chat.id
    assert msg.client_id is None  # a resposta num grupo também não cria vínculo de CRM


def test_group_ignores_the_24h_window(db) -> None:
    """A janela de 24h é regra da Cloud API da Meta, que nem tem grupos. Exigi-la aqui deixaria
    o grupo mudo por engano — e nem template existiria pra destravar."""
    settings_service.get_profile(db, TENANT_ID)
    chat = WhatsappChat(
        tenant_id=TENANT_ID, chat_jid=GROUP_JID, kind=CHAT_KIND_GROUP, title="Grupo X",
    )
    db.add(chat)
    db.commit()
    # Nenhuma mensagem recebida: numa conversa direta isto seria "janela fechada".
    assert inbox_service.is_within_session_window(db, chat_id=chat.id) is True


def test_group_rejects_template_reply(db) -> None:
    settings_service.get_profile(db, TENANT_ID)
    chat = WhatsappChat(
        tenant_id=TENANT_ID, chat_jid=GROUP_JID, kind=CHAT_KIND_GROUP, title="Grupo X",
    )
    db.add(chat)
    db.commit()
    try:
        inbox_service.send_reply_template(
            db, tenant_id=TENANT_ID, actor="user-1", chat_id=chat.id,
            template_id="qualquer", variables=[],
        )
    except inbox_service.WhatsappInboxError as exc:
        assert "Grupo não usa template" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("deveria ter recusado")
