"""Engine e sessão do SQLAlchemy + helper de tenancy via RLS.

A regra de ouro do e1p (isolamento de tenant) é garantida no banco: cada conexão de request
define `app.current_tenant_id`, e as políticas RLS do Postgres filtram automaticamente.
Nenhuma query de aplicação deve filtrar tenant manualmente.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@contextmanager
def tenant_session(tenant_id: str) -> Iterator[Session]:
    """Abre uma sessão com o tenant fixado para a RLS. Use em TODO acesso a dados de negócio."""
    db = SessionLocal()
    try:
        # set_config local: válido só nesta transação/conexão.
        db.execute(
            text("SELECT set_config('app.current_tenant_id', :tid, true)"),
            {"tid": tenant_id},
        )
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_db() -> Iterator[Session]:
    """Sessão SEM tenant (apenas para tabelas globais: plataforma, tenants, auth de login)."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
