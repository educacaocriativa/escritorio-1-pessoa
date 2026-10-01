"""Ingestão de leads sob RLS REAL (papel não-superusuário `e1p_app`, Postgres via testcontainers).

Mesmo bootstrap de `test_crm_events_rls.py`: engine cru da URL do container, migrations com
`alembic upgrade head` como `e1p_app`. Cada caso negativo tem controle positivo.

Marcado `rls_e2e`: NÃO roda no `pytest -q` (suíte SQLite), só no job `cross-tenant-rls` do CI
ou manualmente com Docker (`pytest -m rls_e2e`).
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import pytest

pytest.importorskip("testcontainers.postgres")

from sqlalchemy import create_engine, inspect, text  # noqa: E402
from sqlalchemy.dialects import postgresql  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402
from testcontainers.postgres import PostgresContainer  # noqa: E402

from app.core import events  # noqa: E402
from app.modules.crm import service as crm_service  # noqa: E402
from app.modules.lead_ingest import registro as registro_service  # noqa: E402
from app.modules.lead_ingest import service as ingest_service  # noqa: E402
from app.modules.lead_ingest.models import LeadIngestRecord  # noqa: E402
from app.modules.machine_tokens import service as machine_tokens_service  # noqa: E402
from app.modules.machine_tokens.models import SCOPE_LEAD_INGEST, MachineToken  # noqa: E402
from app.modules.settings.models import TenantProfile  # noqa: E402
from tests.lead_ingest_apoio import corpo, payload  # noqa: E402

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


@pytest.fixture(scope="module")
def ambiente():
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
        yield {
            "url": app_url,
            "super_url": super_url,
            "tenant_a": str(uuid4()),
            "tenant_b": str(uuid4()),
        }


@pytest.fixture(autouse=True)
def _sem_assinantes():
    # `move_client` emite `crm.client.moved`; o assinante de notifications abriria
    # `tenant_session` na URL de settings, não na do container.
    events.clear()
    yield
    events.clear()


@contextmanager
def _sessao(url: str, tenant_id: str | None):
    """Espelho de `db.session.tenant_session` apontado ao container (GUC em escopo de sessão)."""
    engine = create_engine(url, poolclass=NullPool)
    conn = engine.connect()
    try:
        if tenant_id is not None:
            conn.execute(
                text("SELECT set_config('app.current_tenant_id', :t, false)"), {"t": tenant_id}
            )
            conn.commit()
        db = Session(bind=conn, autoflush=False, expire_on_commit=False)
        try:
            yield db
        finally:
            db.close()
    finally:
        conn.close()
        engine.dispose()


def _email() -> str:
    return f"{uuid4().hex[:12]}@exemplo.gov.br"


def _ingere(url: str, tenant_id: str, **sobre):
    with _sessao(url, tenant_id) as db:
        return ingest_service.ingest(db, tenant_id=tenant_id, dados=payload(**sobre))


def test_registro_de_ingestao_e_isolado_e_fail_closed(ambiente):
    url, a, b = ambiente["url"], ambiente["tenant_a"], ambiente["tenant_b"]
    chave = f"site:lead:{uuid4()}"
    assert _ingere(url, a, chave_idempotencia=chave, contato={"email": _email()}).processado

    def _conta(tenant_id: str | None) -> int:
        with _sessao(url, tenant_id) as db:
            return db.scalar(
                text("SELECT count(*) FROM lead_ingest_records WHERE chave_idempotencia = :c"),
                {"c": chave},
            )

    assert _conta(a) == 1  # controle positivo: o dono enxerga
    assert _conta(b) == 0  # outro tenant não enxerga
    assert _conta(None) == 0  # sessão sem GUC não enxerga nada


def test_mesma_chave_em_dois_tenants_processa_nos_dois(ambiente):
    url, a, b = ambiente["url"], ambiente["tenant_a"], ambiente["tenant_b"]
    chave = f"kiwify:{uuid4()}:compra_aprovada"
    for tenant_id in (a, b):
        resultado = _ingere(
            url, tenant_id, evento="compra_aprovada", chave_idempotencia=chave,
            contato={"email": _email()},
        )
        assert resultado.processado is True


def test_contato_de_outro_tenant_nao_e_reaproveitado(ambiente):
    url, a, b = ambiente["url"], ambiente["tenant_a"], ambiente["tenant_b"]
    email, telefone = _email(), f"(11) 9{uuid4().int % 10**8:08d}"
    contato = {"nome": "Maria", "email": email, "telefone": telefone}
    em_b = _ingere(url, b, chave_idempotencia=f"site:lead:{uuid4()}", contato=contato)
    em_a = _ingere(url, a, chave_idempotencia=f"site:lead:{uuid4()}", contato=contato)

    assert em_a.processado is True
    assert em_a.contato_id != em_b.contato_id
    with _sessao(url, a) as db:
        assert db.scalar(
            text("SELECT tenant_id FROM clients WHERE id = :id"), {"id": em_a.contato_id}
        ) == a
        assert db.scalar(
            text("SELECT count(*) FROM clients WHERE id = :id"), {"id": em_b.contato_id}
        ) == 0
    with _sessao(url, b) as db:  # controle positivo: B continua com o seu, intocado
        assert db.scalar(
            text("SELECT count(*) FROM facts WHERE client_id = :id AND kind = :k"),
            {"id": em_b.contato_id, "k": "comercial.lead.recebido"},
        ) == 1


def test_retentativas_concorrentes_da_mesma_chave_so_uma_tem_efeito(ambiente, monkeypatch):
    url, a = ambiente["url"], ambiente["tenant_a"]
    # Aquece: perfil e colunas do Kanban já existem, senão as duas threads disputariam o seed.
    _ingere(url, a, chave_idempotencia=f"aquece:{uuid4()}", contato={"email": _email()})

    original = crm_service.absorb_lead

    def _lento(*args, **kwargs):
        # Segura a reivindicação ABERTA (não commitada) tempo suficiente para a outra thread
        # bater no índice único e ficar esperando — a janela real do reenvio da Kiwify.
        time.sleep(1.0)
        return original(*args, **kwargs)

    monkeypatch.setattr(crm_service, "absorb_lead", _lento)
    chave, email = f"kiwify:{uuid4()}:lead", _email()
    largada = threading.Barrier(2)

    def _envia():
        largada.wait()
        return _ingere(url, a, chave_idempotencia=chave, contato={"email": email})

    with ThreadPoolExecutor(max_workers=2) as pool:
        futuros = [pool.submit(_envia), pool.submit(_envia)]
        resultados = [f.result(timeout=30) for f in futuros]

    assert sorted(r.processado for r in resultados) == [False, True]
    with _sessao(url, a) as db:
        assert db.scalar(
            text(
                "SELECT count(*) FROM facts f JOIN lead_ingest_records r ON f.subject_id = r.id "
                "WHERE r.chave_idempotencia = :c AND f.kind = 'comercial.lead.recebido'"
            ),
            {"c": chave},
        ) == 1
        assert db.scalar(text("SELECT count(*) FROM clients WHERE email = :e"), {"e": email}) == 1


def test_credencial_de_maquina_resolve_sem_tenant_na_sessao(ambiente):
    """O caminho de produção: `get_db` (sem GUC) lê `machine_tokens`, tabela global."""
    url, a = ambiente["url"], ambiente["tenant_a"]
    with _sessao(url, None) as db:
        _, raw = machine_tokens_service.create_token(
            db, tenant_id=a, name="site", scope=SCOPE_LEAD_INGEST
        )
        assert machine_tokens_service.resolve(db, raw=raw, scope=SCOPE_LEAD_INGEST).tenant_id == a


# ── Rulings do controlador: trava real, janela pós-commit do absorb_lead, schema e rota ──────


class _Pausa:
    """Para a PRIMEIRA thread que passar por `ponto()` até `soltar()`; as outras passam direto."""

    def __init__(self) -> None:
        self._trava = threading.Lock()
        self._usada = False
        self.chegou = threading.Event()
        self._solta = threading.Event()

    def ponto(self) -> None:
        with self._trava:
            primeira, self._usada = not self._usada, True
        if primeira:
            self.chegou.set()
            if not self._solta.wait(timeout=60):
                raise TimeoutError("a pausa nunca foi solta")

    def soltar(self) -> None:
        self._solta.set()


def _fatos_da_chave(db: Session, chave: str, kind: str) -> int:
    return db.scalar(
        text(
            "SELECT count(*) FROM facts f JOIN lead_ingest_records r ON f.subject_id = r.id "
            "WHERE r.chave_idempotencia = :c AND f.kind = :k"
        ),
        {"c": chave, "k": kind},
    )


def _espera_alguem_travado_em_lead_ingest(super_url: str, timeout: float = 10.0) -> bool:
    """`True` quando um backend está parado em `Lock` numa consulta a `lead_ingest_records`."""
    engine = create_engine(super_url, poolclass=NullPool, isolation_level="AUTOCOMMIT")
    try:
        limite = time.monotonic() + timeout
        with engine.connect() as conn:
            while time.monotonic() < limite:
                travados = conn.scalar(
                    text(
                        "SELECT count(*) FROM pg_stat_activity WHERE datname = :d "
                        "AND wait_event_type = 'Lock' AND query ILIKE '%lead_ingest_records%'"
                    ),
                    {"d": _DB_NAME},
                )
                if travados:
                    return True
                time.sleep(0.05)
        return False
    finally:
        engine.dispose()


@pytest.mark.parametrize("reivindicacao", ["nova", "retomada"])
def test_retentativa_na_janela_apos_o_commit_do_absorb_lead_nao_duplica_o_fato(
    ambiente, monkeypatch, reivindicacao
):
    """A para logo depois de `_resolve_contato`: `absorb_lead` já commitou, a reivindicação está
    visível, SEM conclusão e SEM trava. B (mesma chave) chega aí, retoma e conclui. Quando A
    volta, a re-trava (`_buscar(travar=True)`) tem de ver a conclusão de B.

    `retomada`: a chave já estava reivindicada e sem conclusão (queda entre os dois commits), e
    A a retoma. Aí `concluido_em=None` foi CARREGADO no identity map de A por `reivindicar` — é
    o caso em que só o `populate_existing` da re-trava impede A de escrever o segundo fato. (Na
    `nova`, o atributo nunca foi carregado depois do INSERT e a re-trava o preenche de qualquer
    jeito.)
    """
    url, a = ambiente["url"], ambiente["tenant_a"]
    _ingere(url, a, chave_idempotencia=f"aquece:{uuid4()}", contato={"email": _email()})
    chave, email = f"kiwify:{uuid4()}:lead", _email()
    if reivindicacao == "retomada":
        with _sessao(url, a) as db:
            assert registro_service.reivindicar(
                db, tenant_id=a, chave=chave, evento="lead",
                ocorrido_em=payload().ocorrido_em, payload={},
            ) is not None
            db.commit()  # e "cai" aqui: reivindicada, nunca concluída

    pausa = _Pausa()
    original = ingest_service._resolve_contato

    def _resolve_e_para(*args, **kwargs):
        contato = original(*args, **kwargs)
        pausa.ponto()
        return contato

    monkeypatch.setattr(ingest_service, "_resolve_contato", _resolve_e_para)

    with ThreadPoolExecutor(max_workers=2) as pool:
        try:
            futuro_a = pool.submit(
                _ingere, url, a, chave_idempotencia=chave, contato={"email": email}
            )
            assert pausa.chegou.wait(timeout=30), "A não chegou ao ponto pós-absorb_lead"
            # Com A parado, B vai do começo ao fim: nada que A segure pode prendê-lo.
            segunda = pool.submit(
                _ingere, url, a, chave_idempotencia=chave, contato={"email": email}
            ).result(timeout=30)
        finally:
            pausa.soltar()
        primeira = futuro_a.result(timeout=30)

    assert segunda.processado is True  # B retomou a reivindicação sem conclusão
    assert primeira.processado is False  # A releu a conclusão de B e não escreveu nada
    assert primeira.contato_id == segunda.contato_id
    with _sessao(url, a) as db:
        assert _fatos_da_chave(db, chave, "comercial.lead.recebido") == 1
        assert db.scalar(
            text(
                "SELECT count(*) FROM lead_ingest_records "
                "WHERE chave_idempotencia = :c AND concluido_em IS NOT NULL"
            ),
            {"c": chave},
        ) == 1
        assert db.scalar(
            text(
                "SELECT count(*) FROM audit_entries a JOIN lead_ingest_records r "
                "ON a.target = r.id WHERE r.chave_idempotencia = :c "
                "AND a.action = 'lead_ingest.process'"
            ),
            {"c": chave},
        ) == 1
        assert db.scalar(text("SELECT count(*) FROM clients WHERE email = :e"), {"e": email}) == 1


def test_retentativa_espera_a_trava_e_enxerga_a_chave_concluida(ambiente, monkeypatch):
    """A retomou a trava (pós-`absorb_lead`) e está no meio de tags/fato. B, mesma chave, fica
    PARADO no `FOR UPDATE` de `reivindicar` até A commitar — e então lê `concluido_em`
    preenchido: responde "já processado" sem nem passar por `absorb_lead`.
    """
    url, a = ambiente["url"], ambiente["tenant_a"]
    _ingere(url, a, chave_idempotencia=f"aquece:{uuid4()}", contato={"email": _email()})

    pausa = _Pausa()
    original = ingest_service.somar_tags

    def _soma_e_para(*args, **kwargs):
        pausa.ponto()  # depois da re-trava, antes de fato + conclusão + commit
        return original(*args, **kwargs)

    monkeypatch.setattr(ingest_service, "somar_tags", _soma_e_para)
    chave, email = f"kiwify:{uuid4()}:lead", _email()

    with ThreadPoolExecutor(max_workers=2) as pool:
        try:
            futuro_a = pool.submit(
                _ingere, url, a, chave_idempotencia=chave, contato={"email": email}
            )
            assert pausa.chegou.wait(timeout=30), "A não chegou à re-trava"
            futuro_b = pool.submit(
                _ingere, url, a, chave_idempotencia=chave, contato={"email": email}
            )
            assert _espera_alguem_travado_em_lead_ingest(ambiente["super_url"]), (
                "B não ficou esperando a trava de A em lead_ingest_records"
            )
            assert not futuro_b.done()
        finally:
            pausa.soltar()
        primeira, segunda = futuro_a.result(timeout=30), futuro_b.result(timeout=30)

    assert primeira.processado is True
    assert segunda.processado is False
    assert segunda.contato_id == primeira.contato_id
    with _sessao(url, a) as db:
        assert _fatos_da_chave(db, chave, "comercial.lead.recebido") == 1
        # B não resolveu contato: viu a conclusão ANTES de chegar a `absorb_lead`.
        assert db.scalar(
            text("SELECT count(*) FROM facts WHERE client_id = :id AND kind = 'crm.lead.retornou'"),
            {"id": primeira.contato_id},
        ) == 0


def _tipo_pg(tipo) -> str:
    return tipo.compile(dialect=postgresql.dialect())


def test_migracoes_0088_a_0090_batem_com_os_modelos_e_forcam_rls(ambiente):
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config(str(_API_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(_API_DIR / "migrations"))
    head = ScriptDirectory.from_config(cfg).get_current_head()

    engine = create_engine(ambiente["url"], poolclass=NullPool)
    try:
        with engine.connect() as conn:
            assert conn.scalar(text("SELECT version_num FROM alembic_version")) == head
            insp = inspect(conn)

            for modelo in (MachineToken, LeadIngestRecord):
                tabela = modelo.__table__
                no_banco = {c["name"]: c for c in insp.get_columns(tabela.name)}
                assert set(no_banco) == {c.name for c in tabela.columns}, tabela.name
                for coluna in tabela.columns:
                    real = no_banco[coluna.name]
                    assert real["nullable"] == coluna.nullable, (tabela.name, coluna.name)
                    assert _tipo_pg(real["type"]) == _tipo_pg(coluna.type), (
                        tabela.name, coluna.name
                    )
                indices_modelo = {
                    (i.name, tuple(c.name for c in i.columns), bool(i.unique))
                    for i in tabela.indexes
                }
                indices_banco = {
                    (i["name"], tuple(i["column_names"]), bool(i["unique"]))
                    for i in insp.get_indexes(tabela.name)
                    if "duplicates_constraint" not in i
                }
                assert indices_banco == indices_modelo, tabela.name

            perfil = {c["name"]: c for c in insp.get_columns("tenant_profiles")}
            config = perfil["lead_ingest_config"]
            modelo_config = TenantProfile.__table__.c.lead_ingest_config
            assert config["nullable"] is False and modelo_config.nullable is False
            assert _tipo_pg(config["type"]) == _tipo_pg(modelo_config.type) == "JSON"
            assert config["default"] == "'{}'::json"

            registros = {c["name"]: c for c in insp.get_columns("lead_ingest_records")}
            assert registros["payload"]["default"] == "'{}'::json"
            assert registros["tags_descartadas"]["default"] == "'[]'::json"

            unicas = {
                u["name"]: u["column_names"]
                for u in insp.get_unique_constraints("lead_ingest_records")
            }
            assert unicas == {"uq_lead_ingest_tenant_chave": ["tenant_id", "chave_idempotencia"]}
            (fk,) = insp.get_foreign_keys("lead_ingest_records")
            assert (fk["constrained_columns"], fk["referred_table"], fk["referred_columns"]) == (
                ["client_id"], "clients", ["id"]
            )
            assert fk["options"].get("ondelete") == "CASCADE"

            rls = {
                linha.relname: (linha.relrowsecurity, linha.relforcerowsecurity)
                for linha in conn.execute(
                    text(
                        "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
                        "WHERE relname IN ('lead_ingest_records', 'machine_tokens')"
                    )
                )
            }
            assert rls["lead_ingest_records"] == (True, True)
            assert rls["machine_tokens"] == (False, False)  # global por desenho (0088)
            politica = conn.execute(
                text(
                    "SELECT qual, with_check FROM pg_policies "
                    "WHERE tablename = 'lead_ingest_records' AND policyname = 'tenant_isolation'"
                )
            ).one()
            assert "app.current_tenant_id" in politica.qual
            assert "app.current_tenant_id" in politica.with_check
    finally:
        engine.dispose()


def test_rota_grava_no_tenant_do_token_e_ignora_o_tenant_do_corpo(ambiente, monkeypatch):
    """`POST /public/ingest/leads` de ponta a ponta, com o `get_db` e o `tenant_session` DE
    PRODUÇÃO (só o engine trocado pelo do container): token de A + corpo citando B = linhas
    só em A, e B (sob RLS) não vê nada.
    """
    from fastapi.testclient import TestClient

    from app.db import session as db_session
    from app.main import app

    url, a, b = ambiente["url"], ambiente["tenant_a"], ambiente["tenant_b"]
    engine = create_engine(url, poolclass=NullPool)
    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(
        db_session,
        "SessionLocal",
        sessionmaker(bind=engine, autoflush=False, expire_on_commit=False),
    )
    assert not app.dependency_overrides  # nada de fábrica de teste no caminho
    with _sessao(url, None) as db:
        _, raw = machine_tokens_service.create_token(
            db, tenant_id=a, name="site", scope=SCOPE_LEAD_INGEST
        )
    chave, email = f"site:lead:{uuid4()}", _email()

    try:
        with TestClient(app) as http:
            resposta = http.post(
                "/public/ingest/leads",
                json=corpo(chave_idempotencia=chave, contato={"email": email}, tenant_id=b),
                headers={"Authorization": f"Bearer {raw}"},
            )
    finally:
        engine.dispose()

    assert resposta.status_code == 201, resposta.text
    contato_id = resposta.json()["contato_id"]

    def _conta(tenant_id: str, sql: str, **params) -> int:
        with _sessao(url, tenant_id) as db:
            return db.scalar(text(sql), params)

    registro = "SELECT count(*) FROM lead_ingest_records WHERE chave_idempotencia = :c"
    cliente = "SELECT count(*) FROM clients WHERE email = :e"
    assert _conta(a, registro, c=chave) == 1  # controle positivo: caiu no tenant do token
    assert _conta(a, "SELECT count(*) FROM clients WHERE id = :i AND tenant_id = :t",
                  i=contato_id, t=a) == 1
    assert _conta(b, registro, c=chave) == 0  # o tenant do corpo não recebeu nada
    assert _conta(b, cliente, e=email) == 0


def test_admin_recusa_funil_de_outro_tenant_e_aceita_o_proprio(ambiente, monkeypatch, capsys):
    """`lead_ingest_admin` com o `get_db`/`tenant_session` DE PRODUÇÃO (engine do container):
    funil do tenant B no mapa do tenant A é recusado (exit 2) e a config de A não muda;
    controle positivo: funil do próprio A passa.
    """
    from app.db import session as db_session
    from app.modules.auth.models import Tenant
    from app.modules.funnels.models import Funnel
    from app.scripts import lead_ingest_admin as admin

    url, a, b = ambiente["url"], ambiente["tenant_a"], ambiente["tenant_b"]
    slug_a = f"a{uuid4().hex[:10]}"
    with _sessao(url, None) as db:
        for tid, slug in ((a, slug_a), (b, f"b{uuid4().hex[:10]}")):
            if db.get(Tenant, tid) is None:
                db.add(Tenant(id=tid, slug=slug, legal_name=slug, document=uuid4().hex[:14]))
        db.commit()
    with _sessao(url, a) as db:
        funil_a = Funnel(tenant_id=a, name="A", nodes=[{"id": "n1"}], edges=[])
        db.add(funil_a)
        db.commit()
        funil_a_id = funil_a.id
    with _sessao(url, b) as db:
        funil_b = Funnel(tenant_id=b, name="B", nodes=[{"id": "n1"}], edges=[])
        db.add(funil_b)
        db.commit()
        funil_b_id = funil_b.id
    slug_a = _slug(url, a)  # o tenant A pode já existir (módulo compartilhado) com outro slug

    engine = create_engine(url, poolclass=NullPool)
    monkeypatch.setattr(db_session, "engine", engine)
    monkeypatch.setattr(
        db_session,
        "SessionLocal",
        sessionmaker(bind=engine, autoflush=False, expire_on_commit=False),
    )
    try:
        # controle positivo
        positivo = ["configurar", "--tenant", slug_a, "--produto", "publia",
                    "--funil", f"lead={funil_a_id}"]
        assert admin.main(positivo) == 0
        capsys.readouterr()
        # negativo: funil do B
        assert admin.main(
            ["configurar", "--tenant", slug_a, "--funil", f"compra_aprovada={funil_b_id}"]
        ) == 2
        assert "Funil não encontrado" in capsys.readouterr().err
    finally:
        engine.dispose()

    with _sessao(url, a) as db:
        config = db.scalar(text("SELECT lead_ingest_config FROM tenant_profiles"))
    assert config == {"produto": "publia", "funis": {"lead": funil_a_id}}


def _slug(url: str, tenant_id: str) -> str | None:
    from app.modules.auth.models import Tenant

    with _sessao(url, None) as db:
        t = db.get(Tenant, tenant_id)
        return t.slug if t else None
