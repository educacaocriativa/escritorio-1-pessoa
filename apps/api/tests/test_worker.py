"""Worker durável (Story 4.3): run_sweep dispara o tick do funil + processa a fila, por tenant.

Usa a sessão SQLite compartilhada (fixture `db`) via injeção de `session_factory`/
`tenant_session_factory` — mesmo idioma do `conftest.py::_override_factory`. Cobre: retomada de
funil pelo worker (IV1), processamento da fila, no-op idempotente, isolamento de falha por
etapa/tenant (IV2) e exclusão do tenant "platform".
"""
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from app import worker
from app.modules.auth.models import Tenant
from app.modules.notifications import service as notif_service
from app.modules.notifications.models import Notification
from app.worker import _tenant_ids, run_sweep


def _cm_factory(db):
    """Context manager que devolve a sessão de teste SEM fechá-la (compartilhada).

    Serve tanto como `session_factory()` (sem args) quanto `tenant_session_factory(tenant_id)`.
    """

    @contextmanager
    def _cm(*_args, **_kwargs):
        yield db

    return _cm


def _make_tenant(db, *, slug, document="00000000000191"):
    tenant = Tenant(slug=slug, legal_name=f"{slug} SA", document=document)
    db.add(tenant)
    db.flush()
    return tenant


# --- Funil resume via worker (usa a máquina HTTP p/ montar funil + enroll) ------------------

REGISTER = {
    "legal_name": "Worker SA",
    "document": "55544433000108",
    "slug": "workersa",
    "email": "worker@example.com",
    "name": "Dona Worker",
    "password": "senha-bem-comprida",
}


def _node(nid, key, action="", config=None):
    return {"id": nid, "type": "funnelNode",
            "data": {"key": key, "action": action, "label": key, "config": config or {}}}


def _edge(src, tgt):
    return {"id": f"{src}-{tgt}", "source": src, "target": tgt}


def test_run_sweep_resumes_due_funnel(client: TestClient, db):
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    cid = client.post("/crm/clients", json={"name": "Contato"}, headers=headers).json()["id"]
    nodes = [
        _node("n1", "esperar", config={"delay_seconds": 0}),
        _node("n2", "tag", "add_tag", config={"tag": "resumido"}),
    ]
    edges = [_edge("n1", "n2")]
    fid = client.post(
        "/funnels", json={"name": "Fluxo", "nodes": nodes, "edges": edges}, headers=headers
    ).json()["id"]
    run = client.post(f"/funnels/{fid}/enroll", json={"client_id": cid}, headers=headers).json()
    assert run["status"] == "waiting"

    cm = _cm_factory(db)
    result = run_sweep(session_factory=cm, tenant_session_factory=cm)

    assert result["tenants_checked"] == 1
    assert result["funnel_resumed"] == 1
    assert result["errors"] == []
    done = client.get(f"/funnels/runs/{run['id']}", headers=headers).json()
    assert done["status"] == "done"


# --- Fila de notificações via worker --------------------------------------------------------

def test_run_sweep_processes_pending_notification(db):
    tenant = _make_tenant(db, slug="notif")
    notif_service.enqueue(
        db, tenant_id=tenant.id, channel="whatsapp", recipient="d@e.com", message="oi"
    )
    db.commit()

    cm = _cm_factory(db)
    result = run_sweep(session_factory=cm, tenant_session_factory=cm)

    assert result["tenants_checked"] == 1
    assert result["notifications_processed"] == 1
    assert result["errors"] == []
    assert db.scalar(select(Notification)).status != "pending"


def test_run_sweep_noop_is_idempotent(db):
    _make_tenant(db, slug="vazio")
    cm = _cm_factory(db)

    first = run_sweep(session_factory=cm, tenant_session_factory=cm)
    second = run_sweep(session_factory=cm, tenant_session_factory=cm)

    for res in (first, second):
        assert res["tenants_checked"] == 1
        assert res["funnel_resumed"] == 0
        assert res["notifications_processed"] == 0
        assert res["errors"] == []


def test_run_sweep_isolates_stage_failure(db, monkeypatch):
    # tick lança para o tenant, mas a etapa da fila (sessão separada) ainda roda — e o sweep
    # não morre: o erro é acumulado em `errors` (IV2).
    tenant = _make_tenant(db, slug="falha")
    notif_service.enqueue(
        db, tenant_id=tenant.id, channel="whatsapp", recipient="d@e.com", message="oi"
    )
    db.commit()

    def _boom(*_a, **_k):
        raise RuntimeError("tick explodiu")

    monkeypatch.setattr(worker.funnels_engine, "tick", _boom)

    cm = _cm_factory(db)
    result = run_sweep(session_factory=cm, tenant_session_factory=cm)

    assert result["notifications_processed"] == 1  # a fila rodou mesmo com o tick falhando
    assert len(result["errors"]) == 1
    assert result["errors"][0]["stage"] == "tick"
    assert result["errors"][0]["tenant_id"] == tenant.id


def test_tenant_ids_excludes_platform(db):
    _make_tenant(db, slug="platform", document="00000000000000")  # tenant interno da plataforma
    real = _make_tenant(db, slug="real")
    db.commit()

    ids = _tenant_ids(db)
    assert ids == [real.id]


def test_run_sweep_continues_across_tenants(db, monkeypatch):
    # Dois tenants com fila; o tick sempre falha, mas AMBOS têm a fila processada e o loop não para.
    t1 = _make_tenant(db, slug="t1", document="00000000000191")
    t2 = _make_tenant(db, slug="t2", document="00000000000272")
    for t in (t1, t2):
        notif_service.enqueue(
            db, tenant_id=t.id, channel="whatsapp", recipient="d@e.com", message="oi"
        )
    db.commit()

    def _boom(*_a, **_k):
        raise RuntimeError("tick explodiu")

    monkeypatch.setattr(worker.funnels_engine, "tick", _boom)

    cm = _cm_factory(db)
    result = run_sweep(session_factory=cm, tenant_session_factory=cm)

    assert result["tenants_checked"] == 2
    assert result["notifications_processed"] == 2
    assert len(result["errors"]) == 2  # um erro de tick por tenant, nenhum trava o sweep


# ── Story 8.14 (AC10) — a etapa 4: promoção `scheduled → paid` ────────────────────────────────
#
# ⚠️ **O worker é COSMÉTICA DE STATUS, não componente da aritmética** (F-D11). O movimento bancário
# nasce com `posted_at` = a data agendada, e tanto o saldo derivado quanto a Projeção são função da
# **data**. A prova disso vive em `test_payables_scheduled.py::test_O_SALDO_DERIVADO_NAO_DEPENDE_DO_
# WORKER` e em `test_financial_intelligence_projection.py::test_AC6_o_numero_e_IDENTICO_com_e_sem_o_
# worker`. Aqui testamos a etapa em si: o contador, a idempotência e o **isolamento de falha**.


def _tenant_com_conta_agendada(client: TestClient, *, dias: int = 5):
    """Um tenant real com uma conta a pagar AGENDADA para daqui a `dias`.

    Devolve `(headers, bill)`. A conta nasce agendada pelo caminho de PRODUÇÃO (a rota de baixa com
    data futura), nunca plantada pelo model: o estado é derivado da data, e montá-lo à mão aqui
    esconderia justamente a derivação que a etapa 4 depende.
    """
    registro = {
        "legal_name": "Agenda Worker SA",
        "document": "11444777000161",
        "slug": "agendaworker",
        "email": "agendaworker@example.com",
        "name": "Selma",
        "password": "senha-bem-comprida",
    }
    token = client.post("/auth/register", json=registro).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    hoje = datetime.now(UTC).date()
    conta = client.post(
        "/bank/accounts",
        json={
            "name": "Itaú PJ",
            "kind": "checking",
            "opening_balance_cents": 100_000_00,
            "opening_balance_is_known": True,
            "opening_date": (hoje - timedelta(days=90)).isoformat(),
        },
        headers=headers,
    ).json()
    bill = client.post(
        "/payables/bills",
        json={"description": "Aluguel", "amount_cents": 5_000_00, "due_date": hoje.isoformat()},
        headers=headers,
    ).json()
    resp = client.post(
        f"/payables/bills/{bill['id']}/pay",
        json={
            "bank_account_id": conta["id"],
            "paid_on": (hoje + timedelta(days=dias)).isoformat(),
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "scheduled", "pré-condição: a conta tinha de nascer agendada"
    return headers, bill


def test_etapa4_promove_a_agendada_quando_o_dia_chega(client: TestClient, db):
    """O sweep com `now` INJETADO depois do dia do débito promove a conta e conta no resultado."""
    headers, bill = _tenant_com_conta_agendada(client, dias=5)
    cm = _cm_factory(db)

    depois = datetime.now(UTC) + timedelta(days=6)
    result = run_sweep(session_factory=cm, tenant_session_factory=cm, now=depois)

    assert result["scheduled_promoted"] == 1
    assert client.get(
        f"/payables/bills/{bill['id']}", headers=headers
    ).json()["status"] == "paid"


def test_etapa4_nao_promove_o_que_ainda_nao_venceu(client: TestClient, db):
    """O sweep de hoje **não** toca a conta agendada para daqui a 5 dias. `now=None` = agora."""
    headers, bill = _tenant_com_conta_agendada(client, dias=5)
    cm = _cm_factory(db)

    result = run_sweep(session_factory=cm, tenant_session_factory=cm)

    assert result["scheduled_promoted"] == 0
    assert client.get(
        f"/payables/bills/{bill['id']}", headers=headers
    ).json()["status"] == "scheduled"


def test_etapa4_e_idempotente_entre_sweeps(client: TestClient, db):
    """Dois sweeps seguidos: promove no primeiro, **zero** no segundo."""
    _tenant_com_conta_agendada(client, dias=2)
    cm = _cm_factory(db)
    depois = datetime.now(UTC) + timedelta(days=3)

    primeiro = run_sweep(session_factory=cm, tenant_session_factory=cm, now=depois)
    segundo = run_sweep(session_factory=cm, tenant_session_factory=cm, now=depois)

    assert primeiro["scheduled_promoted"] == 1
    assert segundo["scheduled_promoted"] == 0, "a etapa 4 não é idempotente"


def test_falha_na_etapa4_NAO_derruba_as_outras_tres(client: TestClient, db, monkeypatch):
    """**IV4 — o isolamento de falha vale para a etapa nova exatamente como para as três antigas.**

    Um erro na promoção é logado, entra em `errors` com `stage="scheduled_promote"` e **não** impede
    o tick do funil, a fila de notificações nem a mídia do WhatsApp — nem para este tenant, nem para
    os demais. Sem isso, uma conta a pagar malformada de um tenant pararia a entrega de notificação
    de todo mundo.
    """
    from app.modules.payables import service as payables_service

    _tenant_com_conta_agendada(client, dias=1)

    def _explode(*_args, **_kwargs):
        raise RuntimeError("promoção explodiu")

    monkeypatch.setattr(payables_service, "promote_scheduled", _explode)
    cm = _cm_factory(db)
    result = run_sweep(session_factory=cm, tenant_session_factory=cm)

    assert result["scheduled_promoted"] == 0
    assert [e["stage"] for e in result["errors"]] == ["scheduled_promote"]
    # As outras três rodaram: os contadores existem e o sweep não abortou no meio.
    assert result["tenants_checked"] == 1
    assert "funnel_resumed" in result and "notifications_processed" in result


def test_sweep_sem_nada_agendado_e_no_op(client: TestClient, db):
    """Idempotente por construção, como as outras três etapas: sem agendada, o contador é 0."""
    client.post("/auth/register", json=REGISTER)
    cm = _cm_factory(db)
    assert run_sweep(session_factory=cm, tenant_session_factory=cm)["scheduled_promoted"] == 0


# ── Story 8.15 — a MESMA etapa 4 passa a varrer as COBRANÇAS também ───────────────────────────
#
# ⚠️ **Não existe quinta etapa, e isso é o AC.** A pergunta ("já chegou o dia?") é uma só; duas
# etapas seriam a mesma regra em dois lugares — com dois isolamentos de falha, dois contadores e
# duas chances de uma receber a próxima correção e a outra não. O contador `scheduled_promoted`
# passou a ser a **SOMA dos dois lados** (decisão registrada no Dev Agent Record da 8.15).


def _tenant_com_cobranca_agendada(client: TestClient, *, dias: int = 5):
    """Um tenant real com uma cobrança liquidada FORA DO TRILHO para daqui a `dias`.

    Nasce pelo caminho de PRODUÇÃO (a rota `settle-externally` com data futura), nunca plantada
    pelo model: o estado é derivado da data, e montá-lo à mão esconderia a derivação.
    """
    registro = {
        "legal_name": "Recebe Depois SA",
        "document": "11444777000161",
        "slug": "recebedepois",
        "email": "recebedepois@example.com",
        "name": "Rita",
        "password": "senha-bem-comprida",
    }
    token = client.post("/auth/register", json=registro).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    hoje = datetime.now(UTC).date()
    conta = client.post(
        "/bank/accounts",
        json={
            "name": "Itaú PJ",
            "kind": "checking",
            "opening_balance_cents": 100_000_00,
            "opening_balance_is_known": True,
            "opening_date": (hoje - timedelta(days=90)).isoformat(),
        },
        headers=headers,
    ).json()
    charge = client.post(
        "/receivables/charges",
        json={
            "kind": "service",
            "method": "pix",
            "amount_cents": 1_000_00,
            "due_date": hoje.isoformat(),
        },
        headers=headers,
    ).json()
    resp = client.post(
        f"/receivables/charges/{charge['id']}/settle-externally",
        json={
            "bank_account_id": conta["id"],
            "received_on": (hoje + timedelta(days=dias)).isoformat(),
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "scheduled", "pré-condição: a cobrança tinha de nascer agendada"
    return headers, charge


def test_etapa4_promove_a_COBRANCA_agendada_quando_o_dia_chega(client: TestClient, db):
    headers, charge = _tenant_com_cobranca_agendada(client, dias=5)
    cm = _cm_factory(db)

    depois = datetime.now(UTC) + timedelta(days=6)
    result = run_sweep(session_factory=cm, tenant_session_factory=cm, now=depois)

    assert result["scheduled_promoted"] == 1
    assert client.get(
        f"/receivables/charges/{charge['id']}", headers=headers
    ).json()["status"] == "paid"


def test_etapa4_nao_promove_a_cobranca_que_ainda_nao_caiu(client: TestClient, db):
    headers, charge = _tenant_com_cobranca_agendada(client, dias=5)
    cm = _cm_factory(db)

    result = run_sweep(session_factory=cm, tenant_session_factory=cm)

    assert result["scheduled_promoted"] == 0
    assert client.get(
        f"/receivables/charges/{charge['id']}", headers=headers
    ).json()["status"] == "scheduled"


def test_etapa4_conta_os_DOIS_lados_do_dinheiro_no_MESMO_contador(client: TestClient, db):
    """**A prova de que é a mesma etapa, não uma quinta.**

    Um tenant com uma conta a pagar agendada **e** uma cobrança agendada: um sweep só promove as
    duas e o contador vem `2`. Se alguém separar a varredura de `receivables` numa etapa própria,
    este teste continua verde **só se** o contador somado sobreviver — e o teste seguinte, que olha
    o nome do `stage` no isolamento de falha, é o que pega a separação.
    """
    hoje = datetime.now(UTC).date()
    registro = {
        "legal_name": "Dois Lados SA",
        "document": "11444777000161",
        "slug": "doislados",
        "email": "doislados@example.com",
        "name": "Dora",
        "password": "senha-bem-comprida",
    }
    token = client.post("/auth/register", json=registro).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    conta = client.post(
        "/bank/accounts",
        json={
            "name": "Itaú PJ",
            "kind": "checking",
            "opening_balance_cents": 100_000_00,
            "opening_balance_is_known": True,
            "opening_date": (hoje - timedelta(days=90)).isoformat(),
        },
        headers=headers,
    ).json()
    bill = client.post(
        "/payables/bills",
        json={"description": "Aluguel", "amount_cents": 5_000_00, "due_date": hoje.isoformat()},
        headers=headers,
    ).json()
    assert client.post(
        f"/payables/bills/{bill['id']}/pay",
        json={
            "bank_account_id": conta["id"],
            "paid_on": (hoje + timedelta(days=3)).isoformat(),
        },
        headers=headers,
    ).status_code == 200
    charge = client.post(
        "/receivables/charges",
        json={
            "kind": "service",
            "method": "pix",
            "amount_cents": 1_000_00,
            "due_date": hoje.isoformat(),
        },
        headers=headers,
    ).json()
    assert client.post(
        f"/receivables/charges/{charge['id']}/settle-externally",
        json={
            "bank_account_id": conta["id"],
            "received_on": (hoje + timedelta(days=3)).isoformat(),
        },
        headers=headers,
    ).status_code == 200

    cm = _cm_factory(db)
    result = run_sweep(
        session_factory=cm, tenant_session_factory=cm, now=datetime.now(UTC) + timedelta(days=4)
    )

    assert result["scheduled_promoted"] == 2, (
        "o contador da etapa 4 deixou de somar os dois lados do dinheiro (ou a varredura de "
        "`receivables` virou uma quinta etapa com contador próprio)"
    )
    assert client.get(f"/payables/bills/{bill['id']}", headers=headers).json()["status"] == "paid"
    assert client.get(
        f"/receivables/charges/{charge['id']}", headers=headers
    ).json()["status"] == "paid"


def test_falha_na_promocao_de_COBRANCAS_usa_o_MESMO_stage_da_etapa4(
    client: TestClient, db, monkeypatch
):
    """**O gate contra a quinta etapa.** Um erro na varredura de `receivables` entra em `errors`
    com `stage="scheduled_promote"` — o mesmo da 8.14. Um `stage` novo (`"receivables_promote"`,
    por exemplo) significaria que alguém criou a etapa que o AC5 proíbe, e o alerta operacional
    passaria a ter dois nomes para o mesmo incidente.
    """
    from app.modules.receivables import service as receivables_service

    _tenant_com_cobranca_agendada(client, dias=1)

    def _explode(*_args, **_kwargs):
        raise RuntimeError("promoção de cobranças explodiu")

    monkeypatch.setattr(receivables_service, "promote_scheduled", _explode)
    cm = _cm_factory(db)
    result = run_sweep(session_factory=cm, tenant_session_factory=cm)

    assert [e["stage"] for e in result["errors"]] == ["scheduled_promote"]
    assert result["tenants_checked"] == 1
    # E as outras três etapas rodaram: o sweep não abortou no meio.
    assert "funnel_resumed" in result and "notifications_processed" in result


def test_o_sweep_NAO_ganhou_contador_novo(client: TestClient, db):
    """**Teste de AUSÊNCIA.** As chaves do resultado são exatamente as seis + `errors`.

    Um `scheduled_promoted_receivables` ao lado do somado daria **três** números para uma
    informação (os dois mais a soma, que qualquer leitor faz de cabeça) — e a granularidade que tem
    consumidor real já existe na trilha de auditoria (`payable.scheduled_promoted` ×
    `receivable.scheduled_promoted`).

    ⚠️ **[Merge com `main`]** `whatsapp_connections_dropped` entrou na lista — é a 5ª etapa (monitor
    de sessão Evolution), independente da promoção de agendadas e trazida por outra frente de
    trabalho (PRs #62–#69). As duas etapas coexistem: nenhuma substitui a outra.

    ⚠️ **`whatsapp_connections_promoted` entrou depois (fix do transporte silencioso, 2026-08-05)
    e NÃO viola a regra acima.** A regra proíbe dar três números para uma informação — o caso da
    promoção de agendadas, onde os dois lados somam. Aqui os dois contadores são eventos
    OPOSTOS do ciclo de vida da sessão (uma conexão subiu × uma caiu); a soma deles não
    responde pergunta nenhuma, e cada um sozinho responde a sua.

    ⚠️ **`briefings_gerados` entrou na Onda 4 da Vima (etapa 6) pelo MESMO critério.** Responde a
    *"quantos briefings este sweep gerou?"* — pergunta que nenhum dos outros responde, e cuja soma
    com qualquer um deles não produziria número nenhum. Não é uma partição de `notifications_
    processed`: um briefing gerado pode não virar notificação alguma (dia sem novidade, WhatsApp
    desligado), e uma notificação pode não vir de briefing nenhum.
    """
    client.post("/auth/register", json=REGISTER)
    cm = _cm_factory(db)
    result = run_sweep(session_factory=cm, tenant_session_factory=cm)
    assert set(result) == {
        "tenants_checked",
        "funnel_resumed",
        "notifications_processed",
        "whatsapp_media_processed",
        "scheduled_promoted",
        "whatsapp_connections_dropped",
        "whatsapp_connections_promoted",
        "briefings_gerados",
        "errors",
    }


# --- Etapa 5: monitoramento de sessão Evolution ---------------------------------------------

def test_run_sweep_checks_whatsapp_connections(db, monkeypatch):
    """5ª etapa: chama whatsapp_session.service.check_connections por tenant, em sessão
    separada das outras 4 — mesmo padrão de isolamento de falha (IV2) já testado acima."""
    tenant = _make_tenant(db, slug="wa-check")
    db.commit()

    calls: list[str] = []
    monkeypatch.setattr(
        worker.whatsapp_session_service, "check_connections",
        lambda db, *, tenant_id: calls.append(tenant_id) or 0,
    )

    cm = _cm_factory(db)
    result = run_sweep(session_factory=cm, tenant_session_factory=cm)

    assert calls == [tenant.id]
    assert result["whatsapp_connections_dropped"] == 0
    assert result["errors"] == []


def test_run_sweep_isolates_whatsapp_stage_failure(db, monkeypatch):
    # A checagem de conexão lança para o tenant, mas a fila (etapa 2, sessão separada) já
    # tinha rodado antes — o erro da etapa 5 fica isolado em `errors`, sem derrubar o sweep.
    tenant = _make_tenant(db, slug="wa-falha")
    notif_service.enqueue(
        db, tenant_id=tenant.id, channel="whatsapp", recipient="d@e.com", message="oi"
    )
    db.commit()

    def _boom(_db, *, tenant_id):
        raise RuntimeError("checagem de conexão explodiu")

    monkeypatch.setattr(worker.whatsapp_session_service, "check_connections", _boom)

    cm = _cm_factory(db)
    result = run_sweep(session_factory=cm, tenant_session_factory=cm)

    assert result["notifications_processed"] == 1  # etapa 2 rodou normalmente
    assert len(result["errors"]) == 1
    assert result["errors"][0]["stage"] == "whatsapp_connections"
    assert result["errors"][0]["tenant_id"] == tenant.id


# --- Etapa 5 (cont.): promover a conexão que a aba fechada deixou pela metade ----------------
#
# Bug real de produção (2026-08-05): `confirm()` só roda se o FRONTEND vir "connected". Aba
# fechada antes = Evolution conectada, `whatsapp_provider` nulo, todo envio caindo no stub da
# Meta como `logged`, sem erro nenhum. `check_connections` não cobre: ele retorna cedo quando o
# provider ainda não é "evolution", que é exatamente a condição do defeito.

def test_run_sweep_promove_conexao_que_ficou_pela_metade(db, monkeypatch):
    tenant = _make_tenant(db, slug="wa-promove")
    db.commit()

    promovidos: list[str] = []
    monkeypatch.setattr(
        worker.whatsapp_session_service, "promote_pending_connections",
        lambda db, *, tenant_id: promovidos.append(tenant_id) or 1,
    )
    monkeypatch.setattr(
        worker.whatsapp_session_service, "check_connections",
        lambda db, *, tenant_id: 0,
    )

    cm = _cm_factory(db)
    result = run_sweep(session_factory=cm, tenant_session_factory=cm)

    assert promovidos == [tenant.id]
    assert result["whatsapp_connections_promoted"] == 1
    assert result["errors"] == []


def test_falha_ao_promover_nao_derruba_o_sweep(db, monkeypatch):
    """Mesmo isolamento por etapa (IV2) das outras: o erro é acumulado, o sweep segue."""
    _make_tenant(db, slug="wa-promove-falha")
    db.commit()

    def _boom(db, *, tenant_id):
        raise RuntimeError("evolution fora do ar")

    monkeypatch.setattr(worker.whatsapp_session_service, "promote_pending_connections", _boom)

    cm = _cm_factory(db)
    result = run_sweep(session_factory=cm, tenant_session_factory=cm)

    assert [e["stage"] for e in result["errors"]] == ["whatsapp_connections"]
    assert result["tenants_checked"] == 1


# --- Etapa 6: a senha do convite não fica em texto puro para sempre -------------------------

def test_sweep_expurga_a_senha_de_convite_ja_entregue(db):
    from app.modules.notifications.models import Notification
    from app.modules.notifications.service import INVITE_BODY_REDACTED
    from app.modules.whatsapp_templates.models import PURPOSE_STAFF_INVITE

    tenant = _make_tenant(db, slug="wa-purga")
    n = Notification(
        tenant_id=tenant.id, channel="whatsapp", recipient="5511999999999",
        message="Senha temporária: segredo-123", status="sent", purpose=PURPOSE_STAFF_INVITE,
        whatsapp_template_variables=["a", "b", "c", "segredo-123"],
    )
    db.add(n)
    db.commit()

    cm = _cm_factory(db)
    result = run_sweep(session_factory=cm, tenant_session_factory=cm)

    db.refresh(n)
    assert n.message == INVITE_BODY_REDACTED
    assert n.whatsapp_template_variables is None
    assert result["errors"] == []


def test_falha_no_expurgo_nao_derruba_o_sweep(db, monkeypatch):
    _make_tenant(db, slug="wa-purga-falha")
    db.commit()

    def _boom(db, *, tenant_id, now):
        raise RuntimeError("expurgo explodiu")

    monkeypatch.setattr(worker.notifications_service, "purge_invite_secrets", _boom)

    cm = _cm_factory(db)
    result = run_sweep(session_factory=cm, tenant_session_factory=cm)

    assert [e["stage"] for e in result["errors"]] == ["invite_secrets"]
    assert result["tenants_checked"] == 1
