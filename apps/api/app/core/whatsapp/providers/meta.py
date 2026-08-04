"""Envio de WhatsApp via WhatsApp Cloud API (Meta).

Provider oficial. Movido para cá na Onda 0 (costura do despachante) sem qualquer mudança de
comportamento — ver docs/superpowers/specs/2026-07-30-whatsapp-evolution-multi-tenant-design.md.

Sem credenciais configuradas (caso atual), NÃO falha: apenas registra o envio como "logged"
para que o fluxo do produto funcione. Quando `whatsapp_token` + `whatsapp_phone_id` existirem,
entrega de verdade pela Graph API.
"""
from __future__ import annotations

import hashlib
import hmac
import logging

import httpx

from app.config import settings
from app.core.whatsapp.inbound import InboundMessage

logger = logging.getLogger("e1p.whatsapp")


def send_text(
    *, to: str, text: str, token: str | None = None, phone_id: str | None = None
) -> str:
    """Retorna o status: 'sent' | 'logged' | 'failed'.

    `token`/`phone_id` são as credenciais do TENANT (ver `TenantProfile`) — passe-as sempre que
    o chamador já tiver o perfil do tenant em mãos. Quando omitidos (None, o default), cai na
    env global `settings.whatsapp_token`/`whatsapp_phone_id` — mantido só por retrocompatibilidade
    com testes/chamadas antigas; em produção essa env NUNCA está configurada (a integração é
    100% por tenant), então omitir os parâmetros equivale, na prática, a 'logged' sempre.
    """
    tok = token if token is not None else settings.whatsapp_token
    pid = phone_id if phone_id is not None else settings.whatsapp_phone_id
    if not tok or not pid:
        logger.info("[whatsapp:logged] para=%s msg=%s", to, text)
        return "logged"
    try:
        resp = httpx.post(
            f"https://graph.facebook.com/v21.0/{pid}/messages",
            headers={"Authorization": f"Bearer {tok}"},
            json={
                "messaging_product": "whatsapp",
                "to": to,
                "type": "text",
                "text": {"body": text},
            },
            timeout=10,
        )
        resp.raise_for_status()
        return "sent"
    except Exception:
        logger.exception("[whatsapp:failed] para=%s", to)
        return "failed"


class WhatsappApiError(Exception):
    """Erro ao chamar a Graph API para gerenciamento de templates (create/sync/delete).

    Diferente de send_text/send_template (fire-and-forget, nunca propagam exceção), estas são
    ações administrativas explícitas e DEVEM propagar erro pro service tratar.
    """


def _raise_for_error(resp: httpx.Response) -> None:
    if resp.status_code >= 400:
        try:
            detail = resp.json()
        except Exception:
            detail = resp.text
        raise WhatsappApiError(f"Graph API retornou erro {resp.status_code}: {detail}")


def create_template(
    *,
    waba_id: str,
    token: str,
    name: str,
    language: str,
    category: str,
    body_text: str,
    variable_examples: list[str],
) -> dict:
    """POST /{waba_id}/message_templates. Envia o template pra aprovação da Meta.

    Retorna o JSON de resposta (contém pelo menos 'id' e 'status'; a Meta às vezes já devolve
    'category' também). Levanta WhatsappApiError em qualquer falha (rede ou status >=400).
    """
    body_component: dict = {"type": "BODY", "text": body_text}
    if variable_examples:
        body_component["example"] = {"body_text": [variable_examples]}
    try:
        resp = httpx.post(
            f"https://graph.facebook.com/v21.0/{waba_id}/message_templates",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "name": name,
                "language": language,
                "category": category,
                "components": [body_component],
            },
            timeout=10,
        )
    except Exception as exc:
        raise WhatsappApiError(f"Falha de rede ao criar template: {exc}") from exc
    _raise_for_error(resp)
    return resp.json()


def fetch_template_status(*, token: str, meta_template_id: str) -> dict:
    """GET /{meta_template_id}?fields=status,category,rejected_reason.

    Retorna {"status": ..., "category": ..., "rejected_reason": ...|None}.
    Levanta WhatsappApiError em qualquer falha.
    """
    try:
        resp = httpx.get(
            f"https://graph.facebook.com/v21.0/{meta_template_id}",
            headers={"Authorization": f"Bearer {token}"},
            params={"fields": "status,category,rejected_reason"},
            timeout=10,
        )
    except Exception as exc:
        raise WhatsappApiError(f"Falha de rede ao consultar template: {exc}") from exc
    _raise_for_error(resp)
    data = resp.json()
    return {
        "status": data.get("status"),
        "category": data.get("category"),
        "rejected_reason": data.get("rejected_reason"),
    }


def delete_template(*, waba_id: str, token: str, name: str) -> None:
    """DELETE /{waba_id}/message_templates?name={name}.

    Levanta WhatsappApiError em qualquer falha.
    """
    try:
        resp = httpx.delete(
            f"https://graph.facebook.com/v21.0/{waba_id}/message_templates",
            headers={"Authorization": f"Bearer {token}"},
            params={"name": name},
            timeout=10,
        )
    except Exception as exc:
        raise WhatsappApiError(f"Falha de rede ao excluir template: {exc}") from exc
    _raise_for_error(resp)


def send_template(
    *, to: str, token: str, phone_id: str, template_name: str, language: str, variables: list[str]
) -> str:
    """Retorna 'sent' | 'logged' | 'failed'.

    MESMO contrato/invariante de send_text: NUNCA propaga exceção (fire-and-forget, graceful
    degradation) — 'logged' quando token ou phone_id vier vazio; 'failed' se a chamada falhar;
    'sent' em 200 OK.
    """
    if not token or not phone_id:
        logger.info("[whatsapp:logged] template para=%s nome=%s", to, template_name)
        return "logged"
    components = (
        [{"type": "body", "parameters": [{"type": "text", "text": v} for v in variables]}]
        if variables
        else []
    )
    try:
        resp = httpx.post(
            f"https://graph.facebook.com/v21.0/{phone_id}/messages",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "messaging_product": "whatsapp",
                "to": to,
                "type": "template",
                "template": {
                    "name": template_name,
                    "language": {"code": language},
                    "components": components,
                },
            },
            timeout=10,
        )
        resp.raise_for_status()
        return "sent"
    except Exception:
        logger.exception("[whatsapp:failed] template para=%s nome=%s", to, template_name)
        return "failed"


def verify_webhook_signature(
    *, app_secret: str, body: bytes, signature_header: str | None
) -> bool:
    """Valida `X-Hub-Signature-256` (HMAC-SHA256 do corpo CRU do webhook). Comparação de tempo
    constante — nunca comparar segredos com `==`."""
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    provided = signature_header.removeprefix("sha256=")
    return hmac.compare_digest(expected, provided)


def upload_media(
    *, phone_id: str, token: str, file_bytes: bytes, filename: str, mime_type: str
) -> str:
    """POST /{phone_id}/media (multipart). Retorna o `media_id` temporário da Meta.
    Levanta WhatsappApiError em qualquer falha."""
    try:
        resp = httpx.post(
            f"https://graph.facebook.com/v21.0/{phone_id}/media",
            headers={"Authorization": f"Bearer {token}"},
            data={"messaging_product": "whatsapp"},
            files={"file": (filename, file_bytes, mime_type)},
            timeout=30,
        )
    except Exception as exc:
        raise WhatsappApiError(f"Falha de rede ao subir mídia: {exc}") from exc
    _raise_for_error(resp)
    return resp.json()["id"]


def fetch_media_url(*, token: str, media_id: str) -> str:
    """GET /{media_id}. Retorna a URL temporária de download. Levanta WhatsappApiError."""
    try:
        resp = httpx.get(
            f"https://graph.facebook.com/v21.0/{media_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
    except Exception as exc:
        raise WhatsappApiError(f"Falha de rede ao resolver mídia: {exc}") from exc
    _raise_for_error(resp)
    return resp.json()["url"]


def download_media(*, token: str, url: str) -> bytes:
    """Baixa os bytes da URL temporária (a Meta exige o Bearer token também neste GET).
    Levanta WhatsappApiError."""
    try:
        resp = httpx.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=30)
    except Exception as exc:
        raise WhatsappApiError(f"Falha de rede ao baixar mídia: {exc}") from exc
    _raise_for_error(resp)
    return resp.content


def send_media(
    *, to: str, token: str, phone_id: str, kind: str, media_id: str, caption: str = ""
) -> str:
    """Retorna 'sent' | 'logged' | 'failed'. Mesmo contrato de send_text/send_template: NUNCA
    propaga exceção."""
    if not token or not phone_id:
        logger.info("[whatsapp:logged] mídia para=%s kind=%s", to, kind)
        return "logged"
    media_obj: dict[str, str] = {"id": media_id}
    if caption:
        media_obj["caption"] = caption
    try:
        resp = httpx.post(
            f"https://graph.facebook.com/v21.0/{phone_id}/messages",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "messaging_product": "whatsapp", "to": to, "type": kind, kind: media_obj,
            },
            timeout=10,
        )
        resp.raise_for_status()
        return "sent"
    except Exception:
        logger.exception("[whatsapp:failed] mídia para=%s kind=%s", to, kind)
        return "failed"


def parse_inbound(payload: dict) -> list[InboundMessage]:
    """Extrai as mensagens do formato aninhado do payload da Meta. Payload não confiável (a
    Meta não garante o shape interno) — dois níveis de tolerância, preservados do antigo
    `whatsapp_inbox.service._extract_messages`:

    - Shape do LOTE quebrado (`value` não é dict, `messages` não é uma lista de dicts) — a
      Meta não conseguiu nem descrever o que mandou; levanta `ValueError` pro chamador decidir
      (o router converte em 400 — o remetente está errado, não uma mensagem específica).
    - Campo de UMA mensagem malformado (`text`/mídia não é dict) — isola só aquela mensagem
      (não entra na lista), sem afetar as demais do mesmo lote nem levantar erro.
    """
    out: list[InboundMessage] = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            if not isinstance(value, dict):
                raise ValueError("Payload inválido: 'value' malformado")
            contacts = value.get("contacts", [])
            try:
                push_name = contacts[0]["profile"]["name"] if contacts else ""
            except (AttributeError, TypeError, KeyError) as exc:
                raise ValueError("Payload inválido: 'contacts' malformado") from exc
            messages = value.get("messages", [])
            if not isinstance(messages, list) or any(
                not isinstance(msg, dict) for msg in messages
            ):
                raise ValueError("Payload inválido: 'messages' malformado")
            for msg in messages:
                try:
                    wa_message_id = msg.get("id", "")
                    from_phone = msg.get("from") or None
                    kind = msg.get("type", "text")
                    text_body = ""
                    media_ref = None
                    if kind == "text":
                        text_field = msg.get("text", {})
                        if not isinstance(text_field, dict):
                            continue  # isola só esta mensagem — ver docstring
                        text_body = text_field.get("body", "")
                    elif kind in ("image", "audio", "document", "video"):
                        media_obj = msg.get(kind, {})
                        if not isinstance(media_obj, dict):
                            continue  # isola só esta mensagem — ver docstring
                        text_body = media_obj.get("caption", "")
                        media_ref = media_obj.get("id")
                    else:
                        kind = "text"
                        text_body = "[tipo de mensagem não suportado]"
                    out.append(InboundMessage(
                        wa_message_id=wa_message_id, from_phone=from_phone, kind=kind,
                        text_body=text_body, media_ref=media_ref, push_name=push_name,
                        # A Meta não expõe JID: o webhook dela entrega só o telefone (`from`), e
                        # a Cloud API não entrega grupo de jeito nenhum (a API oficial não tem
                        # grupos). Derivamos o JID canônico do telefone para que a conversa caia
                        # no MESMO chat que uma mensagem equivalente da Evolution — o que
                        # importa num tenant que troque de transporte.
                        chat_jid=f"{from_phone}@s.whatsapp.net" if from_phone else None,
                        sender_phone=from_phone, sender_name=push_name or None,
                    ))
                except (AttributeError, TypeError, KeyError):
                    continue  # isola só esta mensagem — ver docstring
    return out
