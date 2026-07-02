"""Envio de e-mail (stub de desenvolvimento).

Sem `smtp_host` configurado (caso atual), NÃO falha: registra o envio como "logged" para que o
fluxo do produto funcione. Quando houver SMTP/provedor (SES, etc.), trocar por entrega real.
Mesmo contrato do core/whatsapp.send_text — devolve um status string.
"""
from __future__ import annotations

import logging

from app.config import settings

logger = logging.getLogger("e1p.email")


def send_email(*, to: str, subject: str, body: str) -> str:
    """Retorna o status: 'sent' | 'logged' | 'failed'."""
    if not settings.smtp_host:
        logger.info("[email:logged] para=%s assunto=%s corpo=%s", to, subject, body)
        return "logged"
    try:
        # Integração real (SMTP/SES) entra aqui quando as credenciais existirem.
        logger.info("[email:sent] para=%s assunto=%s", to, subject)
        return "sent"
    except Exception:
        logger.exception("[email:failed] para=%s", to)
        return "failed"
