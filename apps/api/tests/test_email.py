"""Testes do provedor de e-mail transacional (core/email.send_email).

Cobre os 3 caminhos: sem SMTP configurado (graceful degradation), envio real (mockando smtplib)
e falha do provedor (não propaga exceção). Nunca depende de um servidor SMTP real.
"""
from unittest.mock import patch

from app.core import email


def test_send_email_logs_without_smtp_host(monkeypatch):
    # IV2: sem SMTP_HOST, retorna "logged" e NÃO levanta exceção (graceful degradation).
    monkeypatch.setattr(email.settings, "smtp_host", "", raising=False)
    with patch("app.core.email.smtplib.SMTP") as mock_smtp:
        status = email.send_email(to="alguem@example.com", subject="Oi", body="Corpo")
    assert status == "logged"
    mock_smtp.assert_not_called()  # não tenta conectar sem host


def test_send_email_sends_via_smtp(monkeypatch):
    # AC1: com SMTP_HOST configurado, entrega de verdade via smtplib e retorna "sent".
    monkeypatch.setattr(email.settings, "smtp_host", "smtp.example.com", raising=False)
    monkeypatch.setattr(email.settings, "smtp_port", 587, raising=False)
    monkeypatch.setattr(email.settings, "smtp_user", "user@example.com", raising=False)
    monkeypatch.setattr(email.settings, "smtp_password", "s3cr3t", raising=False)
    monkeypatch.setattr(email.settings, "smtp_from", "", raising=False)  # usa smtp_user
    monkeypatch.setattr(email.settings, "smtp_use_tls", True, raising=False)

    with patch("app.core.email.smtplib.SMTP") as mock_smtp:
        smtp_conn = mock_smtp.return_value.__enter__.return_value
        status = email.send_email(to="dest@example.com", subject="Assunto", body="Mensagem")

    assert status == "sent"
    # conectou no host/porta com timeout explícito (IV3: não trava a request)
    mock_smtp.assert_called_once_with("smtp.example.com", 587, timeout=10)
    smtp_conn.starttls.assert_called_once()
    smtp_conn.login.assert_called_once_with("user@example.com", "s3cr3t")
    smtp_conn.send_message.assert_called_once()
    # mensagem montada com remetente (fallback smtp_user), destinatário e assunto corretos
    sent_msg = smtp_conn.send_message.call_args.args[0]
    assert sent_msg["From"] == "user@example.com"
    assert sent_msg["To"] == "dest@example.com"
    assert sent_msg["Subject"] == "Assunto"
    assert sent_msg.get_content().strip() == "Mensagem"


def test_send_email_uses_smtp_from_when_set(monkeypatch):
    monkeypatch.setattr(email.settings, "smtp_host", "smtp.example.com", raising=False)
    monkeypatch.setattr(email.settings, "smtp_user", "user@example.com", raising=False)
    monkeypatch.setattr(email.settings, "smtp_from", "nao-responder@e1p.com", raising=False)
    monkeypatch.setattr(email.settings, "smtp_use_tls", False, raising=False)

    with patch("app.core.email.smtplib.SMTP") as mock_smtp:
        smtp_conn = mock_smtp.return_value.__enter__.return_value
        status = email.send_email(to="d@example.com", subject="S", body="B")

    assert status == "sent"
    smtp_conn.starttls.assert_not_called()  # TLS desligado
    sent_msg = smtp_conn.send_message.call_args.args[0]
    assert sent_msg["From"] == "nao-responder@e1p.com"


def test_send_email_returns_failed_on_provider_error(monkeypatch):
    # IV3: falha do provedor NÃO propaga exceção — retorna "failed".
    monkeypatch.setattr(email.settings, "smtp_host", "smtp.example.com", raising=False)
    with patch("app.core.email.smtplib.SMTP", side_effect=OSError("connrefused")):
        status = email.send_email(to="d@example.com", subject="S", body="B")
    assert status == "failed"
