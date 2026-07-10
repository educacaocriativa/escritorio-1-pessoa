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
