"""O ciclo da conferência — o corte do termo P4, a legibilidade e o histórico.

O que estes testes protegem, em uma frase: **um número medido sobre base incompleta não é gate.**
O épico já pagou essa lição duas vezes — em 2026-07-30, quando a divergência da Onda 1 media a
ausência de uma porta e teria pedido a onda mais cara; e na Story 8.20, quando a comparação
degenerada emitia 🟢 sobre razão bancário vazio. O ciclo é o instrumento que impede a terceira.
"""
from __future__ import annotations

import inspect
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.modules.bank import reconciliation
from app.modules.bank.models import KIND_CHECKING

# A Onda 3 entrou em `main` neste dia (commit 54bb1d4). É um fato do REPOSITÓRIO — ao contrário da
# data do deploy — e é exatamente por isso que ele serve de piso e a data do deploy não serviria.
MERGE_DA_ONDA_3 = date(2026, 8, 10)

REGISTER = {
    "legal_name": "Ciclos ME",
    "document": "11444777000161",
    "slug": "ciclos",
    "email": "ciclos@example.com",
    "name": "Cora",
    "password": "uma-senha-bem-grande",
}


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _account(
    client: TestClient,
    headers,
    *,
    name: str = "Itaú PJ",
    opening: int = 1_000_000,
    opening_date: date,
    number: str = "",
) -> dict:
    resp = client.post(
        "/bank/accounts",
        json={
            "name": name,
            "kind": KIND_CHECKING,
            "number": number,
            "opening_balance_cents": opening,
            "opening_balance_is_known": True,
            "opening_date": opening_date.isoformat(),
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _declarar(
    client: TestClient, headers, account_id: str, *, balance_cents: int, reference_date: date
) -> dict:
    resp = client.post(
        f"/bank/accounts/{account_id}/checkpoints",
        json={
            "reference_date": reference_date.isoformat(),
            "balance_cents": balance_cents,
        },
        headers=headers,
    )
    assert resp.status_code in (200, 201), resp.text
    return resp.json()


def _lancar(
    client: TestClient, headers, account_id: str, *, amount_cents: int, posted_at: date
) -> dict:
    resp = client.post(
        f"/bank/accounts/{account_id}/transactions",
        json={
            "posted_at": posted_at.isoformat(),
            "amount_cents": amount_cents,
            "description": "movimento",
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ── O corte do termo P4 ──────────────────────────────────────────────────────────────────────


def test_primeiro_ciclo_medivel_nao_antecede_a_onda_3():
    """O único valor deste módulo que depende de um fato FORA do repositório.

    Cravá-lo cedo demais faz o e1p declarar conferido um ciclo cujo termo **P4 nunca foi medido** —
    e o relatório reporta esse termo como zero **por omissão**, que é a leitura errada que já custou
    uma decisão de produto neste épico.

    ⚠️ O piso **não prova** que a data está certa: o deploy não é um fato do repositório, e nenhum
    teste pode sabê-lo. Ele elimina a classe de erro barata (cravar no passado) e deixa registrado,
    para quem mover a data, que existe um piso a mover junto.
    """
    assert reconciliation.PRIMEIRO_CICLO_MEDIVEL > MERGE_DA_ONDA_3


def test_primeiro_ciclo_medivel_e_primeiro_dia_do_mes():
    """O corte é por CICLO, não por dia — um mês medido pela metade não é um mês medido.

    Uma data no meio do mês faria a condição (d) recusar setembro e aceitar outubro sem que nada na
    fronteira de setembro explicasse por quê.
    """
    assert reconciliation.PRIMEIRO_CICLO_MEDIVEL.day == 1


# ── A legibilidade do ciclo ──────────────────────────────────────────────────────────────────
#
# ⚠️ **`primeiro_ciclo_medivel` é INJETADO nestes testes, e o motivo não é conveniência.**
# `PRIMEIRO_CICLO_MEDIVEL` é `2026-09-01`, e as guardas de "data futura" de checkpoint e de
# movimento ancoram no relógio real: **nenhum dado pode ser semeado em setembro/2026 hoje**. Sem a
# injeção, o único caminho exercitável seria o da recusa, e o ramo legível — o que o instrumento
# existe para produzir — nasceria sem teste nenhum. Mesma disciplina do `today` injetável de
# `reconciliation_report`: um veredito que depende do relógio da máquina não é testável.
# `test_o_corte_padrao_e_a_constante` prende o default, para a injeção não virar porta dos fundos.

OPENING_CICLO = date(2026, 7, 1)
# `today` em agosto para que JULHO seja um ciclo FECHADO. Precisa ser passado real: a suíte semeia
# dado pelas rotas, e elas recusam data futura.
HOJE_CICLO = date(2026, 8, 5)
# O corte injetado — julho passa a ser medível e o ramo legível fica exercitável.
CORTE_ABERTO = date(2026, 7, 1)


def _ciclos(db: Session, *, today: date = HOJE_CICLO, corte: date = CORTE_ABERTO):
    return reconciliation.ciclos_da_conferencia(db, today=today, primeiro_ciclo_medivel=corte)


def _mes(ciclos, ano_mes: str) -> reconciliation.CicloDaConferencia:
    """O ciclo daquele mês. Falha alto se não existir — não silencia com `[0]`."""
    achados = [c for c in ciclos if c.ano_mes == ano_mes]
    assert achados, f"esperava o ciclo {ano_mes}, vieram {[c.ano_mes for c in ciclos]}"
    return achados[0]


def test_o_corte_padrao_e_a_constante():
    """A injeção dos testes não pode virar porta dos fundos: o default é a constante."""
    assinatura = inspect.signature(reconciliation.ciclos_da_conferencia)
    assert (
        assinatura.parameters["primeiro_ciclo_medivel"].default
        == reconciliation.PRIMEIRO_CICLO_MEDIVEL
    )


def test_sem_conta_ativa_o_historico_sai_vazio(client: TestClient, headers, db: Session):
    """Condição (a), e ela **não** é redundante com (b).

    Sem conta, `contas == []`, `contas_sem_checkpoint == 0` e os três contadores dão zero: as
    condições (b) e (c) passariam **por vacuidade** e o e1p diria conferido sobre nada. É a mesma
    família do 🟢 sobre razão bancário vazio que a Story 8.20 desfez.
    """
    assert _ciclos(db) == []


def test_ciclo_em_curso_nunca_e_legivel(client: TestClient, headers, db: Session):
    """Um mês pela metade não tem o que declarar, e um `True` provisório que vira `False` amanhã é
    pior que um `False` honesto."""
    _account(client, headers, opening_date=OPENING_CICLO)

    agosto = _mes(_ciclos(db), "2026-08")

    assert agosto.fechado is False
    assert agosto.legivel is False


def test_ciclo_legivel_quando_tudo_bate(client: TestClient, headers, db: Session):
    """O MEMBRO: conta ativa, saldo declarado em dia posterior à abertura, termos zerados, janela
    posterior ao corte."""
    acc = _account(client, headers, opening_date=OPENING_CICLO, opening=1_000_000)
    _lancar(client, headers, acc["id"], amount_cents=250_000, posted_at=date(2026, 7, 10))
    _declarar(
        client, headers, acc["id"], balance_cents=1_250_000, reference_date=date(2026, 7, 31)
    )

    julho = _mes(_ciclos(db), "2026-07")

    assert julho.fechado is True
    assert julho.legivel is True
    assert julho.motivo_nao_legivel is None
    assert julho.total_divergencia_cents == 0
    assert julho.movimentos_no_periodo == 1
    assert julho.valor_movimentado_cents == 250_000


def test_ciclo_dormente_e_legivel_com_denominador_zero(
    client: TestClient, headers, db: Session
):
    """O mês sem movimento **NÃO é recusado** — o volume zerado é que se lê sozinho.

    Recusá-lo esconderia o número em vez de qualificá-lo, o inverso do princípio da Onda 0
    (*suprimir a afirmação, nunca o número*). E um mínimo de N movimentos seria um número inventado
    (Artigo IV).
    """
    acc = _account(client, headers, opening_date=OPENING_CICLO, opening=1_000_000)
    _declarar(
        client, headers, acc["id"], balance_cents=1_000_000, reference_date=date(2026, 7, 31)
    )

    julho = _mes(_ciclos(db), "2026-07")

    assert julho.legivel is True
    assert julho.movimentos_no_periodo == 0
    assert julho.valor_movimentado_cents == 0


def test_conta_sem_saldo_declarado_nomeia_a_conta(client: TestClient, headers, db: Session):
    """Condição (b), e o motivo NOMEIA a conta.

    Um motivo genérico ("conferência incompleta") manda o dono procurar o que já se sabe qual é —
    a lição do UX-001 e das notas por conta.
    """
    _account(client, headers, name="Poupança BB", opening_date=OPENING_CICLO)

    julho = _mes(_ciclos(db), "2026-07")

    assert julho.legivel is False
    assert "Poupança BB" in julho.motivo_nao_legivel


def test_janela_anterior_ao_corte_nao_e_legivel(client: TestClient, headers, db: Session):
    """Condição (d), com o corte REAL: em julho o saque ainda não escrevia movimento bancário, e o
    termo P4 é reportado como zero por omissão."""
    acc = _account(client, headers, opening_date=OPENING_CICLO, opening=1_000_000)
    _declarar(
        client, headers, acc["id"], balance_cents=1_000_000, reference_date=date(2026, 7, 31)
    )

    julho = _mes(_ciclos(db, corte=reconciliation.PRIMEIRO_CICLO_MEDIVEL), "2026-07")

    assert julho.legivel is False
    assert "saque" in julho.motivo_nao_legivel.lower()


def test_precedencia_o_corte_vem_antes_do_saldo(client: TestClient, headers, db: Session):
    """Quando (d) e (b) falham juntas, a frase é a de (d).

    Dizer *"falta o saldo da Poupança"* sobre um mês anterior ao corte mandaria o dono a um ato que
    **não resolve aquele mês** — a ordem é por acionabilidade, não por gosto.
    """
    _account(client, headers, name="Poupança BB", opening_date=OPENING_CICLO)

    julho = _mes(_ciclos(db, corte=reconciliation.PRIMEIRO_CICLO_MEDIVEL), "2026-07")

    assert "saque" in julho.motivo_nao_legivel.lower()
    assert "Poupança BB" not in julho.motivo_nao_legivel


def test_conta_criada_depois_do_mes_nao_torna_o_mes_ilegivel_por_ela(
    client: TestClient, headers, db: Session
):
    """Uma conta cadastrada em agosto não faz o e1p cobrar dela o saldo de julho.

    Membro do conjunto *"contas que devem saldo em julho"*: a aberta em 01/07.
    Não-membro: a aberta em 02/08 — ela não era do dono naquele mês.
    """
    velha = _account(client, headers, name="Itaú PJ", opening_date=OPENING_CICLO)
    _declarar(
        client, headers, velha["id"], balance_cents=1_000_000, reference_date=date(2026, 7, 31)
    )
    _account(client, headers, name="Nubank PJ", opening_date=date(2026, 8, 2), number="9")

    julho = _mes(_ciclos(db), "2026-07")

    assert julho.legivel is True, julho.motivo_nao_legivel
    # ⚠️ O ponto sutil: `reconciliation_report` de julho **inclui** a Nubank (ele confere todas as
    # contas ativas de hoje) e a conta como não avaliada. Dizer "1 conta não avaliada" num ciclo
    # conferido mandaria o dono caçar uma lacuna que não existe.
    assert julho.contas_sem_checkpoint == 0
    assert julho.contas_avaliadas == 1

    # Controle positivo: sem o recorte, o relatório cru de julho realmente acusa a conta nova.
    cru = reconciliation.reconciliation_report(
        db, start=date(2026, 7, 1), end=date(2026, 7, 31), today=HOJE_CICLO
    )
    assert cru.contas_sem_checkpoint == 1


def test_historico_tem_teto_de_seis_meses(client: TestClient, headers, db: Session):
    """Teto de EXIBIÇÃO, não regra de decisão — o PRD marca os "3 ciclos" como suposição do @PM."""
    _account(client, headers, opening_date=date(2025, 1, 1))

    assert len(_ciclos(db)) == reconciliation.MESES_DO_HISTORICO


def test_historico_vem_do_mais_recente_para_o_mais_antigo(
    client: TestClient, headers, db: Session
):
    _account(client, headers, opening_date=date(2026, 5, 1))

    assert [c.ano_mes for c in _ciclos(db)] == ["2026-08", "2026-07", "2026-06", "2026-05"]


def test_o_ciclo_nao_altera_a_divergencia_do_relatorio(
    client: TestClient, headers, db: Session
):
    """ANOTA, NUNCA SUBTRAI, também aqui: o total do ciclo é COPIADO do relatório do mês."""
    acc = _account(client, headers, opening_date=OPENING_CICLO, opening=1_000_000)
    _lancar(client, headers, acc["id"], amount_cents=250_000, posted_at=date(2026, 7, 10))
    _declarar(
        client, headers, acc["id"], balance_cents=2_000_000, reference_date=date(2026, 7, 31)
    )

    julho = _mes(_ciclos(db), "2026-07")
    report = reconciliation.reconciliation_report(
        db, start=date(2026, 7, 1), end=date(2026, 7, 31), today=HOJE_CICLO
    )

    assert julho.total_divergencia_cents == report.total_divergencia_cents
    assert julho.contas_avaliadas == report.contas_avaliadas
    assert julho.contas_sem_checkpoint == report.contas_sem_checkpoint


# ── A rota ───────────────────────────────────────────────────────────────────────────────────


def test_rota_de_ciclos_devolve_o_historico(client: TestClient, headers):
    """A rota não aceita período: o ciclo é o mês, e fronteira escolhível permitiria selecionar a
    janela que produz o número desejado."""
    _account(client, headers, opening_date=OPENING_CICLO)

    resp = client.get("/bank/reconciliation-cycles", headers=headers)

    assert resp.status_code == 200, resp.text
    ciclos = resp.json()["ciclos"]
    assert ciclos, "com conta cadastrada existe pelo menos o ciclo em curso"
    for c in ciclos:
        # O denominador viaja SEMPRE — o contrato não permite o número sem ele.
        assert "movimentos_no_periodo" in c
        assert "valor_movimentado_cents" in c
        assert {"ano_mes", "fechado", "legivel", "motivo_nao_legivel"} <= set(c)


def test_rota_de_ciclos_sem_conta_devolve_lista_vazia(client: TestClient, headers):
    """Não um ciclo corrente de conteúdo nulo: isso seria a condição (a) violada na exibição."""
    resp = client.get("/bank/reconciliation-cycles", headers=headers)

    assert resp.status_code == 200, resp.text
    assert resp.json()["ciclos"] == []


def test_a_conferencia_expoe_o_volume_por_conta(client: TestClient, headers):
    """O contrato HTTP do relatório carrega o denominador por conta, não só o agregado do ciclo."""
    acc = _account(client, headers, opening_date=OPENING_CICLO)
    _lancar(client, headers, acc["id"], amount_cents=250_000, posted_at=date(2026, 7, 10))

    resp = client.get(
        "/bank/reconciliation-report",
        params={"start": "2026-07-01", "end": "2026-07-31"},
        headers=headers,
    )

    assert resp.status_code == 200, resp.text
    conta = resp.json()["contas"][0]
    assert conta["movimentos_no_periodo"] == 1
    assert conta["valor_movimentado_cents"] == 250_000
