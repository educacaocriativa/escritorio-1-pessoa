"""A **Regra da Origem** — contrato do sincronizador único (Story 8.9).

Esta story entrega o **contrato**, não o comportamento: ao final dela `sync_origin_movement` existe,
é testada e **não tem um único chamador em produção**. Por isso os testes aqui chamam a função
**direto**, e um deles (`test_nenhum_chamador_de_producao_ainda`) guarda justamente essa ausência —
ele é a fronteira de escopo entre a 8.9 e a 8.12, escrita como asserção em vez de como parágrafo.

Cobre (AC2-AC9 / Tasks 5-8):
- os **três ramos** do sincronizador: ausente → cria; presente → atualiza a MESMA linha (move, nunca
  duplica); `bank_account_id=None` → apaga;
- **AC5** `status='matched'` no nascimento, `raw_description = description`, linha puramente
  sintética (`fitid`/`import_batch_id` nulos), e **não commita** — o contrato do qual a 8.12 depende
  para que a baixa e o movimento caiam na mesma transação;
- **AC6** `origin_dedup_hash` é `sha256("{source}|{origin_id}")` e é **estável sob troca de conta**;
- **AC2** o índice único parcial: mesma origem colide; `origin_id IS NULL` **não** colide (a metade
  autoritativa, no Postgres real, vive em `test_bank_rls.py`);
- **AC4** a Invariante da Origem nas **duas** direções;
- **AC9** a guarda da linha puramente sintética: apaga quando sintética, **desliga a origem** quando
  já enriquecida pela importação (ramo inalcançável hoje, montado à mão);
- **AC7** `test_cache_de_movimento_nunca_diverge_do_origin_id` sobre os **cinco** caminhos de
  mutação — o teste que substitui o `app/scripts/bank_audit.py` que **não existe**;
- **§C-3.3** `test_origin_id_cabe_na_coluna` — toda forma de chave de origem do repositório cabe em
  `VARCHAR(64)`, inclusive as sufixadas `:out`/`:in` da Story 8.18;
- **IV1/IV2** DRE e Projeção intactas.

RLS/isolamento cross-tenant **não** é exercido aqui (SQLite — ver `conftest.py`): no banco dos
testes unitários todas as linhas são visíveis a todas as sessões. Isso vive em `test_bank_rls.py`
(`rls_e2e`), que esta story estendeu.
"""
from __future__ import annotations

import ast
import pathlib
from dataclasses import asdict
from datetime import date, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.bank import service as bank_service
from app.modules.bank.models import (
    SOURCE_CHARGE,
    SOURCE_MANUAL,
    SOURCE_OFX,
    SOURCE_PAYABLE,
    SOURCE_TRANSFER,
    SOURCES_SISTEMA,
    STATUS_MATCHED,
    STATUS_UNMATCHED,
    BankTransaction,
)
from app.modules.bank.origin import origin_dedup_hash, sync_origin_movement
from app.modules.financial_intelligence import dre as dre_service
from app.modules.financial_intelligence import projection as projection_service
from app.modules.payables.models import Payable

REGISTER = {
    "legal_name": "Regra da Origem ME",
    "document": "11444777000161",
    "slug": "regradaorigem",
    "email": "origem@example.com",
    "name": "Otávia",
    "password": "uma-senha-bem-grande",
}

OPENING = date(2026, 7, 1)
OPENING_CENTS = 1_500_00
DIA = date(2026, 7, 10)

APP_DIR = pathlib.Path(__file__).resolve().parents[1] / "app"


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def tenant_id(client: TestClient, headers) -> str:
    return client.get("/auth/me", headers=headers).json()["user"]["tenant_id"]


def _account(client: TestClient, headers, *, name: str = "Itaú PJ", **over) -> dict:
    payload = {
        "name": name,
        "kind": "checking",
        "opening_balance_cents": OPENING_CENTS,
        "opening_balance_is_known": True,
        "opening_date": OPENING.isoformat(),
    }
    payload.update(over)
    resp = client.post("/bank/accounts", json=payload, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _sync(db: Session, tenant_id: str, **over):
    """`sync_origin_movement` com os defaults do caso `payable` (saída, valor NEGATIVO)."""
    kwargs = {
        "tenant_id": tenant_id,
        "actor": "dono",
        "source": SOURCE_PAYABLE,
        "origin_id": str(uuid4()),
        "bank_account_id": None,
        "posted_at": DIA,
        "amount_cents": -120_00,
        "description": "Aluguel — Imobiliária Central",
    }
    kwargs.update(over)
    return sync_origin_movement(db, **kwargs)


def _movimento_da_origem(db: Session, *, source: str, origin_id: str) -> BankTransaction | None:
    return db.scalars(
        select(BankTransaction).where(
            BankTransaction.source == source, BankTransaction.origin_id == origin_id
        )
    ).first()


# ── Ramo 1 — ausente → CRIA, e nasce conciliado (AC5) ────────────────────────────────────────


def test_cria_movimento_de_origem_ja_conciliado(client: TestClient, headers, tenant_id, db):
    """Nasce `matched`, com `origin_id`, puramente sintético — e **move o saldo derivado**.

    `status='matched'` no nascimento é a única escrita legítima desse status fora do
    `_refresh_status` da conciliação (Onda 5, inexistente): o e1p originou os DOIS lados do fato,
    então não há julgamento de conciliação a fazer.
    """
    acc = _account(client, headers)
    origin_id = str(uuid4())

    tx = _sync(db, tenant_id, origin_id=origin_id, bank_account_id=acc["id"])
    db.commit()

    assert tx is not None
    assert tx.source == SOURCE_PAYABLE and tx.origin_id == origin_id
    assert tx.status == STATUS_MATCHED, (
        "movimento de origem do sistema precisa nascer conciliado — o e1p originou os dois lados"
    )
    assert tx.bank_account_id == acc["id"]
    assert tx.amount_cents == -120_00 and tx.posted_at == DIA
    assert tx.raw_description == "Aluguel — Imobiliária Central"
    assert tx.user_description == "", "o rótulo do dono não é escrito pelo sincronizador"
    # Puramente sintética: é o que a guarda do DELETE (AC9) inspeciona.
    assert tx.fitid is None and tx.import_batch_id is None
    assert tx.dedup_hash == origin_dedup_hash(SOURCE_PAYABLE, origin_id)
    # E o saldo derivado — que é derivado, não coluna — se moveu sozinho.
    assert bank_service.derived_balance(db, bank_account_id=acc["id"], until=DIA) == (
        OPENING_CENTS - 120_00
    )


def test_nao_commita_e_isso_e_contrato(client: TestClient, headers, tenant_id, db):
    """**AC5, o contrato do qual a 8.12 depende:** o movimento entra na transação do CHAMADOR.

    Mesmo motivo de `build_payable`/`apply_paid`/`build_charge`: o movimento e o lançamento entram
    na **mesma transação**, e um dos dois sem o outro é exatamente o estado que esta função existe
    para tornar impossível. Se algum dia alguém acrescentar um `db.commit()` aqui dentro, este teste
    é quem avisa — e o sintoma em produção seria um movimento bancário sobrevivendo ao rollback de
    uma baixa que falhou.
    """
    acc = _account(client, headers)
    origin_id = str(uuid4())

    _sync(db, tenant_id, origin_id=origin_id, bank_account_id=acc["id"])
    db.rollback()

    assert _movimento_da_origem(db, source=SOURCE_PAYABLE, origin_id=origin_id) is None, (
        "o movimento sobreviveu ao rollback do chamador — `sync_origin_movement` commitou por "
        "conta própria e quebrou a atomicidade que a Story 8.12 depende"
    )


# ── Ramo 2 — presente → ATUALIZA a mesma linha. Move, nunca duplica (AC5) ────────────────────


def test_atualiza_a_mesma_linha_nunca_duplica(client: TestClient, headers, tenant_id, db):
    """Trocar conta, data e valor **move** a mesma linha; os dois saldos se corrigem sozinhos."""
    origem = _account(client, headers, name="Itaú PJ")
    destino = _account(client, headers, name="Nubank PJ", number="99-9")
    origin_id = str(uuid4())

    primeiro = _sync(db, tenant_id, origin_id=origin_id, bank_account_id=origem["id"])
    db.commit()
    primeiro_id = primeiro.id

    segundo = _sync(
        db,
        tenant_id,
        origin_id=origin_id,
        bank_account_id=destino["id"],
        posted_at=DIA + timedelta(days=3),
        amount_cents=-150_00,
        description="Aluguel — valor corrigido",
    )
    db.commit()

    assert segundo.id == primeiro_id, "o sincronizador duplicou em vez de mover"
    assert db.query(BankTransaction).count() == 1
    assert segundo.bank_account_id == destino["id"]
    assert segundo.posted_at == DIA + timedelta(days=3)
    assert segundo.amount_cents == -150_00
    assert segundo.raw_description == "Aluguel — valor corrigido"
    # Os DOIS saldos se corrigem sozinhos porque são derivados dos movimentos, nunca colunas.
    ate = date(2026, 7, 20)
    assert bank_service.derived_balance(db, bank_account_id=origem["id"], until=ate) == (
        OPENING_CENTS
    )
    assert bank_service.derived_balance(db, bank_account_id=destino["id"], until=ate) == (
        OPENING_CENTS - 150_00
    )


def test_atualizar_nao_reidrata_o_hash_ao_trocar_de_conta(
    client: TestClient, headers, tenant_id, db
):
    """**AC6:** o hash NÃO carrega a conta, então trocar de conta é UPDATE puro.

    Se `bank_account_id` entrasse na fórmula, a troca exigiria reidratar o hash — e o que é uma
    correção viraria uma recriação.
    """
    origem = _account(client, headers, name="Itaú PJ")
    destino = _account(client, headers, name="Nubank PJ", number="99-9")
    origin_id = str(uuid4())

    antes = _sync(db, tenant_id, origin_id=origin_id, bank_account_id=origem["id"])
    hash_antes = antes.dedup_hash
    db.commit()

    depois = _sync(db, tenant_id, origin_id=origin_id, bank_account_id=destino["id"])
    db.commit()

    assert depois.dedup_hash == hash_antes == origin_dedup_hash(SOURCE_PAYABLE, origin_id)


def test_hash_de_origem_e_estavel_sob_troca_de_conta():
    """**AC6, a fórmula em si:** `sha256("{source}|{origin_id}")`, sem a conta. Função pura."""
    import hashlib

    origin_id = str(uuid4())
    esperado = hashlib.sha256(f"{SOURCE_PAYABLE}|{origin_id}".encode()).hexdigest()
    assert origin_dedup_hash(SOURCE_PAYABLE, origin_id) == esperado
    # Estável: a conta não entra na fórmula, então não há como ela mudar o resultado.
    assert origin_dedup_hash(SOURCE_PAYABLE, origin_id) == origin_dedup_hash(
        SOURCE_PAYABLE, origin_id
    )
    # E discrimina por `source`: o mesmo id vindo de origens diferentes são dois fatos diferentes.
    assert origin_dedup_hash(SOURCE_CHARGE, origin_id) != esperado


# ── Ramo 3 — desliquidado → APAGA (AC5, AC9) ─────────────────────────────────────────────────


def test_apaga_quando_a_origem_deixa_de_estar_liquidada(
    client: TestClient, headers, tenant_id, db
):
    """Estorno: o movimento **some**, e o saldo volta ao que era. Sem contrapartida, sem `ignored`.

    Contrapartida (`+valor`) inventaria um crédito que **nunca existiu no banco**; `ignored` é
    estado de julgamento do dono, não de sistema, e ainda colidiria com o índice único no
    repagamento. Apagar é o que devolve a verdade: o sistema não afirma mais que aquele dinheiro
    saiu. A trilha fica em `audit_entries`, que é a finalidade dela.
    """
    acc = _account(client, headers)
    origin_id = str(uuid4())

    _sync(db, tenant_id, origin_id=origin_id, bank_account_id=acc["id"])
    db.commit()
    assert bank_service.derived_balance(db, bank_account_id=acc["id"], until=DIA) != OPENING_CENTS

    resultado = _sync(db, tenant_id, origin_id=origin_id, bank_account_id=None)
    db.commit()

    assert resultado is None
    assert _movimento_da_origem(db, source=SOURCE_PAYABLE, origin_id=origin_id) is None
    assert bank_service.derived_balance(db, bank_account_id=acc["id"], until=DIA) == OPENING_CENTS


def test_apagar_o_que_nao_existe_e_sucesso_nao_404(tenant_id, db, client, headers):
    """Idempotência do ramo de remoção: estornar duas vezes não explode na segunda."""
    assert _sync(db, tenant_id, origin_id=str(uuid4()), bank_account_id=None) is None


@pytest.mark.parametrize(
    "enriquecimento",
    [
        pytest.param({"fitid": "20260710001"}, id="so-fitid"),
        pytest.param({"import_batch_id": "lote-1"}, id="so-import_batch_id"),
        pytest.param({"fitid": "20260710001", "import_batch_id": "lote-1"}, id="os-dois"),
    ],
)
def test_guarda_da_linha_enriquecida_desliga_a_origem_em_vez_de_apagar(
    client: TestClient, headers, tenant_id, db, enriquecimento
):
    """**AC9 — o ramo INALCANÇÁVEL hoje, e é por isso que ele entra agora.**

    Se a importação (Onda 4) já tiver **enriquecido** a linha sintética com a linha real do extrato
    (`fitid`/`import_batch_id`), o estorno **não apaga**: desliga a origem e a linha volta a ser um
    movimento órfão do extrato — o que é **verdade** (o dinheiro saiu mesmo; o sistema é que não
    sabe mais por quê). Degradação honesta.

    Não existe importação hoje, então a linha enriquecida é montada **à mão**. Escrever esta guarda
    na Onda 4 significaria descobrir a regra **depois de já ter perdido dado bancário real** — e o
    modo de falha é silencioso: um `DELETE` bem-sucedido em cima de uma evidência que não voltava.

    ⚠️ **Os dois marcadores são exercitados SEPARADAMENTE, e a parametrização é o teste.** A
    primeira versão deste teste setava os dois de uma vez, e o mutante *"remova o `fitid IS NULL` da
    guarda"* **sobrevivia** — porque o `import_batch_id` sozinho já mantinha a linha viva. Um `and`
    de duas condições exige um caso por condição, senão metade da guarda não está testada. E as duas
    são independentes de verdade: um CSV enriquece sem `fitid` (o formato não tem), e um match
    manual futuro pode gravar `fitid` sem lote de importação.
    """
    acc = _account(client, headers)
    origin_id = str(uuid4())

    tx = _sync(db, tenant_id, origin_id=origin_id, bank_account_id=acc["id"])
    for campo, valor in enriquecimento.items():  # ← o enriquecimento que a Onda 4 vai fazer
        setattr(tx, campo, valor)
    db.commit()
    tx_id = tx.id

    resultado = _sync(db, tenant_id, origin_id=origin_id, bank_account_id=None)
    db.commit()

    assert resultado is None, "a origem foi desligada, então não há movimento de origem a devolver"
    sobrevivente = db.get(BankTransaction, tx_id)
    assert sobrevivente is not None, "a linha do EXTRATO foi apagada — dado bancário real perdido"
    assert sobrevivente.origin_id is None
    assert sobrevivente.source == SOURCE_OFX
    assert sobrevivente.status == STATUS_UNMATCHED
    # O dinheiro saiu mesmo: o saldo NÃO volta ao de abertura, e é isso que a honestidade custa.
    assert bank_service.derived_balance(db, bank_account_id=acc["id"], until=DIA) == (
        OPENING_CENTS - 120_00
    )


# ── AC2 — o índice único parcial (a metade que o SQLite consegue provar) ─────────────────────


def test_indice_unico_impede_dois_movimentos_para_a_mesma_origem(
    client: TestClient, headers, tenant_id, db
):
    """**A idempotência é o ÍNDICE, não o `dedup_hash`.**

    Escrito **contornando** o sincronizador de propósito: o que precisa estar provado é que o
    **banco** recusa, e não que a função tem um `if`. É essa garantia que sobrevive a um retry de
    request, a um reprocessamento de baixa e a um segundo caminho de escrita que alguém abra por
    engano.

    ⚠️ A prova autoritativa é no **Postgres real** (`test_bank_rls.py`), porque é lá que a produção
    roda. Ela vale aqui também porque o `sqlite_where` está declarado no modelo junto do
    `postgresql_where` — sem ele o índice nasceria TOTAL no SQLite e este arquivo estaria
    exercitando um schema que a produção não tem.
    """
    acc = _account(client, headers)
    origin_id = str(uuid4())
    _sync(db, tenant_id, origin_id=origin_id, bank_account_id=acc["id"])
    db.commit()

    db.add(
        BankTransaction(
            tenant_id=tenant_id,
            bank_account_id=acc["id"],
            posted_at=DIA,
            amount_cents=-120_00,
            raw_description="a mesma origem, de novo",
            dedup_hash="hash-diferente-de-proposito",
            source=SOURCE_PAYABLE,
            origin_id=origin_id,
            status=STATUS_MATCHED,
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_dois_movimentos_com_origin_id_nulo_convivem(client: TestClient, headers, db):
    """A outra metade da AC2: dois movimentos com `origin_id IS NULL` na mesma conta **passam**.

    ⚠️ **Correção ao texto da AC2, achada por mutação nesta implementação.** A story justifica o
    `WHERE origin_id IS NOT NULL` dizendo que *"sem ele, todo movimento manual colidiria com todo
    outro movimento manual"*. **Isso é falso** — e o próprio design escreve o motivo duas páginas
    antes, ao rejeitar a coluna `leg`: **no Postgres, `NULL` é distinto de `NULL` em índice único
    por padrão** (idem no SQLite). Removendo a cláusula, este teste **continua passando**; foi
    exatamente o que o mutante mostrou.

    O comportamento afirmado aqui é verdadeiro e obrigatório, então o teste fica. O que **não**
    fica é a inferência: quem garante que a cláusula não vai embora é
    `test_indice_de_origem_e_parcial`, que é estrutural, porque **nenhum teste de comportamento
    distingue o índice parcial do total**.
    """
    acc = _account(client, headers)
    for i in (1, 2):
        resp = client.post(
            f"/bank/accounts/{acc['id']}/transactions",
            json={
                "posted_at": DIA.isoformat(),
                "amount_cents": -50_00,
                "description": f"Pix manual {i}",
            },
            headers=headers,
        )
        assert resp.status_code == 201, resp.text

    movimentos = db.scalars(select(BankTransaction)).all()
    assert len(movimentos) == 2
    assert all(m.origin_id is None and m.source == SOURCE_MANUAL for m in movimentos)


def test_indice_de_origem_e_parcial():
    """**A guarda estrutural da cláusula `WHERE origin_id IS NOT NULL`** (AC2), e por que é assim.

    Este teste existe porque um mutante provou que **nenhum teste de comportamento mata a remoção
    da cláusula**: com o índice TOTAL, a suíte inteira fica verde (`NULL` é distinto de `NULL` em
    índice único, tanto no Postgres quanto no SQLite). Um mutante que nenhum teste mata não é um
    teste faltando — é um teste do **tipo errado**.

    A cláusula fica por duas razões que continuam valendo:
      (1) **tamanho e intenção** — o índice carrega só as linhas de origem de sistema, a minoria,
          em vez de uma entrada por movimento do tenant;
      (2) **não depender do comportamento de `NULL`** — `NULLS DISTINCT` é o default do Postgres,
          mas é **configurável desde o PG15** (`NULLS NOT DISTINCT`). Com o índice parcial, a
          convivência de dois movimentos externos é estrutural: eles nem estão no índice.

    E as duas metades (`postgresql_where` **e** `sqlite_where`) são verificadas porque declarar só
    uma faz o SQLite dos unitários exercitar um schema que a produção não tem — a mesma disciplina
    que `BankAccount` documentou na Story 8.2.
    """
    indice = next(
        i for i in BankTransaction.__table__.indexes if i.name == "uq_bank_transactions_origin"
    )
    assert indice.unique is True
    assert [c.name for c in indice.columns] == ["tenant_id", "source", "origin_id"], (
        "`tenant_id` precisa ser a PRIMEIRA coluna: índice único é GLOBAL e não respeita RLS"
    )
    for dialeto in ("postgresql", "sqlite"):
        clausula = indice.dialect_options[dialeto].get("where")
        assert clausula is not None, (
            f"o índice de origem deixou de ser PARCIAL no dialeto {dialeto}. Ver a explicação "
            "longa em `bank/models.py` e no docstring deste teste."
        )
        assert "origin_id IS NOT NULL" in str(clausula)


# ── AC4 — a Invariante da Origem, nas DUAS direções ──────────────────────────────────────────


def test_origem_do_sistema_sempre_tem_origin_id(client: TestClient, headers, tenant_id, db):
    """`source ∈ SOURCES_SISTEMA` ⟺ `origin_id IS NOT NULL`.

    **Testar só um lado deixa passar exatamente o estado que a Onda 4 vai criar por acidente:** uma
    linha importada (`ofx`) com `origin_id` preenchido — que faria o sincronizador tratar dado
    bancário real como se fosse sintético dele, e apagá-lo num estorno.

    A invariante é aplicada no **service** (não por `CheckConstraint`), padrão do projeto:
    integridade onde ela pode explicar.
    """
    acc = _account(client, headers)
    # Um movimento de cada lado do vocabulário, no mesmo tenant.
    _sync(db, tenant_id, origin_id=str(uuid4()), bank_account_id=acc["id"])
    client.post(
        f"/bank/accounts/{acc['id']}/transactions",
        json={"posted_at": DIA.isoformat(), "amount_cents": 42_00, "description": "manual"},
        headers=headers,
    )
    db.commit()

    movimentos = db.scalars(select(BankTransaction)).all()
    assert len(movimentos) == 2, "pré-condição: o cenário precisa ter os dois lados"

    # (a) nenhum movimento de SISTEMA sem `origin_id`
    sem_origem = [m.id for m in movimentos if m.source in SOURCES_SISTEMA and not m.origin_id]
    assert not sem_origem, (
        f"INVARIANTE DA ORIGEM violada (⇒): movimento de sistema sem `origin_id`: {sem_origem}. "
        "Sem ele o movimento é órfão: não há como movê-lo quando o lançamento muda, nem apagá-lo "
        "quando ele é estornado."
    )
    # (b) nenhum movimento EXTERNO com `origin_id`
    com_origem = [m.id for m in movimentos if m.source not in SOURCES_SISTEMA and m.origin_id]
    assert not com_origem, (
        f"INVARIANTE DA ORIGEM violada (⇐): movimento externo COM `origin_id`: {com_origem}. É "
        "assim que a importação da Onda 4 produziria uma linha de extrato real que o sincronizador "
        "acha que é dele — e apaga no primeiro estorno."
    )


def test_source_fora_de_sources_sistema_e_422(tenant_id, db, client, headers):
    """A função **não é porta genérica de escrita** — 422 para todo valor de `SOURCES_EXTERNA`."""
    acc = _account(client, headers)
    for source in ("manual", "ofx", "csv", "inventado"):
        with pytest.raises(bank_service.BankError) as exc:
            _sync(db, tenant_id, source=source, bank_account_id=acc["id"])
        assert exc.value.status_code == 422
        assert source in str(exc.value)


def test_origin_id_vazio_e_422(tenant_id, db, client, headers):
    acc = _account(client, headers)
    with pytest.raises(bank_service.BankError) as exc:
        _sync(db, tenant_id, origin_id="", bank_account_id=acc["id"])
    assert exc.value.status_code == 422


def test_origin_id_cabe_na_coluna():
    """**Normativo (ratificação §C-3.3).** Toda forma de chave de origem do repositório cabe.

    ⚠️ **Este teste é o que faz uma origem de várias pernas nova reprovar em CI, e não no
    `ALTER COLUMN` sobre tabela com dado sob `FORCE ROW LEVEL SECURITY`** — a armadilha da 0046, que
    o ADR 0003 nomeia como o único ponto desse tipo do épico.

    A largura é lida do **modelo**, nunca escrita à mão aqui: um teste que repete o número não
    verifica nada no dia em que o número mudar. Se a sua story introduzir uma forma de chave nova,
    acrescente-a a `formas` — é o gasto de 5 segundos que a Regra da Instanciação pede.
    """
    largura = BankTransaction.__table__.c.origin_id.type.length
    assert largura == 64, (
        f"a largura de `origin_id` mudou para {largura}. Se foi para MENOS, releia a §C-3.3: a "
        "chave sufixada da Story 8.18 tem 40 caracteres e o vocabulário de perna pode crescer."
    )

    lancamento = str(uuid4())  # `payable.id`, `charge.id`, `investment.id`, `payout.id` — 36
    transferencia = str(uuid4())
    formas = {
        "payable.id (perna única)": lancamento,
        "charge.id (perna única)": lancamento,
        "transfer :out (Story 8.18)": f"{transferencia}:out",
        "transfer :in (Story 8.18)": f"{transferencia}:in",
    }
    grandes = {nome: len(chave) for nome, chave in formas.items() if len(chave) > largura}
    assert not grandes, (
        f"chave de origem maior que VARCHAR({largura}): {grandes}. Corrigir isso depois custa um "
        "`ALTER COLUMN` sobre tabela com dado sob FORCE RLS."
    )


# ── AC5 — as guardas de valor, data e conta ──────────────────────────────────────────────────


def test_valor_zero_e_422(client: TestClient, headers, tenant_id, db):
    acc = _account(client, headers)
    with pytest.raises(bank_service.BankError) as exc:
        _sync(db, tenant_id, bank_account_id=acc["id"], amount_cents=0)
    assert exc.value.status_code == 422


def test_conta_inexistente_e_404_fail_closed(tenant_id, db, client, headers):
    """404 e não 422: sob RLS, "conta de outro tenant" e "conta inexistente" são o mesmo fato."""
    with pytest.raises(bank_service.BankError) as exc:
        _sync(db, tenant_id, bank_account_id=str(uuid4()))
    assert exc.value.status_code == 404


def test_data_anterior_a_abertura_e_422_com_mensagem_acionavel(
    client: TestClient, headers, tenant_id, db
):
    """O **piso** vale para os dois conjuntos de `source`, sem exceção (design §4.2.0).

    A mensagem nasce aqui, acionável — quem a transforma em 422 de API é a 8.12. E a guarda é
    **reusada** de `service.validate_posted_at_floor`, nunca recopiada: duas cópias do mesmo
    predicado divergem no dia em que só uma for corrigida.
    """
    acc = _account(client, headers)
    with pytest.raises(bank_service.BankError) as exc:
        _sync(db, tenant_id, bank_account_id=acc["id"], posted_at=OPENING)
    assert exc.value.status_code == 422
    assert OPENING.isoformat() in str(exc.value)


def test_data_futura_e_aceita_para_origem_de_sistema(client: TestClient, headers, tenant_id, db):
    """O **teto** NÃO se aplica a `SOURCES_SISTEMA` (design §4.2.0, normativo).

    *"O e1p pode afirmar o futuro do que ele mesmo agendou; não pode afirmar o futuro do que outro
    atestou."* O lançamento manual continua recusando data futura (`_validate_posted_at`, teste em
    `test_bank_transactions.py`); o pagamento agendado no app do banco é um fato que o e1p conhece
    em primeira mão. O corte é por `source`, e **não existe booleano `permite_futuro`**.

    Quem põe teto em hoje é a 8.12; quem o libera de fato para o usuário é a 8.14.
    """
    acc = _account(client, headers)
    futuro = date.today() + timedelta(days=30)
    tx = _sync(db, tenant_id, bank_account_id=acc["id"], posted_at=futuro)
    db.commit()
    assert tx.posted_at == futuro


def test_sincronizador_nao_escreve_user_description(client: TestClient, headers, tenant_id, db):
    """O rótulo do dono sobrevive a qualquer ressincronização (Regra da Origem (d))."""
    acc = _account(client, headers)
    origin_id = str(uuid4())
    tx = _sync(db, tenant_id, origin_id=origin_id, bank_account_id=acc["id"])
    tx.user_description = "aluguel da sala nova"
    db.commit()

    _sync(
        db, tenant_id, origin_id=origin_id, bank_account_id=acc["id"],
        description="Aluguel — descrição do sistema mudou",
    )
    db.commit()
    assert tx.user_description == "aluguel da sala nova"
    assert tx.raw_description == "Aluguel — descrição do sistema mudou"


# ── AC7 — o teste que substitui o script que NÃO existe ──────────────────────────────────────


def _cache_coerente(db: Session, payable: Payable) -> None:
    """A asserção do AC7, isolada para ser repetida nos cinco caminhos.

    `payable.bank_transaction_id` aponta para o movimento com `origin_id = payable.id` — **ou** os
    dois são `NULL`. Nunca um preenchido e o outro não.
    """
    movimento = _movimento_da_origem(db, source=SOURCE_PAYABLE, origin_id=payable.id)
    if movimento is None:
        assert payable.bank_transaction_id is None, (
            "cache aponta para um movimento que não existe mais — `origin_id` é quem manda, e ele "
            "diz que não há movimento"
        )
    else:
        assert payable.bank_transaction_id == movimento.id, (
            f"cache ({payable.bank_transaction_id}) diverge do movimento cujo `origin_id` é o "
            f"`payable.id` ({movimento.id}). Quem manda é o `origin_id`."
        )


def test_cache_de_movimento_nunca_diverge_do_origin_id(
    client: TestClient, headers, tenant_id, db
):
    """**AC7 — os CINCO caminhos de mutação: baixar, trocar conta, trocar data, estornar, repagar.**

    ⚠️ **Este teste existe no lugar de `python -m app.scripts.bank_audit`, que NÃO EXISTE** e não
    deve ser criado aqui (ratificação §C-4; `grep -rn "bank_audit" apps/` = 0 ocorrências). A
    divergência entre o cache e o `origin_id` só é alcançável **por bug**: o sincronizador é o
    escritor único, devolve a linha na mesma chamada e na mesma transação, e o chamador grava o
    cache com o que recebeu — não há segundo caminho, não há concorrência, não há materialização
    assíncrona. **Condição alcançável só por bug se prova com teste, não com script; um script que
    ninguém tem gatilho para rodar não é garantia, é intenção documentada.** O script volta a ser
    necessário na Onda 5, junto de `_refresh_status` (também inexistente hoje).

    ⚠️ **Nesta story os cinco caminhos são exercitados chamando `sync_origin_movement` direto e
    escrevendo o cache à mão**, porque nenhum chamador de produção existe ainda. **A Story 8.12
    ESTENDEU este teste** para os caminhos reais, em
    `test_cache_de_movimento_nunca_diverge_do_origin_id_pelos_caminhos_reais` (logo abaixo), com as
    **mesmas** asserções (`_cache_coerente`) sobre as **mesmas** cinco mutações. Os dois convivem de
    propósito: este prova o contrato do sincronizador isolado — que continua valendo para a 8.15 e
    a 8.18, cujos chamadores ainda não existem —, e o de baixo prova o fluxo real de ponta a ponta.
    """
    itau = _account(client, headers, name="Itaú PJ")
    nubank = _account(client, headers, name="Nubank PJ", number="99-9")

    criada = client.post(
        "/payables/bills",
        json={"description": "Aluguel", "category": "Aluguel", "amount_cents": 120_00,
              "due_date": DIA.isoformat()},
        headers=headers,
    )
    assert criada.status_code == 201, criada.text
    payable = db.get(Payable, criada.json()["id"])
    _cache_coerente(db, payable)  # (0) antes de qualquer baixa: os dois NULL

    def _sincronizar(*, conta: str | None, quando: date | None = DIA) -> None:
        """O que a 8.12 vai fazer dentro de `apply_paid`, aqui feito à mão."""
        movimento = sync_origin_movement(
            db,
            tenant_id=tenant_id,
            actor="dono",
            source=SOURCE_PAYABLE,
            origin_id=payable.id,
            bank_account_id=conta,
            posted_at=quando,
            amount_cents=-payable.amount_cents if conta else None,
            description=payable.description,
            counterparty_name=payable.supplier,
        )
        payable.bank_account_id = conta
        payable.bank_transaction_id = movimento.id if movimento else None
        db.commit()

    # (1) BAIXAR
    _sincronizar(conta=itau["id"])
    _cache_coerente(db, payable)
    primeiro_movimento = payable.bank_transaction_id
    assert primeiro_movimento is not None

    # (2) TROCAR A CONTA — move, nunca duplica: o cache continua apontando para a MESMA linha
    _sincronizar(conta=nubank["id"])
    _cache_coerente(db, payable)
    assert payable.bank_transaction_id == primeiro_movimento

    # (3) TROCAR A DATA
    _sincronizar(conta=nubank["id"], quando=DIA + timedelta(days=5))
    _cache_coerente(db, payable)
    assert payable.bank_transaction_id == primeiro_movimento

    # (4) ESTORNAR — os dois viram NULL juntos
    _sincronizar(conta=None, quando=None)
    _cache_coerente(db, payable)
    assert payable.bank_transaction_id is None

    # (5) REPAGAR — e é aqui que o DELETE do estorno se paga: sem ele, o índice único
    #     `uq_bank_transactions_origin` recusaria esta linha e o repagamento seria impossível.
    _sincronizar(conta=itau["id"])
    _cache_coerente(db, payable)
    assert payable.bank_transaction_id is not None
    assert db.query(BankTransaction).count() == 1


def test_cache_de_movimento_nunca_diverge_do_origin_id_pelos_caminhos_reais(
    client: TestClient, headers, tenant_id, db
):
    """**A extensão da Story 8.12: os mesmos CINCO caminhos, agora pelas ROTAS de produção.**

    O teste acima monta as mutações à mão porque, na 8.9, chamador nenhum existia. A partir desta
    story eles existem e são alcançáveis por HTTP — `POST /bills/{id}/pay`,
    `PATCH /bills/{id}/payment` (conta e data) e `POST /bills/{id}/reverse` —, e é **este** teste
    que prova que o cache (`payable.bank_transaction_id`) nunca diverge do movimento cujo
    `origin_id` é o `payable.id` no fluxo que o usuário realmente percorre.

    ⚠️ Ele substitui, junto com o irmão de cima, o `app/scripts/bank_audit.py` que **não existe** e
    não deve ser criado (ratificação §C-4): condição alcançável só por bug se prova com teste, não
    com script que ninguém tem gatilho para rodar.
    """
    itau = _account(client, headers, name="Itaú PJ")
    nubank = _account(client, headers, name="Nubank PJ", number="99-9")
    quando = OPENING + timedelta(days=5)

    criada = client.post(
        "/payables/bills",
        json={"description": "Aluguel", "category": "Aluguel", "supplier": "Imobiliária Central",
              "amount_cents": 120_00, "due_date": quando.isoformat()},
        headers=headers,
    )
    assert criada.status_code == 201, criada.text
    bill_id = criada.json()["id"]
    payable = db.get(Payable, bill_id)
    _cache_coerente(db, payable)  # (0) antes da baixa: os dois NULL

    def _refrescar() -> None:
        db.expire_all()

    # (1) BAIXAR
    resp = client.post(
        f"/payables/bills/{bill_id}/pay",
        json={"bank_account_id": itau["id"], "paid_on": quando.isoformat()},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    _refrescar()
    _cache_coerente(db, payable)
    primeiro_movimento = payable.bank_transaction_id
    assert primeiro_movimento is not None
    assert payable.bank_account_id == itau["id"]

    # (2) TROCAR A CONTA — move, nunca duplica
    assert client.patch(
        f"/payables/bills/{bill_id}/payment",
        json={"bank_account_id": nubank["id"]},
        headers=headers,
    ).status_code == 200
    _refrescar()
    _cache_coerente(db, payable)
    assert payable.bank_transaction_id == primeiro_movimento
    assert payable.bank_account_id == nubank["id"]

    # (3) TROCAR A DATA
    assert client.patch(
        f"/payables/bills/{bill_id}/payment",
        json={"paid_on": (quando + timedelta(days=2)).isoformat()},
        headers=headers,
    ).status_code == 200
    _refrescar()
    _cache_coerente(db, payable)
    assert payable.bank_transaction_id == primeiro_movimento

    # (4) ESTORNAR — os dois viram NULL juntos
    assert client.post(f"/payables/bills/{bill_id}/reverse", headers=headers).status_code == 200
    _refrescar()
    _cache_coerente(db, payable)
    assert payable.bank_transaction_id is None and payable.bank_account_id is None

    # (5) REPAGAR — sem o DELETE do estorno, `uq_bank_transactions_origin` recusaria esta linha
    assert client.post(
        f"/payables/bills/{bill_id}/pay",
        json={"bank_account_id": itau["id"], "paid_on": quando.isoformat()},
        headers=headers,
    ).status_code == 200
    _refrescar()
    _cache_coerente(db, payable)
    assert payable.bank_transaction_id is not None
    assert db.query(BankTransaction).count() == 1


# ── Quem pode chamar o sincronizador: a ALLOWLIST (8.9 → 8.12) ───────────────────────────────

# ⚠️ **Sucessor direto de `test_nenhum_chamador_de_producao_ainda` (Story 8.9).** Aquele gate
# afirmava "zero chamadores de produção" e a própria docstring dele mandava, verbatim: *"este teste
# vai falhar quando você ligar `apply_paid` ao sincronizador, e isso é o comportamento correto.
# Atualize-o com a lista de chamadores legítimos — **nunca o apague**"*. É o que a 8.12 fez: o gate
# **não foi removido**, ele passou de "nenhum" para "só estes, e por este motivo", que é uma
# condição ESTRITAMENTE mais forte do que "nenhum" seria depois de existir um chamador legítimo.
_CHAMADORES_PERMITIDOS: dict[str, str] = {
    "modules/bank/origin.py": (
        "o próprio sincronizador — dono do contrato e ÚNICO escritor de `SOURCES_SISTEMA`."
    ),
    "modules/payables/service.py": (
        "**Story 8.12** — a baixa de Contas a Pagar é o PRIMEIRO chamador de produção da Regra da "
        "Origem. `apply_paid`/`update_payment`/`reverse_payable` chamam o sincronizador (por "
        "`_sincroniza_movimento`, um ponto só dentro do módulo) na MESMA transação do lançamento. "
        "A direção de import `payables → bank` é permitida (Regra dos Planos §1.3d); a volta é "
        "proibida e `test_bank_nao_importa_payables` a reprova."
    ),
    "modules/bank/transfers.py": (
        "**Story 8.18** — a transferência entre contas próprias é o TERCEIRO chamador de produção "
        "da Regra da Origem, e o único que chama o sincronizador **duas vezes por operação**: uma "
        "perna `:out` (negativa, na conta de origem) e uma `:in` (positiva, na de destino), na "
        "MESMA transação do `bank_transfer`, pareadas pelo kwarg `transfer_id`. "
        "⚠️ **É o único chamador que vive DENTRO do próprio módulo `bank`** — e isso não afrouxa "
        "nada: a permissão continua sendo por arquivo, `create_transfer` continua sendo o único "
        "ponto de escrita das pernas, e `delete_transfer` reusa o mesmo sincronizador "
        "(`bank_account_id=None`) em vez de recopiar a guarda da linha puramente sintética."
    ),
    "modules/investments/service.py": (
        "**Onda 2b-i** — o rendimento de aplicação é o QUARTO chamador de produção da Regra da "
        "Origem (`source='yield'`, `amount_cents` POSITIVO, perna única ⇒ `origin_id = charge.id` "
        "sem sufixo). `register_yield` chama o sincronizador na MESMA transação da `Charge` "
        "sintética, depois de um `db.flush()` — o id da Charge tem default Python-side e sem o "
        "flush o `origin_id` nasceria vazio. "
        "⚠️ **A perna NÃO relaxa a IV1 da Story 5.6:** `bank_transactions` é o plano do BANCO; "
        "`Transaction`/`PlatformEarning` são o plano da PLATAFORMA e continuam intocados. Ela "
        "existe porque rendimento move dinheiro numa conta REAL do dono, e um evento assim sem "
        "movimento correspondente é o termo **P3** da pré-condição do gate do Epic 8 — o termo "
        "que esta onda existe para zerar. "
        "Direção `investments → bank` permitida e pré-decidida em `test_money_planes.py`; a "
        "volta (`bank → investments`) segue proibida por dois gates, AST e texto cru."
    ),
    "modules/receivables/service.py": (
        "**Story 8.15** — o recebimento fora do trilho (`settle_off_rail`/`update_off_rail_"
        "payment`) é o SEGUNDO chamador de produção da Regra da Origem, e o primeiro do lado das "
        "ENTRADAS (`source='charge'`, `amount_cents` POSITIVO). Chama o sincronizador por "
        "`_sincroniza_movimento`, um ponto só dentro do módulo, na MESMA transação da baixa. "
        "⚠️ **A permissão é só para o caminho FORA DO TRILHO:** a cobrança paga pelo gateway "
        "(`mark_paid`) continua sem tocar o razão bancário — o dinheiro dela está na Carteira, e "
        "escrever movimento bancário ali seria o cruzamento de planos que originou o épico. A "
        "INVARIANTE DO TRILHO é o que separa os dois, e `tests/test_invariante_do_trilho.py` a "
        "varre. Direção `receivables → bank` permitida (§1.3d); a volta é proibida."
    ),
}


def _mencoes_ao_sincronizador() -> dict[str, list[str]]:
    """`{arquivo: ["arquivo:linha → nome", ...]}` para toda menção AST aos símbolos do módulo.

    Varre por **nome** (`ast.Name`/`ast.Attribute`) e não por import: um `getattr(origin, ...)` ou
    um alias continuam aparecendo, e a pergunta que este gate faz é *"quem toca nisto?"*, não
    *"quem importa isto?"*.
    """
    achados: dict[str, list[str]] = {}
    for path in sorted(APP_DIR.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        rel = path.relative_to(APP_DIR).as_posix()
        for node in ast.walk(tree):
            nome = None
            if isinstance(node, ast.Name):
                nome = node.id
            elif isinstance(node, ast.Attribute):
                nome = node.attr
            if nome in ("sync_origin_movement", "origin_dedup_hash"):
                achados.setdefault(rel, []).append(f"{rel}:{node.lineno} → {nome}")
    return achados


def test_chamadores_do_sincronizador_estao_na_allowlist():
    """**O gate que impede o SEGUNDO caminho de escrita do razão bancário.**

    A Regra da Origem só é auditável enquanto `sync_origin_movement` for o **único** escritor de
    `source ∈ SOURCES_SISTEMA`. Um chamador novo não é proibido — é uma **decisão**, e esta
    allowlist é o lugar onde ela fica escrita (mesmo padrão do `test_tenancy_guard.py`). Quem
    chegar aqui pela 8.15 (recebimento fora do trilho) ou pela 8.18 (transferência) acrescenta a
    entrada **com a justificativa**, e é isso que faz a revisão acontecer.
    """
    fora_da_lista = [
        ocorrencia
        for arquivo, ocorrencias in _mencoes_ao_sincronizador().items()
        if arquivo not in _CHAMADORES_PERMITIDOS
        for ocorrencia in ocorrencias
    ]
    assert not fora_da_lista, (
        "Apareceu um chamador do sincronizador da Regra da Origem fora da allowlist: "
        f"{fora_da_lista}. Se é legítimo (uma story nova ligando o seu fluxo ao razão bancário), "
        "acrescente o arquivo a `_CHAMADORES_PERMITIDOS` **com a justificativa**; se não é, você "
        "está abrindo um segundo caminho de escrita e tornando a Regra da Origem inauditável."
    )


def test_allowlist_do_sincronizador_nao_tem_entrada_morta():
    """A outra metade do gate: **a allowlist não pode permitir o que ninguém mais faz.**

    Sem esta asserção, a lista só cresceria — e uma permissão que sobrevive ao chamador que a
    justificava é exatamente o buraco por onde o próximo caminho de escrita entra sem revisão. É
    também o teste que **cai se a 8.12 for revertida em silêncio**: se `payables/service.py`
    deixar de chamar o sincronizador, o razão bancário volta a nascer vazio e nenhum outro teste
    de comportamento apontaria o motivo.
    """
    mencionam = set(_mencoes_ao_sincronizador())
    mortas = sorted(set(_CHAMADORES_PERMITIDOS) - mencionam)
    assert not mortas, (
        f"Entradas da allowlist sem nenhum uso correspondente: {mortas}. Ou o chamador sumiu (e a "
        "permissão tem de sumir junto), ou o caminho de escrita foi movido para outro arquivo — e "
        "nesse caso a allowlist precisa dizer o arquivo novo."
    )


# ── IV1 / IV2 — DRE, Lucratividade e Projeção intactas ───────────────────────────────────────


def _seed_movimento_financeiro(client: TestClient, headers) -> None:
    """Uma cobrança e uma conta a pagar, para que a DRE do período NÃO seja trivialmente vazia."""
    assert client.post(
        "/receivables/charges",
        json={"description": "Consultoria", "kind": "service", "method": "pix",
              "amount_cents": 300_000, "due_date": "2026-07-10"},
        headers=headers,
    ).status_code == 201
    assert client.post(
        "/payables/bills",
        json={"description": "Aluguel", "category": "Aluguel", "amount_cents": 120_000,
              "due_date": "2026-07-05"},
        headers=headers,
    ).status_code == 201


def test_movimento_de_origem_nao_altera_a_dre(client: TestClient, headers, tenant_id, db):
    """**IV1** — campo a campo, antes e depois. `profitability.py` deriva da DRE, logo coberto.

    A DRE agrega exatamente `charges` + `payables` + `transactions` e filtra `status != canceled`
    nas 4 agregações. Esta story não cria status novo, não muda status de nada e não escreve em
    `charges`/`payables` — só acrescenta colunas nullable que nascem `NULL`.
    """
    _seed_movimento_financeiro(client, headers)
    acc = _account(client, headers)
    antes = asdict(dre_service.dre_report(db, start=date(2026, 7, 1), end=date(2026, 7, 31)))

    _sync(db, tenant_id, bank_account_id=acc["id"], amount_cents=-987_654)
    _sync(db, tenant_id, bank_account_id=acc["id"], amount_cents=123_456, source=SOURCE_CHARGE)
    db.commit()

    depois = asdict(dre_service.dre_report(db, start=date(2026, 7, 1), end=date(2026, 7, 31)))
    assert depois == antes, (
        "A DRE mudou depois de um movimento de origem. Movimento de extrato não é receita nem "
        "despesa de competência — se entrou na DRE, entrou como número inventado."
    )


def test_projecao_so_muda_pela_parcela_do_banco(client: TestClient, headers, tenant_id, db):
    """**IV2** — o acoplamento acidental mais provável desta story, coberto explicitamente.

    Um movimento com `posted_at <= hoje` **entra** no saldo bancário da Projeção — o que é correto e
    é o objetivo do épico. O que este teste garante é que ele entra **só por ali**: a parcela da
    plataforma, o runway e os fluxos não se mexem por acoplamento acidental. E como esta story não
    tem chamador nenhum (ver `test_nenhum_chamador_de_producao_ainda`), na prática a resposta da
    rota é byte a byte a mesma em produção.

    ⚠️ `projection.py` **não é editado por esta story**, e a 8.19 **também não o toca** (a premissa
    dela foi refutada pelo fundador: *"é o saldo real hoje"*).
    """
    _seed_movimento_financeiro(client, headers)
    acc = _account(client, headers)
    hoje = date(2026, 7, 20)
    antes = asdict(projection_service.cash_projection(db, today=hoje))

    _sync(db, tenant_id, bank_account_id=acc["id"], amount_cents=-500_00, posted_at=DIA)
    db.commit()

    depois = asdict(projection_service.cash_projection(db, today=hoje))
    assert depois["saldo_inicial_banco_cents"] == antes["saldo_inicial_banco_cents"] - 500_00
    assert depois["saldo_inicial_plataforma_cents"] == antes["saldo_inicial_plataforma_cents"]
    assert depois["saldo_inicial_origem"] == antes["saldo_inicial_origem"]
    assert depois["overdue_inflow_cents"] == antes["overdue_inflow_cents"]
    assert depois["overdue_outflow_cents"] == antes["overdue_outflow_cents"]
    for w_antes, w_depois in zip(antes["windows"], depois["windows"], strict=True):
        assert w_depois["saldo_projetado_cents"] == w_antes["saldo_projetado_cents"] - 500_00


def test_transfer_id_e_kwarg_do_sincronizador(client: TestClient, headers, tenant_id, db):
    """**AC5, para a Story 8.18:** as duas pernas nascem pareadas, num escritor só.

    O design §8 exige que as duas pernas de uma transferência nasçam com `transfer_id` preenchido; a
    alternativa (*"a 8.18 grava depois"*) seria um **segundo escritor da mesma linha**, que é
    exatamente o que torna a Regra da Origem inauditável. Um kwarg fecha a lacuna sem abrir caminho
    novo. `transfer_id` **já existe** na tabela desde a 0059 — nenhuma migration para ele.

    **Membro:** as duas pernas, com `transfer_id` preenchido e `origin_id` sufixado.
    **Não-membro:** o movimento de `payable` — perna única, `transfer_id=None`.
    """
    origem = _account(client, headers, name="Itaú PJ")
    destino = _account(client, headers, name="Nubank PJ", number="99-9")
    transfer_id = str(uuid4())

    saida = _sync(
        db, tenant_id, source=SOURCE_TRANSFER, origin_id=f"{transfer_id}:out",
        bank_account_id=origem["id"], amount_cents=-800_00, transfer_id=transfer_id,
        description="Transferência entre contas próprias",
    )
    entrada = _sync(
        db, tenant_id, source=SOURCE_TRANSFER, origin_id=f"{transfer_id}:in",
        bank_account_id=destino["id"], amount_cents=800_00, transfer_id=transfer_id,
        description="Transferência entre contas próprias",
    )
    db.commit()

    assert saida.id != entrada.id, (
        "as duas pernas são duas LINHAS — a unidade de sincronização é a perna, não a transferência"
    )
    assert saida.transfer_id == entrada.transfer_id == transfer_id
    assert {saida.origin_id, entrada.origin_id} == {f"{transfer_id}:out", f"{transfer_id}:in"}
    # Não-membro: perna única nasce sem `transfer_id`.
    payable_mov = _sync(db, tenant_id, bank_account_id=origem["id"])
    db.commit()
    assert payable_mov.transfer_id is None
