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

    CRÍTICO — conexão DEDICADA: a Session é presa a UMA conexão física (`engine.connect()`),
    não ao pool da Engine. Motivo: ao commitar, uma Session ligada à Engine devolve a conexão
    ao pool, e o `db.refresh()` seguinte pega OUTRA conexão — sem a GUC `app.current_tenant_id`
    setada — e a RLS esconde a própria linha ("Could not refresh instance"). Presa a uma
    conexão única, todas as queries (inclusive o refresh pós-commit) usam a MESMA conexão, onde
    a GUC (escopo de sessão, is_local=false) permanece setada. No fim, reseta a GUC e devolve a
    conexão limpa ao pool.
    """
    if not tenant_id or not isinstance(tenant_id, str) or len(tenant_id) < 8:
        raise ValueError("tenant_id inválido para abrir sessão de tenant")
    conn = engine.connect()
    try:
        conn.execute(
            text("SELECT set_config('app.current_tenant_id', :tid, false)"),
            {"tid": tenant_id},
        )
        conn.commit()  # fixa a GUC na conexão (escopo de sessão, sobrevive aos próximos commits)
        db = Session(bind=conn, autoflush=False, expire_on_commit=False)
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
    finally:
        # Reseta o tenant na conexão antes de devolvê-la ao pool (fail-closed entre requests).
        try:
            conn.execute(text("SELECT set_config('app.current_tenant_id', '', false)"))
            conn.commit()
        except Exception:
            conn.rollback()
        conn.close()


def get_db() -> Iterator[Session]:
    """Sessão SEM tenant (apenas para tabelas globais: plataforma, tenants, auth de login)."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_tenant_session_factory():
    """Dependência: devolve o factory `tenant_session`.

    Existe para que rotas PÚBLICAS (sem auth) consigam abrir uma sessão de tenant a partir de
    um identificador que NÃO vem do token (ex.: o tenant do snapshot da proposta). Como é uma
    dependência, os testes a sobrescrevem para apontar à sessão de teste (SQLite).
    """
    return tenant_session
