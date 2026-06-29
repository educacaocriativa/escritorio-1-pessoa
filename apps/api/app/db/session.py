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
    """Abre uma sessão com o tenant fixado para a RLS. Use em TODO acesso a dados de negócio.

    Valida o tenant_id antes de setar a GUC: um tenant vazio/None faria a policy RLS casar
    com `tenant_id = ''`/NULL (fail-open). Aqui é fail-closed explícito.

    O GUC é setado em escopo de SESSÃO (is_local=false), não de transação. Motivo: queries
    que rodam APÓS o commit (ex.: db.refresh() para popular created_at) iniciam uma nova
    transação — com is_local=true o tenant já teria sumido e a RLS esconderia a própria linha.
    Em escopo de sessão ele sobrevive ao commit; resetamos no finally para não vazar o tenant
    para a próxima requisição que reaproveitar a conexão do pool.
    """
    if not tenant_id or not isinstance(tenant_id, str) or len(tenant_id) < 8:
        raise ValueError("tenant_id inválido para abrir sessão de tenant")
    db = SessionLocal()
    try:
        db.execute(
            text("SELECT set_config('app.current_tenant_id', :tid, false)"),
            {"tid": tenant_id},
        )
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        # Reseta o tenant na conexão antes de devolvê-la ao pool (fail-closed entre requests).
        try:
            db.execute(text("SELECT set_config('app.current_tenant_id', '', false)"))
            db.commit()
        except Exception:
            db.rollback()
        db.close()


def get_db() -> Iterator[Session]:
    """Sessão SEM tenant (apenas para tabelas globais: plataforma, tenants, auth de login)."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
