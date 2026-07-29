"""Teste e2e de isolamento cross-tenant da bandeja de comprovantes no Postgres REAL (Story
"comprovante-compartilhar-celular", IV — Regra de Ouro nº 1).

Valida, sob RLS real (papel NÃO-superusuário `e1p_app`, que NÃO faz bypass de RLS):
- `link_receipt` NÃO vincula o comprovante da bandeja do tenant A a uma conta do tenant B: a
  conta de B é invisível para a sessão de A (RLS oculta a linha), então `db.get` devolve `None`
  e o service levanta "Conta não encontrada" (404 fail-closed na camada HTTP). O comprovante
  continua intacto na bandeja de A e a conta de B não é tocada;
- `get_staged` (base da bandeja/inbox) não resolve um anexo em staging de outro tenant, mesmo
  quando o `user_id` informado é o dono correto do lado de B — é a RLS na tabela `attachments`
  que barra, não o filtro de `owner_id`;
- `list_candidates` só devolve contas a pagar do tenant da sessão corrente.

Cada caso negativo vem acompanhado de um controle positivo (mesma operação, sob a ótica do
tenant dono) para provar que a asserção falha pelo motivo certo — não por dado ausente/id errado.

Mesmo bootstrap de test_cost_centers_rls.py / test_chart_of_accounts_rls.py: engine SQLAlchemy
"cru" da URL do container (sem reusar `tenant_session`, que fica preso a `settings.database_url`
no import), migrations aplicadas com `alembic upgrade head` como `e1p_app`. Módulo marcado
`rls_e2e`: NÃO roda no `pytest -q`/`scripts/check.sh` (suíte SQLite), só no job dedicado do CI
(`cross-tenant-rls`) ou manualmente com Docker (`pytest -m rls_e2e`).
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date
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

DUE_DATE = date(2026, 7, 15)


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


@contextmanager
def _tenant_session(app_url: str, tenant_id: str):
    """Abre uma engine/conexão isolada (NullPool = sem GUC vazando entre chamadas), fixa a GUC de
    tenant ANTES de qualquer query e cede uma `Session` ligada a essa conexão. Mesmo padrão de
    test_cost_centers_rls.py: `set_config(..., is_local=false)` seguido de `commit()` para ENCERRAR
    a txn — sem isso a Session usaria SAVEPOINT e o `session.commit()` do chamador não liberaria a
    txn externa (padrão de produção em app/db/session.py::tenant_session). Fecha a Session, a
    conexão e a engine na saída, mesmo se o corpo levantar."""
    engine = create_engine(app_url, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            conn.execute(
                text("SELECT set_config('app.current_tenant_id', :tid, false)"), {"tid": tenant_id}
            )
            conn.commit()
            session = Session(bind=conn)
            try:
                yield session
            finally:
                session.close()
    finally:
        engine.dispose()


def _stage_receipt(app_url: str, *, tenant_id: str, user_id: str, filename: str) -> str:
    """Sobe um comprovante para a bandeja do usuário, sob a ótica do tenant dono. Retorna o id do
    Attachment criado (ainda em OWNER_INBOX)."""
    from app.modules.payables import receipts

    with _tenant_session(app_url, tenant_id) as session:
        att = receipts.stage_receipt(
            session,
            tenant_id=tenant_id,
            user_id=user_id,
            actor=user_id,
            filename=filename,
            content_type="application/pdf",
            data=b"%PDF-1.4 conteudo fake de comprovante",
        )
        return att.id


def _create_bill(app_url: str, *, tenant_id: str, description: str) -> str:
    """Cria uma conta a pagar (status aberta) diretamente pelo model, sob a ótica do tenant dono."""
    from app.modules.payables.models import Payable

    with _tenant_session(app_url, tenant_id) as session:
        p = Payable(
            tenant_id=tenant_id, description=description, amount_cents=50000, due_date=DUE_DATE
        )
        session.add(p)
        session.commit()
        return p.id


def _link_receipt(
    app_url: str, *, viewer_tenant_id: str, user_id: str, attachment_id: str, bill_id: str
):
    """Chama `link_receipt` REAL sob a ótica de `viewer_tenant_id`. Devolve
    `(payable_id_ou_None, ReceiptError_ou_None)` — nunca deixa a exceção escapar, para o chamador
    decidir o que assertar."""
    from app.modules.payables import receipts

    with _tenant_session(app_url, viewer_tenant_id) as session:
        try:
            p = receipts.link_receipt(
                session,
                attachment_id=attachment_id,
                user_id=user_id,
                tenant_id=viewer_tenant_id,
                actor=user_id,
                bill_id=bill_id,
                mark_paid=False,
            )
            return p.id, None
        except receipts.ReceiptError as exc:
            session.rollback()
            return None, exc


def _get_staged(app_url: str, *, viewer_tenant_id: str, attachment_id: str, user_id: str):
    """Chama `get_staged` REAL sob a ótica de `viewer_tenant_id`. Devolve
    `(owner_type_ou_None, ReceiptError_ou_None)`."""
    from app.modules.payables import receipts

    with _tenant_session(app_url, viewer_tenant_id) as session:
        try:
            att = receipts.get_staged(session, attachment_id=attachment_id, user_id=user_id)
            return att.owner_type, None
        except receipts.ReceiptError as exc:
            return None, exc


def _bill_status(app_url: str, *, viewer_tenant_id: str, bill_id: str) -> str | None:
    """Status da conta pela ótica de `viewer_tenant_id` (None se a RLS a esconder)."""
    from app.modules.payables.models import Payable

    with _tenant_session(app_url, viewer_tenant_id) as session:
        p = session.get(Payable, bill_id)
        return p.status if p is not None else None


def _bill_has_attachment(app_url: str, *, viewer_tenant_id: str, bill_id: str) -> bool:
    """True se existir algum Attachment com owner_type=payable/owner_id=bill_id, pela ótica de
    `viewer_tenant_id`."""
    from app.modules.attachments import service as attachments_service
    from app.modules.payables.receipts import OWNER_PAYABLE

    with _tenant_session(app_url, viewer_tenant_id) as session:
        atts = attachments_service.list_for(session, owner_type=OWNER_PAYABLE, owner_id=bill_id)
        return len(atts) > 0


def _list_candidate_descriptions(app_url: str, *, viewer_tenant_id: str) -> list[str]:
    from app.modules.payables import receipts

    with _tenant_session(app_url, viewer_tenant_id) as session:
        candidates = receipts.list_candidates(session)
        return [p.description for p in candidates]


def test_receipts_cross_tenant_isolation() -> None:
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

        tenant_a = str(uuid4())
        tenant_b = str(uuid4())
        user_a = str(uuid4())
        user_b = str(uuid4())

        # ── Caso 1 (headline): link_receipt não vincula comprovante de A a conta de B ─────────
        att_a = _stage_receipt(app_url, tenant_id=tenant_a, user_id=user_a, filename="pix-a.pdf")
        bill_b = _create_bill(app_url, tenant_id=tenant_b, description="Conta-B-aluguel")

        payable_id, err = _link_receipt(
            app_url, viewer_tenant_id=tenant_a, user_id=user_a, attachment_id=att_a, bill_id=bill_b
        )
        assert payable_id is None, "RLS falhou: A conseguiu vincular o comprovante à conta de B"
        assert err is not None and err.status_code == 404, (
            "esperado ReceiptError 404 ('conta não encontrada') — a conta de B deve ser "
            "invisível para a sessão de A"
        )

        # O comprovante de A continua intacto na bandeja dele (não foi consumido pela tentativa).
        owner_type, get_err = _get_staged(
            app_url, viewer_tenant_id=tenant_a, attachment_id=att_a, user_id=user_a
        )
        assert get_err is None and owner_type == "receipt_inbox", (
            "o comprovante de A deveria continuar em staging após a tentativa cross-tenant falhar"
        )

        # A conta de B não foi tocada: continua aberta e sem nenhum anexo vinculado.
        assert _bill_status(app_url, viewer_tenant_id=tenant_b, bill_id=bill_b) == "open", (
            "RLS falhou: a conta de B foi alterada por uma chamada da sessão de A"
        )
        assert not _bill_has_attachment(app_url, viewer_tenant_id=tenant_b, bill_id=bill_b), (
            "RLS falhou: a conta de B recebeu o anexo de A"
        )

        # Controle positivo: o MESMO comprovante, vinculado a uma conta do PRÓPRIO tenant A,
        # funciona — prova que o 404 acima é isolamento, não um bug genérico em link_receipt.
        bill_a = _create_bill(app_url, tenant_id=tenant_a, description="Conta-A-internet")
        linked_id, ok_err = _link_receipt(
            app_url, viewer_tenant_id=tenant_a, user_id=user_a, attachment_id=att_a, bill_id=bill_a
        )
        assert ok_err is None and linked_id == bill_a, (
            "controle positivo falhou: A deveria conseguir vincular o próprio comprovante à "
            "própria conta"
        )
        assert _bill_has_attachment(app_url, viewer_tenant_id=tenant_a, bill_id=bill_a), (
            "controle positivo falhou: o anexo deveria estar vinculado à conta de A"
        )

        # ── Caso 2: get_staged (bandeja) não resolve anexo em staging de outro tenant ──────────
        att_b = _stage_receipt(app_url, tenant_id=tenant_b, user_id=user_b, filename="pix-b.pdf")

        # A sessão de A tenta resolver o anexo de B usando o `user_id` CORRETO do lado de B — só
        # o tenant difere. Se isso ainda assim resolvesse, a falha seria da RLS, não do filtro de
        # owner_id (que aqui bateria).
        leaked_owner_type, leak_err = _get_staged(
            app_url, viewer_tenant_id=tenant_a, attachment_id=att_b, user_id=user_b
        )
        assert leaked_owner_type is None, "RLS falhou: A resolveu o comprovante em staging de B"
        assert leak_err is not None and leak_err.status_code == 404

        # Controle positivo: a própria B, com o mesmo attachment_id/user_id, resolve normalmente.
        owner_type_b, err_b = _get_staged(
            app_url, viewer_tenant_id=tenant_b, attachment_id=att_b, user_id=user_b
        )
        assert err_b is None and owner_type_b == "receipt_inbox", (
            "controle positivo falhou: B deveria conseguir ver o próprio comprovante em staging"
        )

        # ── Caso 3: list_candidates só devolve contas do tenant da sessão corrente ─────────────
        _create_bill(app_url, tenant_id=tenant_a, description="Conta-A-agua")
        _create_bill(app_url, tenant_id=tenant_b, description="Conta-B-luz")
        _create_bill(app_url, tenant_id=tenant_b, description="Conta-B-internet")

        candidates_a = _list_candidate_descriptions(app_url, viewer_tenant_id=tenant_a)
        assert "Conta-A-agua" in candidates_a
        assert "Conta-A-internet" in candidates_a  # criada e vinculada no Caso 1
        assert not any(desc.startswith("Conta-B-") for desc in candidates_a), (
            "RLS falhou: list_candidates de A trouxe contas do tenant B"
        )

        candidates_b = _list_candidate_descriptions(app_url, viewer_tenant_id=tenant_b)
        assert "Conta-B-luz" in candidates_b
        assert "Conta-B-internet" in candidates_b
        assert "Conta-B-aluguel" in candidates_b  # criada no Caso 1, nunca vinculada
        assert not any(desc.startswith("Conta-A-") for desc in candidates_b), (
            "RLS falhou: list_candidates de B trouxe contas do tenant A"
        )
