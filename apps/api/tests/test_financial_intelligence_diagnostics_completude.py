"""A completude ponta a ponta: da conta bancária real até o `GET /financial-intelligence/
diagnostics` (Story 8.6, AC7/AC8, IV3/IV4).

O motor puro é testado sem banco em `test_financial_intelligence_completeness.py`. **Aqui** se prova
a outra metade: que `diagnostics.py` — a única camada de I/O desta story — chama a conferência
da 8.5
e adapta o relatório **sem perder nem inventar informação**, e que o endpoint responde 200 em todos
os estados degradados que existem hoje em produção:

- **zero conta bancária** — o estado de *todos* os tenants no dia do deploy (decisão do fundador:
  o 🟡 aparece para todo mundo, sem opt-in e sem dispensar);
- **conta cadastrada e nenhum saldo declarado** — o "não sei" honesto, sem número inventado;
- **conta com divergência acima da banda** — o 🔴 que nomeia a conta e o valor;
- **sem `ANTHROPIC_API_KEY`** — os sinais são os mesmos; só a narrativa cai para template.

Nada aqui escreve nada além do seed: o diagnóstico é read-only (IV3) e a conferência também.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.modules.financial_intelligence import ai_narrator, diagnostics

REGISTER = {
    "legal_name": "Completude ME",
    "document": "11444777000161",
    "slug": "completude",
    "email": "completude@example.com",
    "name": "Cléa",
    "password": "uma-senha-bem-grande",
}

# Datas ancoradas em HOJE (e não em constantes fixas) porque o endpoint não injeta `today`: as
# guardas de "data futura" de conta/checkpoint/movimento ancoram no relógio real, e um período fixo
# no passado deixaria de conter os dados conforme o tempo passa.
TODAY = datetime.now(UTC).date()
START = TODAY - timedelta(days=20)
END = TODAY
REF = TODAY - timedelta(days=2)


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _account(client: TestClient, headers, *, name: str, opening: int = 1_000_000) -> dict:
    resp = client.post(
        "/bank/accounts",
        json={
            "name": name,
            "kind": "checking",
            "opening_balance_cents": opening,
            "opening_date": START.isoformat(),
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _declarar(client: TestClient, headers, account_id: str, *, balance_cents: int,
              reference_date: date = REF) -> None:
    resp = client.post(
        f"/bank/accounts/{account_id}/checkpoints",
        json={"reference_date": reference_date.isoformat(), "balance_cents": balance_cents},
        headers=headers,
    )
    assert resp.status_code in (200, 201), resp.text


def _diagnostics(client: TestClient, headers) -> dict:
    resp = client.get(
        f"/financial-intelligence/diagnostics?start={START.isoformat()}&end={END.isoformat()}",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _completude(payload: dict) -> list[dict]:
    return [s for s in payload["signals"] if s["source"] == "completude"]


# ── IV4 (a) — zero conta bancária: o estado de TODOS os tenants hoje ──────────────────────────


def test_tenant_sem_conta_bancaria_recebe_o_amarelo_e_o_endpoint_responde_200(
    client: TestClient, headers
) -> None:
    """Nenhuma conta cadastrada → 🟡 "não sei", endpoint 200, nada quebra.

    É a mudança visível em produção no dia do deploy, e ela é deliberada: sem conta cadastrada o
    diagnóstico realmente não sabe se os lançamentos estão completos."""
    payload = _diagnostics(client, headers)
    sinais = _completude(payload)
    assert len(sinais) == 1
    assert sinais[0]["level"] == "amarelo"
    assert "Nenhuma conta bancária cadastrada" in sinais[0]["explanation"]
    # O contrato de saída NÃO mudou (AC10): nenhum campo novo em SignalOut.
    assert set(sinais[0]) == {"level", "title", "explanation", "source"}


# ── IV4 (b) — conta cadastrada e nenhum saldo declarado ───────────────────────────────────────


def test_conta_sem_checkpoint_diz_que_nao_sabe_sem_inventar_numero(
    client: TestClient, headers
) -> None:
    _account(client, headers, name="Itaú PJ")
    sinais = _completude(_diagnostics(client, headers))
    assert len(sinais) == 1, f"1 conta = no máximo 1 🟡 de 'não sei': {sinais}"
    assert sinais[0]["level"] == "amarelo"
    assert "Itaú PJ" in sinais[0]["explanation"]
    assert "nunca confirmado" in sinais[0]["explanation"]
    # `None` não virou zero em lugar nenhum do caminho: nada afirma que está batendo.
    assert "batendo" not in sinais[0]["explanation"]


# ── IV4 (c) — divergência acima da banda: o 🔴 que nomeia a conta ─────────────────────────────


def test_divergencia_acima_da_banda_vira_vermelho_nomeando_a_conta(
    client: TestClient, headers
) -> None:
    """Saldo declarado R$ 100,00 abaixo do derivado → o banco tem menos do que o sistema calculou:
    provável **saída** não lançada (REQ-14), acima da banda de R$ 50,00."""
    conta = _account(client, headers, name="Bradesco PJ", opening=1_000_000)
    _declarar(client, headers, conta["id"], balance_cents=990_000)

    sinais = _completude(_diagnostics(client, headers))
    vermelhos = [s for s in sinais if s["level"] == "vermelho"]
    assert len(vermelhos) == 1, sinais
    assert "Bradesco PJ" in vermelhos[0]["explanation"]
    assert "R$ 100,00" in vermelhos[0]["explanation"]
    assert "provavelmente faltam lançamentos de saída" in vermelhos[0]["explanation"]


def test_duas_contas_fora_da_banda_geram_dois_vermelhos_e_nunca_o_consolidado(
    client: TestClient, headers
) -> None:
    """O cenário do fundador (F3) atravessando a camada de I/O real: +R$ 1.200 e −R$ 900 em contas
    diferentes NÃO viram "+R$ 300 consolidado" — viram dois sinais, cada um com a sua conta."""
    itau = _account(client, headers, name="Itaú PJ", opening=1_000_000)
    bradesco = _account(client, headers, name="Bradesco PJ", opening=1_000_000)
    _declarar(client, headers, itau["id"], balance_cents=1_120_000)  # +R$ 1.200
    _declarar(client, headers, bradesco["id"], balance_cents=910_000)  # −R$ 900

    sinais = _completude(_diagnostics(client, headers))
    vermelhos = [s for s in sinais if s["level"] == "vermelho"]
    assert len(vermelhos) == 2, sinais
    texto = " ".join(s["explanation"] for s in sinais)
    assert "Itaú PJ" in texto and "Bradesco PJ" in texto
    assert "R$ 1.200,00" in texto and "R$ 900,00" in texto
    assert "300" not in texto, f"o consolidado vazou para o diagnóstico: {texto}"


def test_conta_conferida_e_dentro_da_banda_fica_verde_e_silenciosa(
    client: TestClient, headers
) -> None:
    """Divergência de R$ 3,50 num saldo de R$ 10.000 → 🟢 e silêncio (a banda da 8.5, intacta)."""
    conta = _account(client, headers, name="Itaú PJ", opening=1_000_000)
    _declarar(client, headers, conta["id"], balance_cents=1_000_350)

    sinais = _completude(_diagnostics(client, headers))
    assert [s["level"] for s in sinais] == ["verde"]
    assert "Está tudo batendo" in sinais[0]["explanation"]
    assert "R$ 3,50" in sinais[0]["explanation"]


# ── Story 8.20 — o 🟢 FALSO: saldo declarado na própria data de abertura ──────────────────────


def test_saldo_declarado_na_data_de_abertura_nao_produz_verde_de_completude(
    client: TestClient, headers
) -> None:
    """**O teste de maior valor da Story 8.20.** O dono cadastra a conta e informa o saldo no mesmo
    dia — o passo 1 do mutirão, e o estado vivo do tenant do fundador.

    Antes desta correção o relatório comparava `opening_balance_cents` com
    `derived_balance(until=opening_date)`, que são **iguais por definição da fórmula**
    (`_movements_sums` só soma `posted_at > opening_date`). Divergência zero **por construção**,
    dentro de qualquer banda, `dias == 0` → `todas_batendo` verdadeiro → 🟢 *"Está tudo batendo"*
    para um tenant com **zero movimento** no razão bancário. O épico inteiro existe para medir isso,
    e este caso o enganava.

    A asserção é a **ausência de qualquer sinal `level=verde` com `source="completude"`**, e não a
    ausência de uma string: a string muda, o verde não. E o que sobra é 🟡 — porque o produto
    realmente **não sabe** se os lançamentos estão completos.
    """
    conta = _account(client, headers, name="C6 PJ", opening=0)
    # `opening_date` das contas desta suíte é `START` — declarar em `START` é declarar no dia do
    # cadastro, exatamente o caso degenerado.
    _declarar(client, headers, conta["id"], balance_cents=0, reference_date=START)

    sinais = _completude(_diagnostics(client, headers))
    assert [s for s in sinais if s["level"] == "verde"] == [], (
        "o 🟢 'está tudo batendo' foi emitido a partir de uma comparação do saldo de abertura com "
        "ele mesmo — o sistema se auto-aprovou sobre um razão bancário vazio"
    )
    assert len(sinais) == 1, f"1 conta = no máximo 1 🟡 de 'não sei': {sinais}"
    assert sinais[0]["level"] == "amarelo"
    assert "C6 PJ" in sinais[0]["explanation"]
    assert "sem comparação avaliável no período" in sinais[0]["explanation"]
    # O bloco 4 continua contando a declaração (AC8): ela é recente, então NÃO entra como motivo.
    assert "nunca confirmado" not in sinais[0]["explanation"], (
        "o bloco 4 foi silenciado junto com o bloco 1: o dono DECLAROU de fato — o degenerado é a "
        "comparação, não a declaração"
    )


# ── IV4 (d) — sem `ANTHROPIC_API_KEY`: os sinais são os mesmos ────────────────────────────────


def test_sinais_de_completude_identicos_com_e_sem_chave_de_ia(
    client: TestClient, headers, monkeypatch
) -> None:
    """A IA nunca origina um sinal de completude — só reescreve a narrativa (Story 5.8, AC2)."""
    conta = _account(client, headers, name="Itaú PJ")
    _declarar(client, headers, conta["id"], balance_cents=990_000)

    monkeypatch.setattr(ai_narrator.settings, "anthropic_api_key", "", raising=False)
    sem_chave = _diagnostics(client, headers)
    assert sem_chave["narrative_source"] == "template"

    monkeypatch.setattr(ai_narrator.settings, "anthropic_api_key", "sk-ant-inexistente",
                        raising=False)
    com_chave = _diagnostics(client, headers)
    # A chamada à Anthropic falha (chave inválida, sem rede) e cai no template — o que importa é
    # que os SINAIS não se moveram.
    assert _completude(com_chave) == _completude(sem_chave)


# ── AC7 — a adaptação relatório → entrada do motor, sem perda e sem agregação ─────────────────


def test_completeness_mapeia_uma_entrada_por_conta_sem_agregar(
    client: TestClient, headers, db: Session
) -> None:
    """`_completeness` é 1:1 com `ConferenciaConta` — sem `max()`, sem colapso, sem invenção.

    `dias_desde_ultima_conferencia` chega **por conta** (ratificação D-2, Ajuste 1): uma conta
    conferida há 2 dias e outra nunca conferida não são "o pior dos dois"."""
    conta = _account(client, headers, name="Itaú PJ")
    _account(client, headers, name="Bradesco PJ")
    _declarar(client, headers, conta["id"], balance_cents=1_000_000)

    entrada = diagnostics._completeness(db, start=START, end=END, today=TODAY)
    # A ordem é a da 8.5 (`service.list_accounts`, por nome) — adaptada sem reordenar.
    assert [c.account_name for c in entrada.contas] == ["Bradesco PJ", "Itaú PJ"]
    bradesco, itau = entrada.contas
    assert itau.divergencia_cents == 0 and itau.dias_desde_ultima_conferencia == 2
    # A conta sem checkpoint fica NÃO AVALIÁVEL — e não "zero, batendo".
    assert bradesco.divergencia_cents is None
    assert bradesco.dias_desde_ultima_conferencia is None
    # A banda vem PRONTA da 8.5 (max(R$ 50; 0,5% de R$ 10.000) = R$ 50,00).
    assert itau.tolerancia_cents == 5_000
    # AC6 — dormente na Onda 1, e é 0 LITERAL (nunca uma aproximação por "movimentos unmatched").
    assert entrada.movimentos_sem_contrapartida == 0


def test_completeness_de_tenant_sem_conta_e_lista_vazia(db: Session) -> None:
    """Sem conta cadastrada a adaptação devolve `contas=[]` — não levanta, não inventa conta."""
    entrada = diagnostics._completeness(db, start=START, end=END, today=TODAY)
    assert entrada.contas == []
    assert entrada.movimentos_sem_contrapartida == 0


# ── IV3 — o eixo em produção segue intacto ────────────────────────────────────────────────────


def test_diagnostico_continua_emitindo_os_sinais_das_outras_origens(
    client: TestClient, headers
) -> None:
    """A completude entrou SEM apagar as demais regras: o sinal 🟡 de investimento (5.6) continua
    lá, ao lado do de completude, e a narrativa continua sendo montada normalmente."""
    r = client.post(
        "/investments",
        json={"name": "CDB Reserva", "principal_cents": 100_000,
              "opened_at": START.isoformat()},
        headers=headers,
    )
    assert r.status_code == 201, r.text

    payload = _diagnostics(client, headers)
    fontes = {s["source"] for s in payload["signals"]}
    assert "investimento" in fontes and "completude" in fontes
    assert payload["narrative"], "a narrativa não pode sumir por causa do sinal novo"
