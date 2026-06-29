"""Fixtures de teste. Usa SQLite em memória + override de get_db.

Nota: RLS é específica do Postgres e NÃO é exercida aqui — é validada em ambiente com Postgres
(ver docs/AWS-DEPLOYMENT.md). Estes testes cobrem a lógica de auth/serviço/rotas.
"""
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.tenancy import get_tenant_db
from app.db.registry import Base
from app.db.session import get_db
from app.main import app

engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture()
def db() -> Iterator[Session]:
    Base.metadata.create_all(engine)
    session = TestSession()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


@pytest.fixture()
def client(db: Session) -> Iterator[TestClient]:
    # Remove assinantes globais do barramento (ex.: WhatsApp on-move, que abriria uma
    # conexão Postgres real). Testes que precisam de assinante registram o seu próprio.
    from app.core import events

    events.clear()

    def _override_get_db() -> Iterator[Session]:
        yield db

    # get_tenant_db usa set_config (Postgres) — em SQLite trocamos pela sessão de teste.
    # (RLS não é exercida aqui; é validada em ambiente Postgres — ver docs/AWS-DEPLOYMENT.md.)
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
