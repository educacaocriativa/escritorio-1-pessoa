"""Sanity check dos modelos novos do inbox — colunas esperadas presentes."""
from sqlalchemy import text
from sqlalchemy.orm import Session

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


def test_public_whatsapp_account_app_secret_encrypted_at_rest(db: Session):
    """Achado da revisão final de branch: `public_whatsapp_accounts.app_secret` guardava o
    segredo do App da Meta em texto plano — um dump/backup vazado expunha o segredo, permitindo
    forjar a assinatura do webhook. Agora usa `EncryptedToken` (mesmo padrão de
    `TenantProfile.whatsapp_app_secret`); este teste bypassa o TypeDecorator (SQL cru) para
    provar que o valor REALMENTE gravado no banco não é o texto plano."""
    plaintext = "shh-meta-app-secret-nao-deveria-vazar"
    db.add(
        PublicWhatsappAccount(
            phone_number_id="phone-enc-test",
            tenant_id="t-enc-test",
            app_secret=plaintext,
            verify_token="verify-enc-test",
        )
    )
    db.commit()

    # Via ORM, o TypeDecorator decifra transparentemente — round-trip correto.
    reloaded = db.get(PublicWhatsappAccount, "phone-enc-test")
    assert reloaded is not None
    assert reloaded.app_secret == plaintext

    # Via SQL cru, bypassa o TypeDecorator — prova que o banco NÃO guarda o texto plano.
    stored_raw = db.execute(
        text(
            "SELECT app_secret FROM public_whatsapp_accounts WHERE phone_number_id = "
            "'phone-enc-test'"
        )
    ).scalar()
    assert stored_raw != plaintext
    assert stored_raw.startswith("enc:v1:")
