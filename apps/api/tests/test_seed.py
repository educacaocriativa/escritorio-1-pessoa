"""Testes do seed do Super Admin (Master). Story 1.4.

Cobre:
- o admin semeado nasce com `must_reset_password=True` (força troca no 1º login);
- o seed é idempotente (rodar 2x não duplica o admin nem sobe erro).

O seed usa seu próprio `SessionLocal` (Postgres em produção); aqui apontamos esse
`SessionLocal` para um SQLite em memória (StaticPool, compartilhado entre sessões).
"""
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.seed as seed_module
from app.config import settings
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
