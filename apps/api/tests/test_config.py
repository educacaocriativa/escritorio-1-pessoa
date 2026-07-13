"""Guarda de configuração: produção não pode subir com segredos fracos."""
import pytest
from pydantic import ValidationError

from app.config import Settings

STRONG = "x" * 40


def test_production_rejects_default_secret():
    with pytest.raises(ValidationError):
        Settings(environment="production", anthropic_api_key="sk-ant-x")


def test_production_rejects_short_secret():
    with pytest.raises(ValidationError):
        Settings(environment="production", jwt_secret="curto", anthropic_api_key="sk-ant-x")


def test_production_requires_anthropic_key():
    with pytest.raises(ValidationError):
        Settings(environment="production", jwt_secret=STRONG, anthropic_api_key="")


def test_production_rejects_default_admin_password():
    with pytest.raises(ValidationError):
        Settings(environment="production", jwt_secret=STRONG, anthropic_api_key="sk-ant-x")


def test_production_ok_with_strong_secret():
    s = Settings(
        environment="production",
        jwt_secret=STRONG,
        anthropic_api_key="sk-ant-x",
        super_admin_password="uma-senha-de-admin-forte",
    )
    assert s.is_production


_GOOGLE = {
    "google_client_id": "cid",
    "google_client_secret": "csec",
    "google_oauth_redirect_uri": "https://api.e1p.com/integrations/google/callback",
}


def test_production_requires_token_encryption_key_when_google_configured():
    # Google ativo em produção → tokens gravados no banco → chave dedicada obrigatória.
    with pytest.raises(ValidationError):
        Settings(
            environment="production",
            jwt_secret=STRONG,
            anthropic_api_key="sk-ant-x",
            super_admin_password="uma-senha-de-admin-forte",
            google_token_encryption_key="",
            **_GOOGLE,
        )


def test_production_rejects_weak_token_encryption_key():
    with pytest.raises(ValidationError):
        Settings(
            environment="production",
            jwt_secret=STRONG,
            anthropic_api_key="sk-ant-x",
            super_admin_password="uma-senha-de-admin-forte",
            google_token_encryption_key="curta",  # < 32 chars
            **_GOOGLE,
        )


def test_production_ok_with_google_and_strong_encryption_key():
    s = Settings(
        environment="production",
        jwt_secret=STRONG,
        anthropic_api_key="sk-ant-x",
        super_admin_password="uma-senha-de-admin-forte",
        google_token_encryption_key="k" * 44,
        **_GOOGLE,
    )
    assert s.is_production and s.google_oauth_configured


def test_production_without_google_does_not_require_encryption_key():
    # Google desligado → nenhum token gravado → a chave não é exigida (não bloqueia deploy).
    s = Settings(
        environment="production",
        jwt_secret=STRONG,
        anthropic_api_key="sk-ant-x",
        super_admin_password="uma-senha-de-admin-forte",
        google_token_encryption_key="",
    )
    assert s.is_production and not s.google_oauth_configured


def test_development_allows_defaults():
    s = Settings(environment="development")
    assert not s.is_production


def test_seed_synthetic_data_defaults_false():
    # Default seguro (Story 3.1): produção NUNCA semeia dados sintéticos a menos que
    # SEED_SYNTHETIC_DATA=true seja definido explicitamente (só no .env de staging).
    assert Settings(environment="development").seed_synthetic_data is False
    assert Settings(
        environment="production",
        jwt_secret=STRONG,
        anthropic_api_key="sk-ant-x",
        super_admin_password="uma-senha-de-admin-forte",
    ).seed_synthetic_data is False
