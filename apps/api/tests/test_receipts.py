"""Testes da bandeja de comprovantes (Contas a Pagar).

⚠️ **Adaptado pela Story 8.12, não reescrito** (IV1). A baixa passou a gerar o movimento bancário e
a exigir a conta de onde o dinheiro saiu; a bandeja usa a conta **primária** como substituto
declarado até a Story 8.13 acrescentar o campo. Nenhum teste foi apagado — inclusive o que a própria
suíte chama de *"guarda de regressão do refactor apply_paid/mark_paid"*.
"""
import io
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

REGISTER = {
    "legal_name": "Recibo Co",
    "document": "12345678000195",
    "slug": "reciboco",
    "email": "recibo@example.com",
    "name": "Recibo",
    "password": "senha-bem-comprida",
}

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64

# Abertura bem no passado: o piso da baixa é `paid_on > opening_date`, e as contas deste arquivo
# são pagas com `paid_on` = hoje.
ABERTURA = date(2026, 1, 1)


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def conta_primaria(client: TestClient, headers) -> str:
    """A conta bancária PRIMÁRIA do tenant. **Autouse desde a Story 8.12, e por um motivo.**

    A bandeja não tem (ainda) campo para informar a conta — quem o acrescenta é a Story 8.13. Até
    lá, `receipts._conta_da_bandeja` usa a **primária** como substituto declarado
    (`[SUPOSIÇÃO DO @SM]` + `TODO(8.13)`), e sem ela toda baixa por comprovante devolveria o 409
    acionável. Autouse porque o tenant REAL que usa esta porta tem conta cadastrada — o cenário
    "sem conta nenhuma" é exercido de propósito, e só, em
    `test_bandeja_sem_conta_primaria_devolve_409_acionavel`.
    """
    resp = client.post(
        "/bank/accounts",
        json={
            "name": "Itaú PJ",
            "kind": "checking",
            "opening_balance_cents": 500_000,
            "opening_date": ABERTURA.isoformat(),
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _pay(client: TestClient, headers, bill_id: str, conta: str, paid_on: str | None = None):
    """`POST /bills/{id}/pay` com o corpo obrigatório da Story 8.12 (AC11)."""
    body = {"bank_account_id": conta, "paid_on": paid_on or datetime.now(UTC).date().isoformat()}
    return client.post(f"/payables/bills/{bill_id}/pay", json=body, headers=headers)


def _upload(client: TestClient, headers, *, name="comprovante.png", ctype="image/png", data=PNG):
    return client.post(
        "/payables/receipts",
        files={"file": (name, data, ctype)},
        headers=headers,
    )


def test_upload_cria_item_na_bandeja(client: TestClient, headers):
    resp = _upload(client, headers)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["filename"] == "comprovante.png"
    assert body["content_type"] == "image/png"
    assert body["size"] == len(PNG)

    bandeja = client.get("/payables/receipts", headers=headers).json()
    assert [i["id"] for i in bandeja] == [body["id"]]


def test_upload_recusa_tipo_nao_permitido(client: TestClient, headers):
    resp = _upload(client, headers, name="audio.ogg", ctype="audio/ogg", data=b"OggS____")
    assert resp.status_code == 415


def test_upload_recusa_arquivo_vazio(client: TestClient, headers):
    resp = _upload(client, headers, data=b"")
    assert resp.status_code == 422


def test_upload_recusa_acima_de_10mb(client: TestClient, headers):
    resp = _upload(client, headers, data=b"0" * (10 * 1024 * 1024 + 1))
    assert resp.status_code == 413


def test_bandeja_tem_teto_de_30(client: TestClient, headers):
    for _ in range(30):
        assert _upload(client, headers).status_code == 201
    resp = _upload(client, headers)
    assert resp.status_code == 409
    assert "bandeja" in resp.json()["detail"].lower()


def test_descartar_remove_da_bandeja(client: TestClient, headers):
    rid = _upload(client, headers).json()["id"]
    assert client.delete(f"/payables/receipts/{rid}", headers=headers).status_code == 204
    assert client.get("/payables/receipts", headers=headers).json() == []


def test_descartar_id_inexistente_da_404(client: TestClient, headers):
    assert client.delete("/payables/receipts/nao-existe", headers=headers).status_code == 404


def test_descartar_anexado_a_conta_da_409(client: TestClient, headers):
    """Um comprovante já linked a uma conta (owner_type != receipt_inbox) não pode ser descartado
    da bandeja — deve retornar 409."""
    # Upload um attachment via /attachments com owner_type="payable"
    resp = client.post(
        "/attachments",
        data={"owner_type": "payable", "owner_id": "bill-123", "label": "comprovante"},
        files={"file": ("comprovante.png", io.BytesIO(PNG), "image/png")},
        headers=headers,
    )
    assert resp.status_code == 201
    att_id = resp.json()["id"]

    # Tenta descartar via /payables/receipts (que espera owner_type=receipt_inbox)
    resp = client.delete(f"/payables/receipts/{att_id}", headers=headers)
    assert resp.status_code == 409
    assert "anexado" in resp.json()["detail"].lower()


def _bill(client: TestClient, headers, **over):
    base = {
        "description": "Energia",
        "category": "Estrutura",
        "supplier": "Copel",
        "amount_cents": 30000,
        "due_date": "2099-01-10",
    }
    return client.post("/payables/bills", json={**base, **over}, headers=headers).json()


def test_candidates_lista_abertas_por_vencimento(client: TestClient, headers):
    _bill(client, headers, description="Depois", due_date="2099-03-01")
    _bill(client, headers, description="Antes", due_date="2099-01-01")
    itens = client.get("/payables/receipts/candidates", headers=headers).json()
    assert [i["description"] for i in itens] == ["Antes", "Depois"]


def test_candidates_inclui_pagas_recentes_depois_das_abertas(
    client: TestClient, headers, conta_primaria
):
    aberta = _bill(client, headers, description="Aberta", due_date="2099-02-02")
    paga = _bill(client, headers, description="Paga", due_date="2099-02-03")
    _pay(client, headers, paga["id"], conta_primaria)
    itens = client.get("/payables/receipts/candidates", headers=headers).json()
    assert [i["description"] for i in itens] == ["Aberta", "Paga"]
    assert itens[0]["id"] == aberta["id"]


def test_candidates_nao_lista_canceladas(client: TestClient, headers):
    b = _bill(client, headers, description="Cancelada")
    client.post(f"/payables/bills/{b['id']}/cancel", headers=headers)
    itens = client.get("/payables/receipts/candidates", headers=headers).json()
    assert [i["description"] for i in itens] == []


def test_candidates_busca_por_descricao_e_fornecedor(client: TestClient, headers):
    _bill(client, headers, description="Aluguel sala", supplier="Imobiliária X")
    _bill(client, headers, description="Energia", supplier="Copel")

    por_descricao = client.get("/payables/receipts/candidates?q=aluguel", headers=headers).json()
    assert [i["description"] for i in por_descricao] == ["Aluguel sala"]

    por_fornecedor = client.get("/payables/receipts/candidates?q=copel", headers=headers).json()
    assert [i["description"] for i in por_fornecedor] == ["Energia"]


def test_candidates_respeita_janela_de_30_dias(
    client: TestClient, headers, db: Session, conta_primaria
):
    """Verifica que contas pagas há mais de 30 dias são excluídas,
    e contas pagas dentro de 30 dias são incluídas."""
    from app.modules.payables.models import Payable

    # Criar e pagar uma conta
    paga_antiga = _bill(client, headers, description="Paga há 40 dias", due_date="2099-01-01")
    _pay(client, headers, paga_antiga["id"], conta_primaria)

    # Criar e pagar outra conta
    paga_recente = _bill(client, headers, description="Paga há 29 dias", due_date="2099-01-02")
    _pay(client, headers, paga_recente["id"], conta_primaria)

    # Manipular diretamente os paid_at via db para ter controle preciso
    cutoff = datetime.now(UTC) - timedelta(days=30)
    db_antiga = db.get(Payable, paga_antiga["id"])
    db_recente = db.get(Payable, paga_recente["id"])

    if db_antiga:
        db_antiga.paid_at = cutoff - timedelta(days=10)  # 40 dias atrás
    if db_recente:
        db_recente.paid_at = cutoff + timedelta(days=1)  # 29 dias atrás

    db.commit()

    # Verificar que apenas a recente aparece
    itens = client.get("/payables/receipts/candidates", headers=headers).json()
    assert [i["description"] for i in itens] == ["Paga há 29 dias"]


def test_candidates_limita_a_100_itens(client: TestClient, headers):
    """Verifica que mesmo com mais de 100 contas abertas, apenas 100 são retornadas."""
    # Criar 101 contas abertas
    for i in range(101):
        _bill(client, headers, description=f"Bill {i:03d}", due_date="2099-12-31")

    # Verificar que apenas 100 são retornadas
    itens = client.get("/payables/receipts/candidates", headers=headers).json()
    assert len(itens) == 100


def _link(client: TestClient, headers, rid: str, bill_id: str, mark_paid: bool = True):
    return client.post(
        f"/payables/receipts/{rid}/link",
        json={"bill_id": bill_id, "mark_paid": mark_paid},
        headers=headers,
    )


def test_link_anexa_e_da_baixa(client: TestClient, headers):
    b = _bill(client, headers)
    rid = _upload(client, headers).json()["id"]

    resp = _link(client, headers, rid, b["id"])
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "paid"
    assert resp.json()["paid_at"] is not None

    # saiu da bandeja e virou anexo da conta, com o label certo
    assert client.get("/payables/receipts", headers=headers).json() == []
    anexos = client.get(
        f"/attachments?owner_type=payable&owner_id={b['id']}", headers=headers
    ).json()
    assert [a["label"] for a in anexos] == ["comprovante"]


def test_link_sem_mark_paid_nao_muda_status(client: TestClient, headers):
    b = _bill(client, headers)
    rid = _upload(client, headers).json()["id"]
    resp = _link(client, headers, rid, b["id"], mark_paid=False)
    assert resp.status_code == 200
    assert resp.json()["status"] == "open"
    assert resp.json()["paid_at"] is None


def test_link_em_conta_ja_paga_nao_altera_paid_at(client: TestClient, headers, conta_primaria):
    b = _bill(client, headers)
    paga = _pay(client, headers, b["id"], conta_primaria).json()
    rid = _upload(client, headers).json()["id"]

    resp = _link(client, headers, rid, b["id"], mark_paid=True)
    assert resp.status_code == 200
    assert resp.json()["paid_at"] == paga["paid_at"]  # baixa preservada, não re-datada


def test_link_em_conta_cancelada_falha_e_mantem_na_bandeja(client: TestClient, headers):
    b = _bill(client, headers)
    client.post(f"/payables/bills/{b['id']}/cancel", headers=headers)
    rid = _upload(client, headers).json()["id"]

    resp = _link(client, headers, rid, b["id"])
    assert resp.status_code == 409
    # nada foi gravado: o comprovante continua na bandeja
    assert [i["id"] for i in client.get("/payables/receipts", headers=headers).json()] == [rid]


def test_link_duas_vezes_da_409(client: TestClient, headers):
    b = _bill(client, headers)
    rid = _upload(client, headers).json()["id"]
    assert _link(client, headers, rid, b["id"]).status_code == 200
    assert _link(client, headers, rid, b["id"]).status_code == 409


def test_link_em_conta_inexistente_da_404(client: TestClient, headers):
    rid = _upload(client, headers).json()["id"]
    assert _link(client, headers, rid, "nao-existe").status_code == 404


def test_mark_paid_continua_funcionando_apos_refactor(client: TestClient, headers, conta_primaria):
    """Guarda de regressão do refactor apply_paid/mark_paid: a rota antiga não muda."""
    b = _bill(client, headers)
    paga = _pay(client, headers, b["id"], conta_primaria).json()
    assert paga["status"] == "paid" and paga["paid_at"] is not None
    eventos = [
        e for e in client.get("/agenda/events?limit=500", headers=headers).json()
        if e["external_ref"] == b["id"]
    ]
    assert [e["status"] for e in eventos] == ["done"]


def _new_bill_payload(**over):
    base = {
        "description": "Estacionamento",
        "category": "Geral",
        "supplier": "Shopping",
        "amount_cents": 4500,
        "due_date": "2099-05-05",
        "mark_paid": True,
    }
    return {**base, **over}


def test_new_bill_cria_conta_paga_com_o_anexo(client: TestClient, headers):
    rid = _upload(client, headers).json()["id"]
    resp = client.post(
        f"/payables/receipts/{rid}/new-bill", json=_new_bill_payload(), headers=headers
    )
    assert resp.status_code == 201, resp.text
    b = resp.json()
    assert b["description"] == "Estacionamento"
    assert b["status"] == "paid"

    assert client.get("/payables/receipts", headers=headers).json() == []
    anexos = client.get(
        f"/attachments?owner_type=payable&owner_id={b['id']}", headers=headers
    ).json()
    assert [a["label"] for a in anexos] == ["comprovante"]


def test_new_bill_sem_mark_paid_nasce_aberta(client: TestClient, headers):
    rid = _upload(client, headers).json()["id"]
    b = client.post(
        f"/payables/receipts/{rid}/new-bill",
        json=_new_bill_payload(mark_paid=False),
        headers=headers,
    ).json()
    assert b["status"] == "open"


def test_new_bill_injeta_evento_na_agenda(client: TestClient, headers):
    rid = _upload(client, headers).json()["id"]
    b = client.post(
        f"/payables/receipts/{rid}/new-bill", json=_new_bill_payload(), headers=headers
    ).json()
    eventos = [
        e for e in client.get("/agenda/events?limit=500", headers=headers).json()
        if e["external_ref"] == b["id"]
    ]
    assert len(eventos) == 1
    assert eventos[0]["kind"] == "cobranca_pagar"


def test_new_bill_recusa_valor_zero(client: TestClient, headers):
    rid = _upload(client, headers).json()["id"]
    resp = client.post(
        f"/payables/receipts/{rid}/new-bill",
        json=_new_bill_payload(amount_cents=0),
        headers=headers,
    )
    assert resp.status_code == 422  # PayableCreate exige amount_cents > 0


def test_create_bill_continua_funcionando_apos_refactor(client: TestClient, headers):
    """Guarda de regressão do refactor build_payable/create_payable."""
    b = _bill(client, headers, due_date="2099-06-01", recurrence="monthly", recurrence_count=3)
    todas = client.get("/payables/bills", headers=headers).json()
    assert len([x for x in todas if x["recurrence_group"] == b["recurrence_group"]]) == 3


def _device_token(db: Session, headers) -> tuple[str, str, str]:
    """Cria um token de dispositivo direto pelo serviço (a rota HTTP só vem na Task 7).

    Usa a fixture `db` — a MESMA sessão SQLite que a fixture `client` usa — em vez de abrir
    outra: o token precisa estar visível para a requisição que virá logo em seguida.

    Devolve (token_cru, user_id, tenant_id).
    """
    from app.modules.auth.models import User
    from app.modules.device_tokens import service as dt_service

    user = db.query(User).filter(User.email == REGISTER["email"]).one()
    _, raw = dt_service.create_token(
        db, tenant_id=user.tenant_id, user_id=user.id, name="iPhone de teste"
    )
    return raw, user.id, user.tenant_id


def test_upload_aceita_token_de_dispositivo(client: TestClient, db: Session, headers):
    raw, _, _ = _device_token(db, headers)
    resp = client.post(
        "/payables/receipts",
        files={"file": ("comp.png", PNG, "image/png")},
        headers={"X-E1P-Device-Token": raw},
    )
    assert resp.status_code == 201, resp.text
    # o arquivo caiu na bandeja do MESMO usuário, visível pela sessão web
    assert [i["id"] for i in client.get("/payables/receipts", headers=headers).json()] == [
        resp.json()["id"]
    ]


def test_upload_recusa_token_de_dispositivo_invalido(client: TestClient):
    resp = client.post(
        "/payables/receipts",
        files={"file": ("comp.png", PNG, "image/png")},
        headers={"X-E1P-Device-Token": "token-que-nao-existe"},
    )
    assert resp.status_code == 401


def test_upload_sem_credencial_nenhuma_da_401(client: TestClient):
    resp = client.post("/payables/receipts", files={"file": ("comp.png", PNG, "image/png")})
    assert resp.status_code == 401


def test_token_de_dispositivo_escreve_sempre_no_tenant_do_proprio_token(
    client: TestClient, db: Session, headers
):
    """O tenant_id do anexo vem do TOKEN, nunca do corpo da requisição — por isso um token de
    A não consegue escrever em B, mesmo forjando parâmetros. (O outro lado do isolamento — a
    LEITURA cross-tenant no `link` — depende de RLS e só é validável no Postgres: ver
    docs/CHECKLIST-COMPROVANTE-MOBILE.md.)"""
    from app.modules.attachments.models import Attachment

    raw, user_id, tenant_id = _device_token(db, headers)
    rid = client.post(
        "/payables/receipts",
        files={"file": ("comp.png", PNG, "image/png")},
        headers={"X-E1P-Device-Token": raw},
    ).json()["id"]

    att = db.get(Attachment, rid)
    assert att.tenant_id == tenant_id
    assert att.owner_id == user_id


def test_link_continua_exigindo_sessao_web(client: TestClient, db: Session, headers):
    """O token de dispositivo NÃO autoriza vincular — escopo travado no upload."""
    b = _bill(client, headers)
    raw, _, _ = _device_token(db, headers)
    rid = _upload(client, headers).json()["id"]
    resp = client.post(
        f"/payables/receipts/{rid}/link",
        json={"bill_id": b["id"], "mark_paid": True},
        headers={"X-E1P-Device-Token": raw},
    )
    assert resp.status_code == 401  # link exige Bearer, não conhece o header do dispositivo
