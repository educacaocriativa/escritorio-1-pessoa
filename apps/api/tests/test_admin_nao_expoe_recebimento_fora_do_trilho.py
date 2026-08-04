"""A PROIBIÇÃO NORMATIVA da Story 8.16 (AC4/IV7), em forma de gate — duas varreduras.

> **Nenhuma superfície da plataforma pode ser construída sobre `charges.bank_account_id`.** Nem
> painel do Master, nem agregado em `/admin/*`, nem e-mail, nem cobrança de taxa.
> `platform_earnings` **não é tocado**.

⚠️ **Isto é NORMATIVO, não estilo.** A Story 8.15 deu ao dono uma porta para declarar que recebeu
direto na conta dele — e, no estudo interno, isso é **vazamento de receita da plataforma**. A
"melhoria" natural (*"já que agora a gente SABE, por que não cobrar?"*) é óbvia para quem chegar
depois e não tem nada que a impeça no código. Se a e1p um dia quiser cobrar sobre recebimento fora
da cobrança do e1p, isso é **decisão comercial com consentimento contratual**, nunca consequência
técnica de uma coluna. *"Escrever isto agora custa um parágrafo; descobrir depois custa a relação
com o usuário."*

**Duas varreduras, pelo mesmo motivo que a 8.6 precisou de duas** (AST e comportamento pegam coisas
diferentes):

- **estrutural** — nenhum arquivo de `app/modules/platform/` (o único `APIRouter` com
  `prefix="/admin"`) menciona `bank_account_id`, `settle_off_rail`, `SOURCE_CHARGE` ou
  `bank_transaction`; e nenhum campo dos schemas de saída de lá tem nome derivado disso. Pega a
  intenção antes de ela virar comportamento.
- **comportamental** — com um tenant que TEM recebimentos fora da cobrança do e1p, **toda** resposta
  de `/admin/*` acessível ao Master é comparada, campo a campo, com o mesmo cenário sem eles:
  **idênticas**. Pega o que a varredura de texto não veria (um agregado montado por join dinâmico,
  um campo calculado com outro nome).

**Mutação demonstrada na implementação** (registrada nas Completion Notes da Story 8.16):
acrescentar um campo agregado sobre `charges.bank_account_id` a um schema de `/admin` **reprova** —
o teste não é vácuo.
"""
from __future__ import annotations

import ast
import pathlib
from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.modules.auth.models import Tenant, User
from app.modules.bank.models import KIND_CHECKING, BankAccount
from app.modules.crm.models import Client
from app.modules.receivables import service as receivables_service
from app.modules.receivables.models import Charge
from app.modules.wallet.models import PlatformEarning

PLATFORM_DIR = pathlib.Path(__file__).resolve().parents[1] / "app" / "modules" / "platform"

ADMIN_EMAIL = "master@e1p.com"
ADMIN_PASS = "senha-do-master-123"  # noqa: S105 (senha efêmera do teste)

HOJE = date(2026, 7, 12)

REGISTER = {
    "legal_name": "Escritório Fora do Trilho ME",
    "document": "11444777000161",
    "slug": "foradotrilho",
    "email": "dono@example.com",
    "name": "Dono",
    "password": "uma-senha-bem-grande",
    "address": "Rua Um, 10",
    "phone": "27988887777",
}


# ── (1) Varredura ESTRUTURAL ─────────────────────────────────────────────────────────────────

_TERMOS_PROIBIDOS = (
    "bank_account_id",   # a coluna que a 8.15 criou e que a plataforma não pode enxergar
    "settle_off_rail",   # a porta que a preenche
    "SOURCE_CHARGE",     # o `source` do movimento bancário que ela gera
    "bank_transaction",  # a linha do plano 3
)


def _arquivos_de_platform() -> list[pathlib.Path]:
    return sorted(p for p in PLATFORM_DIR.rglob("*.py") if "__pycache__" not in p.parts)


def test_platform_e_o_unico_router_com_prefixo_admin() -> None:
    """A varredura só vale se `platform/` for mesmo o dono do `/admin`.

    Um teste de ausência precisa de um teste de presença ao lado, senão ele mede o vazio: se um dia
    outro módulo montar um `APIRouter(prefix="/admin")`, esta suíte inteira passaria a olhar para o
    lugar errado — e ficaria verde.
    """
    from app.main import app

    donos = {
        rota.path.split("/")[1]
        for rota in app.routes
        if getattr(rota, "path", "").startswith("/admin/")
    }
    assert donos == {"admin"}
    # E o módulo que os declara é `platform`.
    fontes = {p.read_text(encoding="utf-8") for p in _arquivos_de_platform()}
    assert any('prefix="/admin"' in f for f in fontes)


def test_nenhum_arquivo_de_platform_menciona_o_recebimento_fora_do_trilho() -> None:
    """O equivalente literal do `grep -r "bank_account_id" app/modules/platform/`.

    Inclusive em comentário e docstring, de propósito: o custo é escrever *"a coluna da Story
    8.15"* em vez do nome dela, e o ganho é que **não existe forma de começar a construir a
    superfície proibida que passe daqui** — nem um TODO.
    """
    ofensores: list[str] = []
    for path in _arquivos_de_platform():
        texto = path.read_text(encoding="utf-8")
        ofensores += [
            f"{path.name} → {termo}" for termo in _TERMOS_PROIBIDOS if termo in texto
        ]
    assert not ofensores, (
        f"app/modules/platform passou a conhecer o recebimento fora da cobrança do e1p: "
        f"{ofensores}. Isso é PROIBIDO por decisão de produto (Story 8.16 AC4): cobrar sobre esse "
        "recebimento é decisão comercial com consentimento contratual, nunca consequência técnica "
        "de uma coluna."
    )


def test_nenhum_schema_de_saida_de_admin_tem_campo_derivado_da_coluna() -> None:
    """A mesma proibição no nível do CONTRATO: nome de campo, anotação e default.

    Mais estrito que o `grep` acima em um ponto: pega o campo que tenta disfarçar o conceito num
    nome vizinho (`recebido_por_fora_cents`, `off_rail_total`, `fora_do_trilho`...). Um schema é o
    lugar onde a "melhoria" apareceria primeiro, porque é onde ela fica visível na tela do Master.
    """
    disfarces = ("off_rail", "fora_do_trilho", "por_fora", "extra_trilho", "direto_na_conta")
    ofensores: list[str] = []
    for path in _arquivos_de_platform():
        arvore = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for no in ast.walk(arvore):
            if isinstance(no, ast.AnnAssign) and isinstance(no.target, ast.Name):
                nome = no.target.id.lower()
                if any(d in nome for d in (*disfarces, "bank_account")):
                    ofensores.append(f"{path.name} → {no.target.id}")
    assert not ofensores, (
        f"schema de /admin com campo derivado do recebimento fora da cobrança do e1p: {ofensores}"
    )


# ── (2) Varredura COMPORTAMENTAL ─────────────────────────────────────────────────────────────


@pytest.fixture()
def admin_headers(client: TestClient, db: Session) -> dict[str, str]:
    t = Tenant(slug="platform", legal_name="Plataforma", document="00000000000")
    db.add(t)
    db.flush()
    db.add(
        User(
            tenant_id=t.id,
            email=ADMIN_EMAIL,
            name="Master",
            password_hash=hash_password(ADMIN_PASS),
            role="owner",
            allowed_modules=[],
            is_platform_admin=True,
        )
    )
    db.commit()
    token = client.post(
        "/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _rotas_admin_get(client: TestClient) -> list[str]:
    """**Toda** rota GET de `/admin` sem parâmetro de caminho, descoberta do app real.

    Enumerada dinamicamente, e não escrita à mão: uma rota nova que agregasse a coluna proibida
    entraria automaticamente na comparação. Uma lista fixa envelheceria em silêncio, que é
    exatamente o modo de falha que este arquivo existe para impedir.
    """
    return sorted(
        {
            rota.path
            for rota in client.app.routes
            if getattr(rota, "path", "").startswith("/admin")
            and "GET" in getattr(rota, "methods", set())
            and "{" not in rota.path
        }
    )


def _snapshot_do_master(client: TestClient, headers: dict[str, str], db: Session) -> dict:
    """Tudo o que o Master vê, campo a campo, mais o ledger global da plataforma."""
    visao = {rota: client.get(rota, headers=headers).json() for rota in _rotas_admin_get(client)}
    visao["/wallet/platform-earnings"] = client.get(
        "/wallet/platform-earnings", headers=headers
    ).json()
    # E o ledger direto do banco, sem passar por rota nenhuma: se alguém "cobrasse" o recebimento
    # fora da cobrança do e1p, apareceria aqui mesmo que nenhuma tela ainda o mostrasse.
    visao["_platform_earnings"] = db.execute(
        select(
            func.count(),
            func.coalesce(func.sum(PlatformEarning.gross_cents), 0),
            func.coalesce(func.sum(PlatformEarning.fee_cents), 0),
        )
    ).one()._asdict()
    return visao


def _recebe_fora_do_trilho(db: Session, tenant_id: str, *, quantas: int = 3) -> None:
    """O cenário: uma conta bancária e N cobranças recebidas DIRETO na conta do dono."""
    conta = BankAccount(
        tenant_id=tenant_id,
        name="Itaú PJ",
        kind=KIND_CHECKING,
        opening_balance_cents=1_000_000,
        opening_date=date(2026, 7, 1),
    )
    db.add(conta)
    cliente = Client(tenant_id=tenant_id, name="Cliente Pix", email="pix@example.com")
    db.add(cliente)
    db.flush()
    for i in range(quantas):
        charge = Charge(
            tenant_id=tenant_id,
            client_id=cliente.id,
            description=f"Consultoria {i}",
            amount_cents=140_000,
            due_date=HOJE,
            method="pix",
            kind="service",
        )
        db.add(charge)
        db.flush()
        receivables_service.settle_off_rail(
            db,
            charge_id=charge.id,
            tenant_id=tenant_id,
            actor="dono@example.com",
            bank_account_id=conta.id,
            received_on=HOJE,
        )


def test_o_master_ve_exatamente_a_mesma_coisa_com_e_sem_recebimento_fora_do_trilho(
    client: TestClient, admin_headers, db: Session
) -> None:
    """**A asserção que a proibição existe para produzir.** Idêntico, campo a campo.

    Não *"não vaza o valor"* nem *"não aparece o nome do cliente"*: **idêntico**. Qualquer diferença
    — um contador a mais, uma soma que mudou, um campo novo com zero — significa que a plataforma
    passou a enxergar o dinheiro que entrou na conta do dono, e é aí que a cobrança sobre ele deixa
    de ser decisão comercial e vira consequência técnica.
    """
    tenant_id = client.post("/auth/register", json=REGISTER).json()["user"]["tenant_id"]

    antes = _snapshot_do_master(client, admin_headers, db)
    _recebe_fora_do_trilho(db, tenant_id, quantas=3)
    depois = _snapshot_do_master(client, admin_headers, db)

    # A pré-condição do teste: o cenário existe mesmo (senão a igualdade seria trivial).
    fora_do_trilho = db.scalars(
        select(Charge).where(Charge.bank_account_id.is_not(None))
    ).all()
    assert len(fora_do_trilho) == 3
    assert all(c.transaction_id is None for c in fora_do_trilho), "Invariante do Trilho"

    assert depois == antes, (
        "uma superfície da plataforma mudou por causa de recebimento fora da cobrança do e1p. "
        "Isso é PROIBIDO (Story 8.16 AC4): a coluna existe para a CONFERÊNCIA do dono, não para o "
        "painel do Master."
    )


def test_recebimento_fora_do_trilho_nao_cria_platform_earning(db: Session, client: TestClient):
    """`platform_earnings` **não é tocado** — a metade "plataforma" da Invariante do Trilho.

    Redundante com o snapshot acima **de propósito**: aquele compara agregados, e uma linha de
    valor zero passaria por ele na soma sem passar na contagem. Aqui a asserção é sobre a
    EXISTÊNCIA da linha.
    """
    tenant_id = client.post("/auth/register", json=REGISTER).json()["user"]["tenant_id"]
    _recebe_fora_do_trilho(db, tenant_id, quantas=2)

    assert db.scalar(select(func.count()).select_from(PlatformEarning)) == 0
    from app.modules.wallet.models import Transaction

    assert db.scalar(select(func.count()).select_from(Transaction)) == 0, (
        "recebimento fora do trilho não passa pela Carteira — nenhuma `Transaction`, por design"
    )


def test_a_data_de_hoje_do_cenario_nao_e_futura() -> None:
    """Guarda-trilho do próprio teste: `settle_off_rail` recusa data futura.

    Se `HOJE` ficar no futuro (o arquivo envelhece), o cenário deixaria de ser montado e os dois
    snapshots ficariam iguais **por não haver nada**. Um teste que passa por vacuidade é pior do que
    nenhum teste.
    """
    assert HOJE <= datetime.now(UTC).date(), (
        "atualize `HOJE` neste arquivo: a data do cenário precisa estar no passado"
    )
