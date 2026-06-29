"""Testes de notificação. A entrega real (subscriber + Postgres) é coberta no e2e Docker."""
from app.core import whatsapp


def test_whatsapp_logged_without_config():
    # sem WHATSAPP_TOKEN/PHONE_ID configurados, o envio não falha: retorna "logged".
    assert whatsapp.send_text(to="5511999999999", text="oi") == "logged"
