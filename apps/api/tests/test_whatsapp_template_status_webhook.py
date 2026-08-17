"""O MESMO endpoint público recebe mensagem e aprovação de template — e o segundo tipo chega
roteado por WABA, sem telefone nenhum. Ver issue #36 item 5.

Payload conferido contra o exemplo oficial da Meta (`message_template_status_update`).
"""
import hashlib
import hmac
import json

from sqlalchemy import select

from app.modules.whatsapp_inbox.models import PublicWhatsappAccount, WhatsappMessage
from app.modules.whatsapp_templates.models import WhatsappTemplate

TENANT_ID = "22222222-2222-2222-2222-222222222222"


def _seed(db, *, tenant_id=TENANT_ID, waba_id="waba-1", app_secret="segredo",
          meta_template_id="777"):
    db.add(PublicWhatsappAccount(
        phone_number_id="phone-1", tenant_id=tenant_id, app_secret=app_secret,
        verify_token="verify-1", waba_id=waba_id,
    ))
    db.add(WhatsappTemplate(
        tenant_id=tenant_id, name="lembrete", language="pt_BR", category_requested="UTILITY",
        body_text="Olá {{1}}", variable_count=1, variable_examples=["Maria"],
        status="PENDING", meta_template_id=meta_template_id,
    ))
    db.commit()


def _payload(*, waba_id="waba-1", event="APPROVED", template_id=777, reason="NONE"):
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": waba_id,
            "time": 1751247548,
            "changes": [{
                "field": "message_template_status_update",
                "value": {
                    "event": event, "message_template_id": template_id,
                    "message_template_name": "lembrete", "message_template_language": "pt_BR",
                    "reason": reason, "message_template_category": "UTILITY",
                },
            }],
        }],
    }


def _sign(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _post(client, payload, *, secret="segredo", signature=None):
    body = json.dumps(payload).encode()
    return client.post(
        "/public/whatsapp/webhook", content=body,
        headers={
            "content-type": "application/json",
            "x-hub-signature-256": signature or _sign(body, secret),
        },
    )


def _template(db):
    return db.scalar(select(WhatsappTemplate).where(WhatsappTemplate.meta_template_id == "777"))


def test_aprovacao_da_meta_atualiza_o_template_sem_ninguem_clicar(client, db):
    _seed(db)
    resp = _post(client, _payload())
    assert resp.status_code == 200
    assert _template(db).status == "APPROVED"


def test_rejeicao_traz_o_motivo(client, db):
    _seed(db)
    resp = _post(client, _payload(event="REJECTED", reason="INVALID_FORMAT"))
    assert resp.status_code == 200

    tpl = _template(db)
    assert tpl.status == "REJECTED"
    assert tpl.rejected_reason == "INVALID_FORMAT"


def test_assinatura_invalida_nao_muda_nada(client, db):
    """Sem esta checagem, qualquer um na internet aprovaria template alheio com um curl."""
    _seed(db)
    resp = _post(client, _payload(), signature="sha256=forjado")
    assert resp.status_code == 403
    assert _template(db).status == "PENDING"


def test_waba_desconhecida_da_404(client, db):
    _seed(db)
    resp = _post(client, _payload(waba_id="waba-de-outra-plataforma"))
    assert resp.status_code == 404


def test_evento_de_template_nao_exige_phone_number_id(client, db):
    """A regressão que este arquivo existe pra impedir: antes desta onda o payload de template
    morria em 404 'phone_number_id não encontrado' porque só havia um caminho de roteamento."""
    _seed(db)
    resp = _post(client, _payload())
    assert resp.status_code == 200
    assert "phone_number_id" not in resp.text


def test_mensagem_recebida_continua_funcionando(client, db):
    """O ramo novo roda ANTES do antigo em todo payload — o caminho de mensagem não pode ter
    mudado de comportamento."""
    _seed(db)
    payload = {
        "entry": [{
            "id": "waba-1",
            "changes": [{
                "field": "messages",
                "value": {
                    "metadata": {"phone_number_id": "phone-1"},
                    "contacts": [{"profile": {"name": "Cliente"}, "wa_id": "5511900000000"}],
                    "messages": [{"from": "5511900000000", "id": "wamid.novo", "type": "text",
                                  "text": {"body": "Olá!"}}],
                },
            }],
        }],
    }
    resp = _post(client, payload)
    assert resp.status_code == 200
    assert db.scalar(
        select(WhatsappMessage).where(WhatsappMessage.wa_message_id == "wamid.novo")
    ) is not None
