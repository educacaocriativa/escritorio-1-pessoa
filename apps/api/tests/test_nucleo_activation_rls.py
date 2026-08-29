"""O rastro de ativação do núcleo (Vima V2), no Postgres REAL e sob RLS.

**Por que este teste existe, e por que não podia ser em SQLite.** `entradas_do_dna()` é a leitura
que `nucleo_activation.py` usa para reconstruir as passagens pelo núcleo — e, como `auditar()` em
`investment_audit.py`, ela lê uma tabela com `FORCE ROW LEVEL SECURITY` (`audit_entries`, via
`TenantMixin`). Uma consulta ali **sem** a GUC de tenant devolve **zero linhas, sem erro**: foi
assim que a sondagem de `phone_key` em produção quase virou um "está tudo limpo" falso, e a mesma
armadilha vale aqui — um relatório de ativação vazio por falta de sessão de tenant seria
indistinguível de "ninguém abriu o núcleo ainda".

Os testes SQLite de `derivar()`/`respostas_por_origem()` (em `test_nucleo_activation.py`) provam a
aritmética das passagens e nada mais — **RLS não é exercida lá** (ver `conftest.py`). O que se
prova aqui é a outra metade:

1. `entradas_do_dna()` dentro de `tenant_session` só vê a trilha **daquele** tenant;
2. e **não** vê a do vizinho (se visse, um dono veria as passagens de outro pelo núcleo — pior do
   que ficar calado);
3. sem GUC, a leitura é **fail-closed** — zero linhas, o mesmo resultado que o `main()` do script
   não pode confundir com "nenhum tenant varreu o núcleo ainda" (por isso ele imprime a contagem
   de tenants).

Módulo marcado `rls_e2e`: NÃO roda no `pytest -q` (suíte SQLite), só no job `cross-tenant-rls` do
CI ou manualmente com Docker (`pytest -m rls_e2e`).
"""
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

pytest.importorskip("testcontainers.postgres")

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402
from testcontainers.postgres import PostgresContainer  # noqa: E402

pytestmark = pytest.mark.rls_e2e

_ROOT_USER = "e1p_root"
_ROOT_PASS = "rootpass"  # noqa: S105 (senha efêmera do container de teste)
_APP_PASS = "e1ppass"  # noqa: S105 (senha efêmera do papel de app no container de teste)
_DB_NAME = "e1pdb"

_API_DIR = Path(__file__).resolve().parents[1]


def _bootstrap_rls_role(super_url: str) -> None:
    engine = create_engine(super_url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            conn.execute(text(f"CREATE ROLE e1p_app WITH LOGIN PASSWORD '{_APP_PASS}' NOSUPERUSER"))
            conn.execute(text(f"GRANT ALL PRIVILEGES ON DATABASE {_DB_NAME} TO e1p_app"))
            conn.execute(text("GRANT ALL ON SCHEMA public TO e1p_app"))
    finally:
        engine.dispose()


def _run_migrations_as_app(app_url: str) -> None:
    from alembic import command
    from alembic.config import Config

    from app.config import settings

    original_url = settings.database_url
    settings.database_url = app_url
    try:
        cfg = Config(str(_API_DIR / "alembic.ini"))
        cfg.set_main_option("script_location", str(_API_DIR / "migrations"))
        command.upgrade(cfg, "head")
    finally:
        settings.database_url = original_url


def _seed(app_url: str, *, slug: str, exibidas: str, pergunta: str) -> str:
    """Um tenant com uma passagem completa pelo núcleo: `open` → `save` → `abandon`.

    `exibidas` e `pergunta` distinguem o conteúdo entre tenants — se a leitura trocasse A por B
    (em vez de simplesmente vazar as duas), um teste que semeasse o MESMO roteiro nos dois não
    pegaria a troca. Grava via `eventos.registrar`, a mesma porta que `service._gravar` e
    `router.nucleo_evento` usam em produção — não `AuditEntry` direto, para o teste também provar
    que o vocabulário fechado sobrevive a uma sessão com GUC de tenant fixada à mão. Devolve o
    `tenant_id`.
    """
    from app.modules.auth.models import Tenant
    from app.modules.dna import eventos

    tenant_id = str(uuid4())
    engine = create_engine(app_url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            conn.execute(
                text("SELECT set_config('app.current_tenant_id', :tid, false)"), {"tid": tenant_id}
            )
            conn.commit()  # fixa a GUC (escopo de sessão) e encerra a txn — ver a nota do
            # test_financial_intelligence_diagnostics_rls sobre o SAVEPOINT.
            session = Session(bind=conn)
            session.add(Tenant(id=tenant_id, slug=slug, legal_name=slug, document=f"{slug}-doc"))
            session.flush()
            eventos.registrar(
                session,
                tenant_id=tenant_id,
                actor="u",
                action=eventos.ACTION_OPEN,
                target=exibidas,
            )
            eventos.registrar(
                session,
                tenant_id=tenant_id,
                actor="u",
                action=eventos.ACTION_SAVE,
                target=eventos.alvo_da_resposta("nucleo", pergunta),
            )
            eventos.registrar(
                session, tenant_id=tenant_id, actor="u", action=eventos.ACTION_ABANDON, target=""
            )
            session.commit()
            session.close()
    finally:
        engine.dispose()
    return tenant_id


def _entradas_como(app_url: str, tenant_id: str | None) -> list[str]:
    """Os `target`s da trilha do DNA vistos por esta sessão.

    ⚠️ **Sem ordem prometida.** As três chamadas de `_seed` correm na MESMA transação, e
    `AuditEntry.created_at` usa `server_default=func.now()` — em Postgres isso é o instante da
    TRANSAÇÃO, não da linha: as três saem com o MESMO carimbo, e a query de `entradas_do_dna`
    desempata por `id` (uuid), arbitrário. Afirmar a ordem aqui testaria o acaso (achado na
    primeira execução deste teste); o chamador compara por CONJUNTO.
    """
    from app.scripts.nucleo_activation import entradas_do_dna

    engine = create_engine(app_url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            if tenant_id is not None:
                conn.execute(
                    text("SELECT set_config('app.current_tenant_id', :tid, false)"),
                    {"tid": tenant_id},
                )
            session = Session(bind=conn)
            entradas = entradas_do_dna(session)
            session.close()
            return [e.target for e in entradas]
    finally:
        engine.dispose()


def test_a_ativacao_enxerga_a_propria_trilha_e_nao_a_do_vizinho() -> None:
    with PostgresContainer(
        "postgres:16-alpine",
        username=_ROOT_USER,
        password=_ROOT_PASS,
        dbname=_DB_NAME,
        driver="psycopg",
    ) as pg:
        host = pg.get_container_host_ip()
        port = pg.get_exposed_port(5432)
        super_url = f"postgresql+psycopg://{_ROOT_USER}:{_ROOT_PASS}@{host}:{port}/{_DB_NAME}"
        app_url = f"postgresql+psycopg://e1p_app:{_APP_PASS}@{host}:{port}/{_DB_NAME}"

        _bootstrap_rls_role(super_url)
        _run_migrations_as_app(app_url)

        a = _seed(app_url, slug="tenant-a", exibidas="6", pergunta="oferta.o_que_vende")
        b = _seed(app_url, slug="tenant-b", exibidas="5", pergunta="oferta.como_cobra")

        # (1) e (2) — o tenant A vê as TRÊS entradas da própria passagem, e não a de B.
        # Por conjunto, não por lista (ver a nota de `_entradas_como` sobre `func.now()`
        # por transação — a mesma razão que `test_investment_audit_rls` não tem aqui, porque lá
        # a ordem nunca era afirmada).
        alvos_a = _entradas_como(app_url, a)
        assert sorted(alvos_a) == sorted(["6", "nucleo:oferta.o_que_vende", ""])

        # (3) — e não vê nada do vizinho. Se a leitura trocasse A por B (em vez de vazar as duas),
        # o roteiro distinto de cada tenant denuncia: o relatório de ativação de A citaria a
        # pergunta de B — o modo de falha que o épico chama de "pior do que ficar calado".
        alvos_b = _entradas_como(app_url, b)
        assert sorted(alvos_b) == sorted(["5", "nucleo:oferta.como_cobra", ""])
        assert "nucleo:oferta.como_cobra" not in alvos_a
        assert "nucleo:oferta.o_que_vende" not in alvos_b

        # (4) — sem GUC: ZERO linhas, sem erro. É este silêncio que `main()` não pode confundir com
        # "nenhum tenant abriu o núcleo ainda", e por isso o script imprime a contagem de tenants.
        assert _entradas_como(app_url, None) == []
