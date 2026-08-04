"""A guarda de contagem dupla + o manual curado (Story 8.17).

**O que esta story impede, dito uma vez:** hoje o formulário manual é a porta **primária** do
módulo bancário e parece o jeito de registrar qualquer coisa — inclusive um pagamento que já tem
conta a pagar. Registrado nos dois lugares, o mesmo dinheiro derruba o saldo **duas vezes**, e a
divergência resultante **parece um achado real**. É o pior modo de falha da onda: o erro não se
anuncia como erro, ele se anuncia como o produto funcionando.

Cobre:
- **AC1/AC3** o vocabulário de `operation_nature` é SUGERIDO — texto livre passa, a API não impõe
  a lista, e a lista do backend bate com a da UI;
- **AC2** zero migration (a coluna, os dois schemas e o tipo TS já existiam);
- **AC4** saída manual legítima (a tarifa de R$ 2,90) passa em silêncio, sem `payable` nenhum;
- **AC5** o 409 **com escolha**, no formato da 8.12; `confirmar_avulso=true` insiste; as bordas
  (±3 dias dentro, ±4 fora; 1 centavo de diferença não casa; entrada nunca dispara); o desempate;
  e `update_transaction` **sem** a guarda;
- **AC6** o fail-closed **no BOOT** (a app não sobe sem o probe) e a segunda guarda no request;
- **AC7** movimento legado com `operation_nature = NULL` continua legal;
- **AC9/IV3** `operation_nature` não move o saldo derivado em 1 centavo.

O gate estrutural que sustenta o AC6 (`bank` não nomeia a entidade de negócio, nem sob
`TYPE_CHECKING`, nem em nome de campo) vive em `test_money_planes.py`, junto com o resto da Regra
dos Planos — não aqui, para não haver dois lugares onde a mesma proibição é afirmada.

RLS/cross-tenant não é exercido aqui (SQLite — ver `conftest.py`): a afirmação *"a guarda nunca
enxerga conta a pagar de outro tenant"* (IV5) só o Postgres real prova, e ela mora em
`test_bank_rls.py` (`rls_e2e`).
"""
from __future__ import annotations

import ast
import pathlib
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app import main as app_main
from app.modules.bank import service as bank_service
from app.modules.bank.models import KIND_CHECKING, OPERATION_NATURES, BankTransaction
from app.modules.bank.schemas import BankTransactionCreate
from app.modules.payables.models import ALL_STATUSES
from app.modules.payables.service import _ESTADOS_CANDIDATOS

REGISTER = {
    "legal_name": "Contagem Dupla ME",
    "document": "11444777000161",
    "slug": "contagemdupla",
    "email": "contagem@example.com",
    "name": "Dulce",
    "password": "uma-senha-bem-grande",
}

# Todas as datas são do passado real: `_validate_posted_at` recusa `posted_at` futuro e
# `_valida_data_de_baixa` recusa baixa futura — o mesmo ancoramento do resto da suíte.
OPENING = date(2026, 7, 1)
OPENING_CENTS = 1_500_00
DIA = date(2026, 7, 12)
VALOR = 380_00


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def account(client: TestClient, headers) -> dict:
    resp = client.post(
        "/bank/accounts",
        json={
            "name": "Itaú PJ",
            "kind": KIND_CHECKING,
            "opening_balance_cents": OPENING_CENTS,
            "opening_date": OPENING.isoformat(),
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _payable(
    client: TestClient,
    headers,
    *,
    amount_cents: int = VALOR,
    due_date: date = DIA,
    supplier: str = "Enel",
) -> dict:
    resp = client.post(
        "/payables/bills",
        json={
            "description": "Energia",
            "supplier": supplier,
            "amount_cents": amount_cents,
            "due_date": due_date.isoformat(),
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _lancar(
    client: TestClient,
    headers,
    account_id: str,
    *,
    amount_cents: int,
    posted_at: date = DIA,
    **extra,
):
    payload = {
        "posted_at": posted_at.isoformat(),
        "amount_cents": amount_cents,
        "description": "Pagamento",
    }
    payload.update(extra)
    return client.post(
        f"/bank/accounts/{account_id}/transactions", json=payload, headers=headers
    )


# ── AC5 — o 409 com ESCOLHA ──────────────────────────────────────────────────────────────────


def test_saida_manual_casando_com_conta_a_pagar_devolve_409_acionavel(
    client: TestClient, headers, account
):
    """O cenário inteiro da story: mesma quantia, mesma janela, saída manual → **409 com escolha**.

    Não é bloqueio mudo: o payload nomeia a ação (`baixar_payable`), entrega o id para a tela poder
    levar o usuário ao fluxo da baixa — onde *o movimento nasce sozinho* — e traz a frase pronta.
    """
    p = _payable(client, headers)

    resp = _lancar(client, headers, account["id"], amount_cents=-VALOR)

    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    # ⚠️ `acao` e `payable_id` DENTRO de `detail` — o mesmo formato que a 8.12 estabeleceu com
    # `cadastrar_conta`. Dois formatos de erro acionável obrigariam a UI a saber, por rota, onde
    # procurar o `acao` (correção do @po na v0.2 desta story).
    assert detail["acao"] == "baixar_payable"
    assert detail["payable_id"] == p["id"]
    assert "R$ 380,00" in detail["mensagem"]
    assert "12/07" in detail["mensagem"]
    assert "Enel" in detail["mensagem"]
    # A escolha é OFERECIDA na frase — as duas saídas, nenhuma pré-selecionada.
    assert "outro pagamento" in detail["mensagem"]
    # E nada foi escrito: a guarda roda ANTES de qualquer escrita.
    assert client.get("/bank/transactions", headers=headers).json() == []


def test_confirmar_avulso_insiste_e_o_movimento_nasce(client: TestClient, headers, account):
    """*"É outro pagamento mesmo"* — o usuário repete a requisição e o movimento passa (AC5).

    Falso positivo (pagou outra coisa de exatamente R$ 380 em 3 dias) custa **um clique**, e é raro;
    verdadeiro positivo evita a divergência dobrada que parece um achado. Vale a troca.
    """
    _payable(client, headers)

    resp = _lancar(client, headers, account["id"], amount_cents=-VALOR, confirmar_avulso=True)

    assert resp.status_code == 201, resp.text
    assert resp.json()["amount_cents"] == -VALOR
    # O saldo se moveu de verdade — a confirmação não é um no-op cosmético.
    saldo = client.get(f"/bank/accounts/{account['id']}/balance", headers=headers).json()
    assert saldo["saldo_derivado_cents"] == OPENING_CENTS - VALOR


def test_confirmar_avulso_nao_e_persistido(client: TestClient, headers, account, db: Session):
    """É confirmação de INTENÇÃO, não fato sobre o movimento — não existe coluna, e não deve haver.

    Gravá-la criaria uma coluna que descreve o diálogo com o usuário em vez do dinheiro.
    """
    _payable(client, headers)
    resp = _lancar(client, headers, account["id"], amount_cents=-VALOR, confirmar_avulso=True)
    assert resp.status_code == 201

    assert "confirmar_avulso" not in resp.json()
    assert not hasattr(BankTransaction, "confirmar_avulso")
    tx = db.get(BankTransaction, resp.json()["id"])
    assert not hasattr(tx, "confirmar_avulso")


def test_sem_candidato_a_saida_manual_passa_em_silencio(client: TestClient, headers, account):
    """Sem `payable` casando, **201 e nenhum aviso**. Silêncio é o default."""
    resp = _lancar(client, headers, account["id"], amount_cents=-VALOR)
    assert resp.status_code == 201, resp.text


def test_tarifa_de_dois_reais_e_noventa_passa_sem_aviso(client: TestClient, headers, account):
    """**AC4 — movimento manual NEGATIVO continua legal, e isto é um AC, não uma nota.**

    Tarifa, IOF e taxa de TED são saídas que não têm — e nunca terão — conta a pagar: *"criar uma
    conta a pagar de R$ 2,90 para uma tarifa é a ERP-ificação que o produto recusa"*. Proibir saída
    manual seria a granularidade errada; a guarda por candidato é a certa.
    """
    resp = _lancar(
        client,
        headers,
        account["id"],
        amount_cents=-2_90,
        description="Tarifa de manutenção",
        operation_nature="tarifa_bancaria",
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["operation_nature"] == "tarifa_bancaria"
    assert client.get("/payables/bills", headers=headers).json() == []


def test_entrada_com_payable_de_mesmo_valor_nao_dispara(client: TestClient, headers, account):
    """A guarda é **só de saída**: dinheiro ENTRANDO não pode ser a mesma linha de uma obrigação."""
    _payable(client, headers)
    resp = _lancar(client, headers, account["id"], amount_cents=VALOR)
    assert resp.status_code == 201, resp.text


@pytest.mark.parametrize("delta", [-3, -1, 0, 1, 3])
def test_dentro_da_janela_de_tres_dias_dispara(client: TestClient, headers, account, delta: int):
    """±3 dias **dentro** — a borda é inclusiva, como a do enriquecimento da §4.5."""
    _payable(client, headers, due_date=DIA)
    resp = _lancar(
        client, headers, account["id"], amount_cents=-VALOR, posted_at=DIA + timedelta(days=delta)
    )
    assert resp.status_code == 409, resp.text


@pytest.mark.parametrize("delta", [-4, 4])
def test_fora_da_janela_de_tres_dias_nao_dispara(client: TestClient, headers, account, delta: int):
    """±4 dias **fora**. A janela é `DUPLICATA_JANELA_DIAS`, num lugar só."""
    _payable(client, headers, due_date=DIA)
    resp = _lancar(
        client, headers, account["id"], amount_cents=-VALOR, posted_at=DIA + timedelta(days=delta)
    )
    assert resp.status_code == 201, resp.text


def test_um_centavo_de_diferenca_nao_casa(client: TestClient, headers, account):
    """Valor **EXATO**, sem tolerância percentual — o design pede igualdade de módulo."""
    _payable(client, headers, amount_cents=VALOR)
    resp = _lancar(client, headers, account["id"], amount_cents=-(VALOR + 1))
    assert resp.status_code == 201, resp.text


def test_conta_a_pagar_ja_paga_tambem_e_candidata(client: TestClient, headers, account):
    """**O caso ruim de verdade**: o dono deu a baixa E lançou o mesmo pagamento à mão.

    É por isso que `paid` entra na busca. Se só `open` entrasse, a guarda calaria exatamente no
    cenário que produz a divergência dobrada.
    """
    p = _payable(client, headers)
    baixa = client.post(
        f"/payables/bills/{p['id']}/pay",
        json={"bank_account_id": account["id"]},
        headers=headers,
    )
    assert baixa.status_code == 200, baixa.text

    resp = _lancar(client, headers, account["id"], amount_cents=-VALOR)
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["payable_id"] == p["id"]


def test_conta_cancelada_nao_e_candidata(client: TestClient, headers, account):
    """Conta cancelada não é obrigação nenhuma — um 409 apontando para ela não teria saída."""
    p = _payable(client, headers)
    assert client.post(f"/payables/bills/{p['id']}/cancel", headers=headers).status_code == 200

    resp = _lancar(client, headers, account["id"], amount_cents=-VALOR)
    assert resp.status_code == 201, resp.text


def test_desempate_escolhe_o_candidato_mais_proximo(client: TestClient, headers, account):
    """Mais de um candidato → **uma** escolha, nunca uma lista (o mesmo anti-ruído da banda).

    Critério: **menor distância em dias** e, no empate, `due_date` mais recente.
    """
    _payable(client, headers, due_date=DIA - timedelta(days=3), supplier="Longe")
    perto = _payable(client, headers, due_date=DIA - timedelta(days=1), supplier="Perto")

    resp = _lancar(client, headers, account["id"], amount_cents=-VALOR, posted_at=DIA)
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["payable_id"] == perto["id"]


def test_desempate_por_vencimento_mais_recente(client: TestClient, headers, account):
    """Empate em distância (−2 e +2 dias) → vence o `due_date` mais RECENTE."""
    _payable(client, headers, due_date=DIA - timedelta(days=2), supplier="Antiga")
    recente = _payable(client, headers, due_date=DIA + timedelta(days=2), supplier="Recente")

    resp = _lancar(client, headers, account["id"], amount_cents=-VALOR, posted_at=DIA)
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["payable_id"] == recente["id"]


def test_update_transaction_nao_ganhou_a_guarda(client: TestClient, headers, account):
    """**Editar é correção, não criação** (ratificação §C-5.4) — o 409 ali seria uma parede.

    O movimento nasce com outro valor (sem candidato) e é EDITADO para o valor que casa com a conta
    a pagar. Isso passa, de propósito: ampliar a guarda por conta própria seria escopo inventado.
    """
    _payable(client, headers)
    tx = _lancar(client, headers, account["id"], amount_cents=-10_00).json()

    resp = client.patch(
        f"/bank/transactions/{tx['id']}", json={"amount_cents": -VALOR}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["amount_cents"] == -VALOR


# ── AC6 — o fail-closed, e a hora dele ───────────────────────────────────────────────────────


def test_app_nao_sobe_sem_o_probe_de_contagem_dupla(monkeypatch):
    """**A versão à prova de mutação de "a fiação registra o probe"** (ratificação §C-5.2).

    *"Um erro de fiação é condição de startup, não de request."* A alternativa — seguir sem validar
    — seria a guarda desligada em produção sem ninguém saber. Precedente do projeto: a guarda de
    boot contra `JWT_SECRET` fraco.
    """
    monkeypatch.setattr(bank_service, "_duplicata_probe", None)
    with pytest.raises(RuntimeError, match="guarda de contagem dupla"):
        app_main.verifica_fiacao_da_guarda()


def test_a_guarda_de_boot_e_chamada_no_nivel_do_modulo():
    """Teste **ESTRUTURAL**: um fail-closed que ninguém invoca é um comentário.

    Mutante a matar: apagar a chamada de `verifica_fiacao_da_guarda()` do corpo de `app/main.py`.
    Nenhum teste de comportamento pegaria isso — a app continuaria subindo, e a guarda de boot
    viraria uma função morta que ninguém percebe.
    """
    fonte = (pathlib.Path(app_main.__file__)).read_text(encoding="utf-8")
    tree = ast.parse(fonte)
    chamadas = {
        node.value.func.id
        for node in tree.body
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
    }
    assert "liga_a_guarda_de_contagem_dupla" in chamadas
    assert "verifica_fiacao_da_guarda" in chamadas, (
        "a guarda de BOOT da contagem dupla não é chamada no nível do módulo em app/main.py — a "
        "aplicação voltaria a subir com a guarda desligada, em silêncio"
    )


def test_o_probe_esta_registrado_de_verdade_depois_do_boot():
    """E o outro lado: importar a app **registra** a implementação concreta."""
    assert bank_service.duplicata_probe_registrado()


def test_segunda_guarda_recusa_o_lancamento_sem_criar_o_movimento(
    monkeypatch, db: Session, client: TestClient, headers, account
):
    """A guarda de request-time — inalcançável se a de boot funcionar, e **nunca silenciosa**.

    Mesma disciplina dupla que `update_transaction` documenta *"de propósito"*. O que ela **não**
    pode fazer é deixar passar: "não valida em silêncio" é a guarda desligada em produção.
    """
    monkeypatch.setattr(bank_service, "_duplicata_probe", None)
    tenant_id = client.get("/auth/me", headers=headers).json()["user"]["tenant_id"]
    antes = db.query(BankTransaction).count()

    with pytest.raises(bank_service.BankError) as exc:
        bank_service.create_transaction(
            db,
            bank_account_id=account["id"],
            tenant_id=tenant_id,
            actor="teste",
            data=BankTransactionCreate(posted_at=DIA, amount_cents=-VALOR, description="x"),
        )

    assert exc.value.status_code == 500
    assert db.query(BankTransaction).count() == antes


# ── AC1/AC2/AC3 — o vocabulário ──────────────────────────────────────────────────────────────


def test_operation_nature_aceita_texto_fora_da_lista(client: TestClient, headers, account):
    """**NÃO é whitelist** (AC3): *"Outro (descreva)"* grava o que o usuário escrever.

    *"O extrato está cheio de coisas que não imaginamos (estorno de tarifa, crédito de convênio,
    débito de seguro, cashback). Recusar um fato bancário legítimo porque ele não está na lista
    recria a incompletude que a onda combate."*
    """
    resp = _lancar(
        client,
        headers,
        account["id"],
        amount_cents=-1_00,
        operation_nature="estorno de tarifa",
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["operation_nature"] == "estorno de tarifa"


def test_operation_nature_continua_validado_por_TAMANHO(client: TestClient, headers, account):
    """A coluna é `String(24)` e o `max_length` do schema **não é afrouxado** por esta story."""
    resp = _lancar(client, headers, account["id"], amount_cents=-1_00, operation_nature="x" * 25)
    assert resp.status_code == 422, resp.text


def test_o_vocabulario_sugerido_e_o_da_story():
    """AC1: um valor novo (`tarifa_bancaria`) e três já existentes no design-mãe §7.2."""
    assert OPERATION_NATURES == (
        "tarifa_bancaria",
        "tributo",
        "transferencia_propria",
        "receita_financeira",
    )


def test_vocabulario_sugerido_bate_com_a_ui():
    """As duas listas (Python e TS) são **espelhos manuais** — este teste é o que as amarra.

    Mesmo padrão que `BANK_ACCOUNT_KINDS` já usa para `KINDS`. Sem ele, a UI ofereceria um valor
    que o backend não sugere (ou vice-versa) e ninguém saberia até alguém abrir as duas telas.

    Pula (em vez de falhar) quando `apps/web` não está presente: o backend precisa poder rodar
    sozinho num container sem o frontend.

    ⚠️ **[CORREÇÃO, gate do PR #71]** A guarda tem que vir ANTES de indexar `parents[3]`, não
    depois: dentro da imagem de produção (`apps/api/Dockerfile`, contexto de build = só `apps/api`)
    a árvore é mais rasa e `parents[3]` levanta `IndexError` — não "arquivo ausente". Checar
    `.exists()` depois de já ter estourado o índice nunca executa. Mesmo padrão de
    `test_financial_intelligence_onda2_signals.py::test_o_rotulo_do_frontend_tambem_perdeu_o_adjetivo`.
    """
    parents = pathlib.Path(__file__).resolve().parents
    if len(parents) <= 3:
        pytest.skip("apps/web não está presente nesta árvore")
    contas_ts = parents[3] / "apps" / "web" / "src" / "features" / "financeiro" / "contas.ts"
    if not contas_ts.exists():
        pytest.skip("apps/web não está presente nesta árvore")
    texto = contas_ts.read_text(encoding="utf-8")
    faltando = [v for v in OPERATION_NATURES if f'"{v}"' not in texto]
    assert not faltando, f"valores sugeridos pelo backend e ausentes da UI: {faltando}"


def test_estados_candidatos_existem_no_vocabulario():
    """⚠️ **`scheduled` NÃO existe ainda** — quem o cria é a Story 8.14.

    A Story 8.17 AC5 lista `open|scheduled|paid`; o vocabulário real de `payables` é
    `{open, paid, canceled}`. Filtrar por um valor inexistente seria ruído, então `scheduled` entra
    quando nascer. Este teste reprova se alguém acrescentar um estado que não existe — e é ele que
    lembra de acrescentar o que passar a existir.
    """
    assert set(_ESTADOS_CANDIDATOS) <= ALL_STATUSES
    assert "canceled" not in _ESTADOS_CANDIDATOS


def test_zero_migration_a_coluna_ja_existia():
    """**AC2** — verificado, não presumido: nenhuma revision nova nesta story.

    Se durante a implementação parecer que uma migration é necessária, isso é sinal de que o AC2 foi
    violado.
    """
    coluna = BankTransaction.__table__.c.operation_nature
    assert coluna.nullable is True
    assert coluna.type.length == 24
    versions = pathlib.Path(__file__).resolve().parents[1] / "migrations" / "versions"
    assert not list(versions.glob("*8_17*")), "esta story não cria migration"


# ── AC7/AC9/IV3 — o legado e o saldo ─────────────────────────────────────────────────────────


def test_movimento_legado_com_natureza_nula_continua_legal(client: TestClient, headers, account):
    """**Nada automático sobre o `source='manual'` que já existe** (AC7).

    Lançar sem informar a finalidade continua **201** e a linha nasce com `NULL` — a curadoria é de
    UI. *"Uma linha manual é a afirmação do usuário; reescrevê-la seria a tradução silenciosa entre
    dois vocabulários que a lição D-3 proíbe."*
    """
    resp = _lancar(client, headers, account["id"], amount_cents=-1_00)
    assert resp.status_code == 201, resp.text
    assert resp.json()["operation_nature"] is None


def test_operation_nature_nao_move_o_saldo_derivado(client: TestClient, headers, account):
    """**IV3/AC9** — `operation_nature` é RÓTULO, não fato de dinheiro.

    Dois movimentos idênticos, um com finalidade e outro sem: o saldo derivado é o mesmo número.
    """
    _lancar(client, headers, account["id"], amount_cents=-1_00, operation_nature="tributo")
    com = client.get(f"/bank/accounts/{account['id']}/balance", headers=headers).json()

    _lancar(client, headers, account["id"], amount_cents=-1_00, posted_at=DIA + timedelta(days=1))
    depois = client.get(f"/bank/accounts/{account['id']}/balance", headers=headers).json()

    assert com["saldo_derivado_cents"] == OPENING_CENTS - 1_00
    assert depois["saldo_derivado_cents"] == OPENING_CENTS - 2_00
