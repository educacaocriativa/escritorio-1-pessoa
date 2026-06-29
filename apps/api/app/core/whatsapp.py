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
