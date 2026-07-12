"""Testes do seed do Super Admin (Master). Story 1.4.

Cobre:
- o admin semeado nasce com `must_reset_password=True` (força troca no 1º login);
- o seed é idempotente (rodar 2x não duplica o admin nem sobe erro).

O seed usa seu próprio `SessionLocal` (Postgres em produção); aqui apontamos esse
`SessionLocal` para um SQLite em memória (StaticPool, compartilhado entre sessões).
"""
import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.seed as seed_module
from app.config import Settings, settings
from app.db.registry import Base
from app.modules.auth.models import User


@pytest.fixture()
def seed_session(monkeypatch):
    """SQLite em memória com as tabelas criadas, plugado no SessionLocal do seed."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(seed_module, "SessionLocal", TestSession)
    try:
        yield TestSession
    finally:
        Base.metadata.drop_all(engine)


def _admin(session_factory) -> User | None:
    with session_factory() as db:
        return db.scalar(select(User).where(User.is_platform_admin.is_(True)))


def test_seed_creates_admin_with_must_reset_password(seed_session):
    seed_module.seed_super_admin()

    admin = _admin(seed_session)
    assert admin is not None
    assert admin.is_platform_admin is True
    assert admin.email == settings.super_admin_email.lower()
    # AC1: a conta de maior privilégio nasce obrigada a trocar a senha no 1º acesso.
    assert admin.must_reset_password is True


def test_seed_is_idempotent(seed_session):
    seed_module.seed_super_admin()
    seed_module.seed_super_admin()  # segunda passada não pode duplicar nem falhar

    with seed_session() as db:
        admins = db.scalars(select(User).where(User.is_platform_admin.is_(True))).all()
    assert len(admins) == 1
    assert admins[0].must_reset_password is True


def test_seed_never_runs_with_invalid_production_config():
    """Caminho infeliz do seed: config inválida em produção (env obrigatória faltando).

    `app/seed.py::seed_super_admin()` consome `settings.super_admin_password` (e email/name)
    DIRETAMENTE, sem validação própria — ele confia que o objeto `settings` global já é válido.
    Essa validação é fail-fast e vive em `app/config.py::Settings._guard_production_secrets`
    (`@model_validator(mode="after")`), executada na CONSTRUÇÃO de `Settings()` (linha de módulo).
    Logo, em produção com config inválida, `import app.config`/`Settings()` já falha ANTES de
    `seed_super_admin()` rodar — o "caminho infeliz do seed" É esse guard.

    Aqui provamos o cenário mais diretamente ligado ao seed: a senha default do admin
    (`"trocar-no-primeiro-acesso"`, único dos 4 campos do guard que o seed.py de fato lê).
    Cross-ref: mesma asserção que `test_config.py::test_production_rejects_default_admin_password`,
    mas rastreável a partir do contexto/motivação do seed — não é duplicação cega (AC1).
    """
    with pytest.raises(ValidationError):
        # jwt_secret forte + anthropic_api_key presente => o ÚNICO campo inválido é
        # super_admin_password, que fica no default -> guard de produção rejeita.
        Settings(
            environment="production",
            jwt_secret="x" * 40,
            anthropic_api_key="sk-ant-x",
        )
