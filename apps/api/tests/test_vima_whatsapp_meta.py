"""Meta em dois tempos: template com botão → ele toca → a janela abre → sai o texto inteiro.

Por que dois tempos: parâmetro de template da Cloud API **não aceita quebra de linha** (e o
briefing tem várias), e às 7h o dono está sempre fora da janela de 24h. O único jeito de mandar o
texto livre é ele falar primeiro — e o toque num botão de resposta rápida é a forma mais barata de
"falar" que existe.

⚠️ O formato do webhook foi conferido contra a documentação da Meta, não suposto:
`messages[].type == "button"` com `button: {payload, text}` para botão de TEMPLATE; e
`type == "interactive"` com `interactive.button_reply.{id,title}` para botão interativo.
"""
from __future__ import annotations

import dataclasses
from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core import facts
from app.core.facts import FIN_PAGAMENTO_RECEBIDO
from app.core.whatsapp.providers import meta as meta_provider
from app.modules.auth.models import User
from app.modules.crm.models import Client
from app.modules.notifications.models import Notification
from app.modules.receivables.models import METHOD_PIX, STATUS_PAID, Charge
from app.modules.settings.models import TenantProfile
from app.modules.vima.scheduler import PAYLOAD_BOTAO_BRIEFING, tick
from app.modules.wallet.models import KIND_SERVICE
from app.modules.whatsapp_inbox.service import ingest_webhook_payload
from app.modules.whatsapp_templates.models import (
    PURPOSE_VIMA_BRIEFING,
    PURPOSE_VIMA_BRIEFING_TEXTO,
    STATUS_APPROVED,
    WhatsappTemplate,
)

REGISTER = {
    "legal_name": "Vima ME",
    "document": "11444777000161",
    "slug": "vimame",
    "email": "vima@example.com",
    "name": "Flávio Kato",
    "password": "uma-senha-bem-grande",
}

TELEFONE = "5543984074017"

_SP = ZoneInfo("America/Sao_Paulo")


def _sete_e_cinco_de_hoje() -> datetime:
    """07:05 no fuso do tenant, **no dia de HOJE de verdade**.

    ⚠️ Não fixe a data aqui. Este arquivo injeta o relógio numa ponta (`tick(agora=...)`) e a
    outra ponta lê o relógio de parede: `responder_optin` resolve o dia com `hoje_do_tenant(db)`,
    sem `now` injetado, porque é uma FRONTEIRA — o toque no botão acontece agora, e é o briefing
    de hoje que ele libera. Com uma data literal, o briefing gerado e o procurado passam a ser de
    dias diferentes assim que a suíte cruza a meia-noite.

    Aconteceu: a versão anterior usava `datetime(2026, 8, 6, 10, 5, UTC)`, passou local às 23h de
    São Paulo do dia 6 e reprovou no CI às 00:01 do dia 7 (PR #90). O `tick` só compara a HORA
    local com `briefing_hour`, então derivar o dia do relógio real não afrouxa nada — só faz as
    duas pontas concordarem por construção.
    """
    hoje = datetime.now(_SP).date()
    return datetime.combine(hoje, time(7, 5), tzinfo=_SP).astimezone(UTC)


@pytest.fixture()
def tenant_id(client: TestClient) -> str:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return client.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).json()["user"][
        "tenant_id"
    ]


@pytest.fixture()
def tenant_meta(db: Session, tenant_id: str) -> TenantProfile:
    """Tenant na Cloud API da Meta, com o template do aviso já aprovado e vinculado."""
    tpl = WhatsappTemplate(
        tenant_id=tenant_id, name="vima_briefing_aviso", language="pt_BR",
        category_requested="UTILITY", status=STATUS_APPROVED,
        body_text="Bom dia, {{1}}. Seu resumo de hoje está pronto.", variable_count=1,
        variable_examples=["Flávio"],
    )
    db.add(tpl)
    db.flush()
    perfil = TenantProfile(
        tenant_id=tenant_id, display_name="Vima ME", timezone="America/Sao_Paulo",
        whatsapp_provider="meta",
        # Credenciais da Cloud API preenchidas: sem elas o tenant não está "esperando a Meta
        # aprovar o template", está esperando CONECTAR — e a entrega recusa antes, com outra
        # frase (ver `vima/delivery.SEM_WHATSAPP`).
        whatsapp_token="tok-de-teste", whatsapp_phone_id="phone-id-de-teste",
        whatsapp_template_bindings={PURPOSE_VIMA_BRIEFING: tpl.id},
    )
    db.add(perfil)
    db.commit()
    return perfil


@pytest.fixture()
def usuario_com_optin(db: Session, tenant_id: str) -> User:
    user = db.query(User).filter(User.tenant_id == tenant_id).one()
    user.phone = TELEFONE
    user.briefing_hour = "07:00"
    user.briefing_whatsapp_enabled = True
    db.commit()
    return user


@pytest.fixture()
def aconteceu_algo(db: Session, tenant_id: str) -> Charge:
    cobranca = Charge(
        tenant_id=tenant_id, description="Consultoria", kind=KIND_SERVICE,
        method=METHOD_PIX, amount_cents=320_000, due_date=date(2026, 8, 3),
        status=STATUS_PAID, paid_at=datetime(2026, 8, 6, 12, 0, tzinfo=UTC),
    )
    db.add(cobranca)
    db.flush()
    facts.record(
        db, tenant_id=tenant_id, module="financeiro", kind=FIN_PAGAMENTO_RECEBIDO,
        title="Pagamento de João recebido", actor="system",
        subject_type="charge", subject_id=cobranca.id,
    )
    db.commit()
    return cobranca


def _toque_no_botao(de: str = TELEFONE, payload: str = PAYLOAD_BOTAO_BRIEFING) -> dict:
    """Payload REAL da Meta para o toque num botão de resposta rápida de template."""
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "contacts": [{"profile": {"name": "Flávio Kato"}, "wa_id": de}],
                            "messages": [
                                {
                                    "from": de,
                                    "id": f"wamid.BTN-{payload}-{de}",
                                    "timestamp": "1754470000",
                                    "type": "button",
                                    "button": {"payload": payload, "text": "Ver meu resumo"},
                                }
                            ],
                        }
                    }
                ]
            }
        ]
    }


# ── O parser ────────────────────────────────────────────────────────────────────────────


def test_parse_inbound_le_o_botao_do_template() -> None:
    (msg,) = meta_provider.parse_inbound(_toque_no_botao())
    assert msg.button_payload == PAYLOAD_BOTAO_BRIEFING
    # O rótulo do botão é o corpo da mensagem: é o que o dono vê no fio da conversa.
    assert msg.text_body == "Ver meu resumo"
    assert msg.kind == "text"


def test_parse_inbound_le_o_botao_interativo() -> None:
    """A outra forma que a Meta usa (`interactive.button_reply`), aceita pelo mesmo caminho."""
    payload = {
        "entry": [{"changes": [{"value": {
            "contacts": [{"profile": {"name": "Flávio"}, "wa_id": TELEFONE}],
            "messages": [{
                "from": TELEFONE, "id": "wamid.INT1", "type": "interactive",
                "interactive": {
                    "type": "button_reply",
                    "button_reply": {"id": PAYLOAD_BOTAO_BRIEFING, "title": "Ver meu resumo"},
                },
            }],
        }}]}]
    }
    (msg,) = meta_provider.parse_inbound(payload)
    assert msg.button_payload == PAYLOAD_BOTAO_BRIEFING


def test_mensagem_de_texto_comum_nao_tem_payload_de_botao() -> None:
    payload = {
        "entry": [{"changes": [{"value": {
            "contacts": [{"profile": {"name": "João"}, "wa_id": "5511999998888"}],
            "messages": [{
                "from": "5511999998888", "id": "wamid.T1", "type": "text",
                "text": {"body": "bom dia"},
            }],
        }}]}]
    }
    (msg,) = meta_provider.parse_inbound(payload)
    assert msg.button_payload is None


# ── Primeiro passo: o aviso ─────────────────────────────────────────────────────────────


def test_primeiro_passo_e_o_template_curto(
    db: Session, tenant_id, tenant_meta, usuario_com_optin, aconteceu_algo
):
    tick(db, tenant_id=tenant_id, agora=_sete_e_cinco_de_hoje())

    n = db.query(Notification).one()
    assert n.purpose == PURPOSE_VIMA_BRIEFING
    assert n.whatsapp_template_name == "vima_briefing_aviso"
    # É o aviso, não o briefing: uma linha, sem quebra — parâmetro de template não aceita `\n`.
    assert "\n" not in n.message
    assert len(n.message) < 200
    assert n.whatsapp_template_variables == ["Flávio"]


def test_o_botao_sai_com_payload_NOSSO_nao_com_o_rotulo_do_tenant(monkeypatch) -> None:
    """A Meta devolve, no toque, o `payload` do componente de botão — e quando não mandamos
    componente nenhum ela devolve o RÓTULO que o tenant escreveu no console dela. Como o rótulo
    é livre ("Ver resumo", "Bora", "Sim"), casar por constante só funciona se formos NÓS a
    definir o payload no envio."""
    capturado: dict = {}

    def _fake_post(url, **kwargs):
        capturado.update(kwargs.get("json") or {})

        class _R:
            def raise_for_status(self) -> None:
                return None

        return _R()

    monkeypatch.setattr(meta_provider.httpx, "post", _fake_post)
    meta_provider.send_template(
        to=TELEFONE, token="tok", phone_id="pid", template_name="vima_briefing_aviso",
        language="pt_BR", variables=["Flávio"], quick_reply_payload=PAYLOAD_BOTAO_BRIEFING,
    )

    componentes = capturado["template"]["components"]
    botao = next(c for c in componentes if c["type"] == "button")
    assert botao["sub_type"] == "quick_reply"
    assert botao["index"] == "0"
    assert botao["parameters"] == [{"type": "payload", "payload": PAYLOAD_BOTAO_BRIEFING}]


def test_sem_payload_o_template_sai_como_sempre(monkeypatch) -> None:
    """Os outros 5 propósitos não têm botão — o componente não pode aparecer para eles."""
    capturado: dict = {}

    def _fake_post(url, **kwargs):
        capturado.update(kwargs.get("json") or {})

        class _R:
            def raise_for_status(self) -> None:
                return None

        return _R()

    monkeypatch.setattr(meta_provider.httpx, "post", _fake_post)
    meta_provider.send_template(
        to=TELEFONE, token="tok", phone_id="pid", template_name="cobranca",
        language="pt_BR", variables=["João"],
    )

    tipos = {c["type"] for c in capturado["template"]["components"]}
    assert tipos == {"body"}


# ── Segundo passo: o toque ──────────────────────────────────────────────────────────────


def test_toque_no_botao_libera_o_briefing_inteiro(
    db: Session, tenant_id, tenant_meta, usuario_com_optin, aconteceu_algo
):
    tick(db, tenant_id=tenant_id, agora=_sete_e_cinco_de_hoje())
    ingest_webhook_payload(
        db, tenant_id=tenant_id, messages=meta_provider.parse_inbound(_toque_no_botao())
    )

    completos = (
        db.query(Notification)
        .filter(Notification.purpose == PURPOSE_VIMA_BRIEFING_TEXTO)
        .all()
    )
    assert len(completos) == 1
    assert len(completos[0].message) > 40
    # Texto LIVRE: a janela de 24h acabou de abrir, então não precisa (nem pode) ser template.
    assert completos[0].whatsapp_template_name is None


def test_o_toque_nao_cria_contato_no_crm(
    db: Session, tenant_id, tenant_meta, usuario_com_optin, aconteceu_algo
):
    """A guarda `_e_telefone_da_equipe` vale aqui: a resposta vem do telefone do PRÓPRIO dono.

    Sem ela o dono viraria lead do próprio funil todo dia — um card novo a cada toque no botão."""
    antes = db.query(Client).count()
    tick(db, tenant_id=tenant_id, agora=_sete_e_cinco_de_hoje())
    ingest_webhook_payload(
        db, tenant_id=tenant_id, messages=meta_provider.parse_inbound(_toque_no_botao())
    )
    assert db.query(Client).count() == antes


def test_tocar_duas_vezes_nao_manda_o_briefing_duas_vezes(
    db: Session, tenant_id, tenant_meta, usuario_com_optin, aconteceu_algo
):
    """Dedo escorregando no celular não pode custar duas mensagens iguais."""
    tick(db, tenant_id=tenant_id, agora=_sete_e_cinco_de_hoje())
    for i in range(2):
        (msg,) = meta_provider.parse_inbound(_toque_no_botao())
        # `wa_message_id` distinto: dois toques DE VERDADE, não a reentrega do mesmo evento (que
        # o ingest já descarta por idempotência — não seria este o comportamento sob teste).
        ingest_webhook_payload(
            db, tenant_id=tenant_id,
            messages=[dataclasses.replace(msg, wa_message_id=f"wamid.BTN-{i}")],
        )

    assert (
        db.query(Notification).filter(Notification.purpose == PURPOSE_VIMA_BRIEFING_TEXTO).count()
        == 1
    )


def test_toque_de_um_estranho_nao_libera_briefing_nenhum(
    db: Session, tenant_id, tenant_meta, usuario_com_optin, aconteceu_algo
):
    """O payload do botão é conhecido e um cliente qualquer poderia repeti-lo. Sem o vínculo com
    um usuário DO TENANT, o briefing do dono sairia para quem escrevesse a string certa."""
    tick(db, tenant_id=tenant_id, agora=_sete_e_cinco_de_hoje())
    ingest_webhook_payload(
        db,
        tenant_id=tenant_id,
        messages=meta_provider.parse_inbound(_toque_no_botao(de="5511977776666")),
    )

    assert (
        db.query(Notification).filter(Notification.purpose == PURPOSE_VIMA_BRIEFING_TEXTO).count()
        == 0
    )


def test_toque_sem_briefing_do_dia_nao_quebra(
    db: Session, tenant_id, tenant_meta, usuario_com_optin
):
    """Toque atrasado (ontem à noite, respondido hoje de manhã) não pode derrubar o webhook."""
    ingest_webhook_payload(
        db, tenant_id=tenant_id, messages=meta_provider.parse_inbound(_toque_no_botao())
    )
    assert db.query(Notification).count() == 0
