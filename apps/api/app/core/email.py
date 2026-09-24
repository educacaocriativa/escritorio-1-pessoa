"""Envio de e-mail transacional via SMTP genérico (cobre também o endpoint SMTP do Amazon SES).

Sem `smtp_host` configurado, NÃO falha: registra o envio como "logged" (graceful degradation)
para que o fluxo do produto funcione. Com `smtp_host` presente, entrega de verdade via `smtplib`
(stdlib — sem SDK/dependência nova). Falha do provedor não propaga exceção: devolve "failed".
Mesmo contrato do core/whatsapp.send_text — devolve um status string.
"""
from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage

from app.config import settings

logger = logging.getLogger("e1p.email")


def send_email(*, to: str, subject: str, body: str) -> str:
    """Retorna o status: 'sent' | 'logged' | 'failed'."""
    if not settings.smtp_host:
        logger.info("[email:logged] para=%s assunto=%s corpo=%s", to, subject, body)
        return "logged"
    if settings.smtp_user and not settings.smtp_use_tls:
        # Login sem TLS manda usuário e senha (no Resend, a API key) em texto puro pela rede.
        # Recusar é melhor que vazar: a config errada aparece no log, não num sniffer.
        logger.error("[email:failed] para=%s: SMTP_USER exige SMTP_USE_TLS=true", to)
        return "failed"
    try:
        msg = EmailMessage()
        msg["From"] = settings.smtp_from or settings.smtp_user
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
            if settings.smtp_use_tls:
                # Sem `context`, o smtplib usa um contexto que NÃO verifica o certificado nem
                # o hostname: um intermediário se passaria pelo provedor e levaria a senha.
                smtp.starttls(context=ssl.create_default_context())
            if settings.smtp_user:
                smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(msg)
        logger.info("[email:sent] para=%s assunto=%s", to, subject)
        return "sent"
    except Exception:
        logger.exception("[email:failed] para=%s", to)
        return "failed"
