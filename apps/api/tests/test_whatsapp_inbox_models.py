"""Sanity check dos modelos novos do inbox — colunas esperadas presentes."""
from app.modules.settings.models import TenantProfile
from app.modules.whatsapp_inbox.models import (
    PublicWhatsappAccount,
    WhatsappConversationState,
    WhatsappMessage,
)


def test_whatsapp_message_columns():
    cols = {c.name for c in WhatsappMessage.__table__.columns}
    assert cols == {
        "id", "tenant_id", "client_id", "direction", "kind", "text_body",
        "media_attachment_id", "media_status", "wa_message_id", "meta_media_id", "status",
        "created_at", "updated_at",
    }


def test_whatsapp_conversation_state_columns():
    cols = {c.name for c in WhatsappConversationState.__table__.columns}
    assert cols == {"id", "tenant_id", "client_id", "last_read_at", "created_at", "updated_at"}


def test_public_whatsapp_account_columns():
    cols = {c.name for c in PublicWhatsappAccount.__table__.columns}
    assert cols == {
        "phone_number_id", "tenant_id", "app_secret", "verify_token",
        "created_at", "updated_at",
    }


def test_tenant_profile_has_new_whatsapp_fields():
    cols = {c.name for c in TenantProfile.__table__.columns}
    assert "whatsapp_app_secret" in cols
    assert "whatsapp_verify_token" in cols
