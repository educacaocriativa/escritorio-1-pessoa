"""A **Regra dos Planos** como teste executável — não como convenção (Story 8.2, AC8).

Por que este arquivo existe (design `controle-bancario-design.md` §1.3): o bug que originou o Epic
8 foi a Projeção de Caixa tratando `wallet.available_cents` (plano 1 — dinheiro na plataforma) como
se fosse o saldo da conta bancária do usuário (plano 3). Rotular os campos e escrever a regra na
docstring resolve o caso conhecido; não resolve o próximo. Literalmente:

    *"sem (1) o resto degrada por acidente: basta uma story futura importar o módulo errado para
    recriar o bug numa forma nova."*

Por isso o design classifica esta regra como **gate**, e por isso ela vive aqui, em varredura
estática (mesmo estilo de `tests/test_tenancy_guard.py`), e não num comentário que ninguém lê.

**A regra**, em três partes:
  (a) nenhum cálculo de saldo bancário lê `transactions`, nenhum cálculo de saldo de carteira lê
      `bank_transactions`, e as duas somas **nunca** ocupam o mesmo campo numérico;
  (b) `app.modules.bank` **pode** importar `app.modules.wallet`; `app.modules.wallet` **nunca**
      importa `app.modules.bank` — o único ponto de contato legítimo (o payout da Carteira, Onda 6)
      vive do lado `bank` e se comunica por `core/events` (design §6.6);
  (c) todo campo de API que carrega saldo declara a procedência num irmão `*_origem`
      (`app.core.money_planes`).

**Os testes da regra, e onde cada um mora:**
  1. `test_wallet_nao_importa_bank`        — aqui (parte b, direção proibida)
  2. `test_bank_nao_referencia_transaction`— aqui (parte b, mais estrito que o design de propósito)
  3. `test_bank_balance_ignora_wallet`     — aqui (parte a, plano 1 → plano 3)
  4. `test_wallet_summary_ignora_bank`     — aqui (parte a, plano 3 → plano 1)
  5. `test_projecao_declara_origem_do_saldo_inicial` — **NÃO está aqui**: é da Story 8.1 e vive em
     `tests/test_financial_intelligence_projection.py` (parte c). Duplicá-lo criaria dois testes de
     mesmo nome em arquivos diferentes; este comentário existe para o leitor achar o quinto.
"""
from __future__ import annotations

import ast
import pathlib

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.modules.bank import service as bank_service
from app.modules.wallet import service as wallet_service
from app.modules.wallet.models import STATUS_AVAILABLE, STATUS_PENDING, Transaction

APP_DIR = pathlib.Path(__file__).resolve().parents[1] / "app"
WALLET_DIR = APP_DIR / "modules" / "wallet"
BANK_DIR = APP_DIR / "modules" / "bank"


# ── Varredura estática (parte b da regra) ─────────────────────────────────────────────────────


def _python_files(directory: pathlib.Path) -> list[pathlib.Path]:
    files = sorted(p for p in directory.rglob("*.py") if "__pycache__" not in p.parts)
    assert files, f"Nenhum .py encontrado em {directory} — teste desatualizado?"
    return files


def _imported_modules(path: pathlib.Path) -> list[str]:
    """Módulos importados por um arquivo, via AST (não por texto).

    AST em vez de `grep` porque prosa em docstring **precisa** poder citar o módulo proibido (esta
    suíte inteira fala de `app.modules.bank` o tempo todo) sem quebrar o teste. Imports RELATIVOS
    são devolvidos com um prefixo `.` para que o chamador os inspecione — o projeto usa imports
    absolutos (Constitution, Artigo VI), então um relativo aqui já é anomalia por si só.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            prefix = "." * node.level
            modules.append(f"{prefix}{node.module or ''}")
    return modules


def test_wallet_nao_importa_bank():
    """`app.modules.wallet` NUNCA importa `app.modules.bank` (Regra dos Planos §1.3b).

    Este é o teste de maior valor da Story 8.2: é a única defesa **permanente** contra a
    reintrodução do bug original numa forma nova, e custa ~20 linhas.

    **Sem allowlist, e isso é deliberado.** O ponto de contato entre os planos 1 e 3 (o payout da
    Carteira, Onda 6) foi desenhado para viver do lado `bank`, publicando/consumindo `core/events`
    (design §6.6) — logo **não existe** exceção legítima nesta direção. Se uma story futura
    "precisar" de uma, o que ela precisa de verdade é rever o desenho do ponto de contato.
    """
    offenders: list[str] = []
    for path in _python_files(WALLET_DIR):
        for module in _imported_modules(path):
            if module.startswith("app.modules.bank") or module.lstrip(".").startswith("bank"):
                offenders.append(f"{path.relative_to(APP_DIR)} → {module}")

    assert not offenders, (
        "Regra dos Planos §1.3b VIOLADA: app/modules/wallet importa app/modules/bank — a direção "
        f"proibida. Ocorrências: {offenders}. O ponto de contato entre a Carteira (plano 1) e o "
        "banco (plano 3) é o payout da Onda 6, e ele vive do lado `bank`, via core/events. "
        "Importar `bank` de dentro de `wallet` é o caminho por onde o bug que originou o Epic 8 "
        "volta numa forma nova."
    )


def test_wallet_nao_importa_bank_tambem_por_texto_cru():
    """O equivalente literal do `grep -r "from app.modules.bank" app/modules/wallet/` (epic §5).

    Redundante com o teste por AST **de propósito**: se um dia alguém trocar o import por algo que
    o AST não pega (um `importlib.import_module("app.modules.bank")`, um `__import__` montado por
    string), o grep cru ainda pega. Custa duas linhas e cobre a fuga mais óbvia.
    """
    offenders = [
        str(path.relative_to(APP_DIR))
        for path in _python_files(WALLET_DIR)
        if "app.modules.bank" in path.read_text(encoding="utf-8")
    ]
    assert not offenders, (
        f"Menção a `app.modules.bank` dentro de app/modules/wallet: {offenders}. "
        "Ver test_wallet_nao_importa_bank."
    )


def test_bank_nao_referencia_transaction():
    """`app.modules.bank` não referencia `Transaction`/`wallet.models` — **hoje**.

    ⚠️ Este teste é **mais estrito que o design de propósito**. A Regra dos Planos §1.3b *permite*
    `bank → wallet`; o que ela proíbe é o contrário. Mas o ponto de contato da Onda 6 foi desenhado
    via `core/events` (design §6.6) e **não precisa** do modelo da Carteira, então hoje a referência
    correta é: nenhuma. Manter o teste apertado enquanto a resposta certa é "nenhuma" é o que faz
    dele um sinal — um teste que já permite o que ninguém usa não avisa nada quando alguém começar
    a usar.

    Se uma story futura precisar legitimamente do símbolo, ela **atualiza este teste com
    justificativa escrita** (mesmo padrão de allowlist do `test_tenancy_guard.py`) — nunca o apaga.
    """
    offenders: list[str] = []
    for path in _python_files(BANK_DIR):
        for module in _imported_modules(path):
            if module.startswith("app.modules.wallet") or module.lstrip(".").startswith("wallet"):
                offenders.append(f"{path.relative_to(APP_DIR)} → import {module}")
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id == "Transaction":
                offenders.append(f"{path.relative_to(APP_DIR)} → símbolo Transaction")
            elif isinstance(node, ast.Attribute) and node.attr == "Transaction":
                offenders.append(f"{path.relative_to(APP_DIR)} → atributo .Transaction")

    assert not offenders, (
        "app/modules/bank passou a referenciar a Carteira (plano 1). Isto NÃO é proibido pelo "
        f"design (§1.3b permite bank → wallet), mas hoje não deveria existir: {offenders}. Se o "
        "uso for legítimo, atualize ESTE teste com a justificativa escrita — não o apague."
    )


# ── Os planos não se cruzam em RUNTIME (parte a da regra) ─────────────────────────────────────

REGISTER = {
    "legal_name": "Planos Separados ME",
    "document": "11444777000161",
    "slug": "planos",
    "email": "planos@example.com",
    "name": "Petra",
    "password": "uma-senha-bem-grande",
}


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _tenant_id(client: TestClient, headers: dict[str, str]) -> str:
    return client.get("/auth/me", headers=headers).json()["user"]["tenant_id"]


def _bank_account(client: TestClient, headers: dict[str, str], *, opening: int) -> dict:
    resp = client.post(
        "/bank/accounts",
        json={
            "name": "Itaú PJ",
            "kind": "checking",
            "opening_balance_cents": opening,
            "opening_date": "2026-07-01",
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_bank_balance_ignora_wallet(client: TestClient, headers, db: Session):
    """Dinheiro que entra na Carteira (plano 1) não muda o saldo bancário (plano 3) em 1 centavo.

    Inclui uma transação `available` — a exata que o bug original somava como se fosse saldo de
    banco.
    """
    account = _bank_account(client, headers, opening=250_000)
    tenant_id = _tenant_id(client, headers)
    antes = client.get(f"/bank/accounts/{account['id']}/balance", headers=headers).json()
    assert antes["saldo_derivado_cents"] == 250_000

    db.add_all(
        [
            Transaction(
                tenant_id=tenant_id, kind="service", method="pix", gross_cents=1_000_000,
                platform_fee_cents=300_000, net_cents=700_000, status=STATUS_AVAILABLE,
            ),
            Transaction(
                tenant_id=tenant_id, kind="product", method="card", gross_cents=500_000,
                platform_fee_cents=200_000, net_cents=300_000, status=STATUS_PENDING,
            ),
        ]
    )
    db.commit()
    assert wallet_service.wallet_summary(db)["available_cents"] == 700_000, (
        "pré-condição do teste falhou: a Carteira deveria ter recebido o dinheiro"
    )

    depois = client.get(f"/bank/accounts/{account['id']}/balance", headers=headers).json()
    assert depois["saldo_derivado_cents"] == 250_000, (
        "Regra dos Planos §1.3a VIOLADA: o saldo bancário se moveu por causa de uma venda na "
        "Carteira. O saldo do plano 3 é `opening_balance_cents + SUM(bank_transactions)` e nada "
        "mais — `transactions` não entra nessa conta em hipótese nenhuma."
    )
    assert depois == antes
    # E pelo service, sem passar pela camada HTTP (o cálculo é que precisa estar limpo).
    assert bank_service.derived_balance(db, bank_account_id=account["id"]) == 250_000


def test_wallet_summary_ignora_bank(client: TestClient, headers, db: Session):
    """O recíproco: cadastrar conta bancária com saldo alto não move a Carteira em 1 centavo."""
    tenant_id = _tenant_id(client, headers)
    db.add(
        Transaction(
            tenant_id=tenant_id, kind="service", method="pix", gross_cents=100_000,
            platform_fee_cents=30_000, net_cents=70_000, status=STATUS_AVAILABLE,
        )
    )
    db.commit()
    antes = wallet_service.wallet_summary(db)

    _bank_account(client, headers, opening=99_999_999)

    depois = wallet_service.wallet_summary(db)
    assert depois == antes, (
        "Regra dos Planos §1.3a VIOLADA: o resumo da Carteira mudou depois de cadastrar uma conta "
        f"bancária. antes={antes} depois={depois}"
    )
    # Campo a campo, para que a mensagem diga QUAL campo vazou se um dia falhar.
    for field in ("available_cents", "pending_cents", "withdrawn_cents", "gross_total_cents",
                  "fees_total_cents"):
        assert depois[field] == antes[field], f"campo contaminado pelo plano 3: {field}"


def test_saldos_dos_dois_planos_nao_ocupam_o_mesmo_campo(client: TestClient, headers):
    """Parte (a), fim da frase: as duas somas nunca ocupam o mesmo campo numérico.

    A Carteira devolve `available_cents` (sem `*_origem`, porque nunca foi ambígua: é o plano 1 por
    definição); o banco devolve `saldo_derivado_cents` **com** `saldo_derivado_origem='banco'`. São
    nomes diferentes com procedência declarada — é isso que impede o `saldo_inicial` da Projeção de
    voltar a receber o número errado sem ninguém perceber.
    """
    from app.core.money_planes import ORIGEM_BANCO, ORIGENS

    account = _bank_account(client, headers, opening=1_234)
    assert account["saldo_derivado_origem"] == ORIGEM_BANCO
    assert account["saldo_derivado_origem"] in ORIGENS
    assert "available_cents" not in account
    assert "saldo_derivado_cents" not in client.get("/wallet/summary", headers=headers).json()
