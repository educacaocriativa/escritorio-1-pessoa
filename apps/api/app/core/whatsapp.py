"""Envio de WhatsApp via WhatsApp Cloud API (Meta).

Sem credenciais configuradas (caso atual), NÃO falha: apenas registra o envio como "logged"
para que o fluxo do produto funcione. Quando `whatsapp_token` + `whatsapp_phone_id` existirem,
entrega de verdade pela Graph API.
"""
from __future__ import annotations

import logging

import httpx

from app.config import settings

logger = logging.getLogger("e1p.whatsapp")


def send_text(*, to: str, text: str) -> str:
    """Retorna o status: 'sent' | 'logged' | 'failed'."""
    if not settings.whatsapp_token or not settings.whatsapp_phone_id:
        logger.info("[whatsapp:logged] para=%s msg=%s", to, text)
        return "logged"
    try:
        resp = httpx.post(
            f"https://graph.facebook.com/v21.0/{settings.whatsapp_phone_id}/messages",
            headers={"Authorization": f"Bearer {settings.whatsapp_token}"},
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
