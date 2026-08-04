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

from datetime import UTC, date, datetime, time, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.modules.financial_intelligence import ai_narrator, diagnostics, engine
from app.modules.payables import service as payables_service
from app.modules.payables.models import Payable
from app.modules.receivables.models import Charge

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


def _account(
    client: TestClient,
    headers,
    *,
    name: str,
    opening: int = 1_000_000,
    opening_date: date = START,
) -> dict:
    resp = client.post(
        "/bank/accounts",
        json={
            "name": name,
            "kind": "checking",
            "opening_balance_cents": opening,
            "opening_date": opening_date.isoformat(),
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
    assert "sem comparação avaliável no período" in sinais[0]["explanation"]
    # Story 8.19 — o motivo "nunca confirmado" SAIU: a conta tem saldo de partida declarado no
    # cadastro (`opening_date` = START, 20 dias atrás), então o bloco 4 conta 20 e não `None`. O 🟡
    # continua saindo, e continua sendo UM só — muda o motivo escrito nele, não o sinal.
    assert "nunca confirmado" not in sinais[0]["explanation"], (
        "o diagnóstico voltou a dizer 'nunca confirmado' a quem informou o saldo de abertura"
    )
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


# ── Story 8.19 — o 🟢 NÃO nasce do bloco 4 passar a contar a partir da abertura ───────────────
#
# **O teste de maior valor da Story 8.19**, porque é o único modo de falha caro que ela poderia
# introduzir. O AC1 troca `dias_desde_ultima_conferencia` de `None` para um número, e o `todas_
# batendo` de `engine._completeness_signals` testa `dias is not None and dias <= 45` — de fora, isso
# parece exatamente o passo que libera o verde. **Não libera**: a guarda que segura o 🟢 é
# `divergencia_cents is not None`, e essa continua `None` sem checkpoint na janela.
#
# É a mesma família do 🟢 falso que a Story 8.20 fechou (`test_saldo_declarado_na_data_de_abertura_
# nao_produz_verde_de_completude`, acima), e a diferença entre os dois cenários é o que prova que
# esta story não o reabre: lá **havia** checkpoint e o defeito era a COMPARAÇÃO ser tautológica;
# aqui não há checkpoint nenhum, `derived_balance` nem é chamada, e o saldo de abertura entra só
# como DATA.


def test_conta_recem_cadastrada_sem_checkpoint_nao_produz_verde_de_completude(
    client: TestClient, headers
) -> None:
    """Conta aberta ONTEM, zero checkpoint: 🟡 e **nenhum** 🟢 — no dia seguinte ao cadastro.

    Com `dias = 1` (bem dentro dos 45 de frescor), os dois últimos termos do `todas_batendo` são
    verdadeiros. Se o verde saísse daqui, todo tenant novo receberia *"Está tudo batendo"* na
    primeira semana de uso, sobre um razão bancário vazio.
    """
    _account(client, headers, name="C6 PJ", opening=0, opening_date=TODAY - timedelta(days=1))

    sinais = _completude(_diagnostics(client, headers))
    assert [s for s in sinais if s["level"] == "verde"] == [], (
        "o 🟢 'está tudo batendo' apareceu numa conta que nunca foi conferida — o bloco 4 passar a "
        "contar a partir da abertura não pode virar lastro para o bloco 1"
    )
    assert len(sinais) == 1, f"1 conta = no máximo 1 🟡 de 'não sei': {sinais}"
    assert sinais[0]["level"] == "amarelo"
    assert "C6 PJ" in sinais[0]["explanation"]
    assert "sem comparação avaliável no período" in sinais[0]["explanation"]
    # O motivo "nunca confirmado" saiu: ela FOI confirmada, no cadastro, há 1 dia.
    assert "nunca confirmado" not in sinais[0]["explanation"]


def test_o_verde_e_segurado_pela_divergencia_e_nao_pelo_contador_de_dias() -> None:
    """A **verificação de que o teste acima não é vazio** — feita sem mutar código de produção.

    O cenário do teste anterior, reproduzido como entrada pura do motor: `divergencia_cents=None`
    (sem checkpoint) e `dias=1` (abertura de ontem). Removida a guarda `divergencia_cents is not
    None` do `todas_batendo`, os três termos restantes ficam **todos verdadeiros** — e o 🟢 sairia.
    É exatamente essa guarda, e só ela, que segura o verde no cenário desta story.

    O predicado abaixo é uma **cópia declarada** do `todas_batendo` de `engine.py` sem o primeiro
    termo: replicá-lo aqui prova a mesma coisa que editar o arquivo de produção e reverter, sem o
    risco de a reversão falhar e o gate ficar morto no repositório.
    """
    conta = engine.CompletenessAccountInput(
        account_name="C6 PJ", divergencia_cents=None, tolerancia_cents=5_000,
        dias_desde_ultima_conferencia=1,
    )
    entrada = engine.CompletenessInput(contas=[conta])

    # Com a guarda (o código real): nenhum verde.
    niveis = [s.level for s in engine._completeness_signals(entrada)]
    assert "verde" not in niveis and niveis == ["amarelo"]

    # Sem a guarda (a mutação): os termos restantes passam todos — o verde sairia.
    sem_a_guarda = (
        abs(conta.divergencia_cents or 0) <= conta.tolerancia_cents
        and conta.dias_desde_ultima_conferencia is not None
        and conta.dias_desde_ultima_conferencia <= engine._COMPLETENESS_STALE_DAYS
    )
    assert sem_a_guarda, (
        "o teste acima é VAZIO: sem a guarda de `divergencia_cents` o cenário já não produziria "
        "verde por outro motivo, então ele não estaria provando nada sobre esta story"
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
    # Story 8.19 — o bloco 4 dela conta a partir da DATA DE ABERTURA (START), não `None`. O bloco 1
    # (a linha acima) não se moveu: declaração e comparação são coisas diferentes.
    assert bradesco.dias_desde_ultima_conferencia == (END - START).days == 20
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


# ── Story 8.16 — a camada de I/O das duas regras da Onda 2 ───────────────────────────────────
#
# O motor é testado sem banco em `test_financial_intelligence_onda2_signals.py`. **Aqui** se prova
# a outra metade: que `diagnostics.py` monta as duas populações a partir do banco real, com o
# predicado certo, e que o endpoint continua respondendo 200 em todos os estados.
#
# O teste que mais importa deste bloco é
# `test_o_debito_suspeito_SOBREVIVE_ao_worker_promover_scheduled_para_paid`: a população foi
# ratificada justamente porque a regra literal do design ("payables em `scheduled` cuja data já
# passou") é **código morto** depois do worker. Se a implementação dependesse do estado `scheduled`,
# o sinal existiria entre a meia-noite e a varredura e sumiria depois — e o teste seria verde
# escrevendo o cenário antes do worker rodar.


def _charge(
    db: Session,
    tenant_id: str,
    *,
    valor: int,
    pago_em: date,
    bank_account_id: str | None = None,
    transaction_id: str | None = None,
    external_ref: str | None = None,
    status: str = "paid",
) -> Charge:
    c = Charge(
        tenant_id=tenant_id,
        description="Consultoria",
        amount_cents=valor,
        due_date=pago_em,
        method="pix",
        kind="service",
        status=status,
        external_ref=external_ref,
        bank_account_id=bank_account_id,
        transaction_id=transaction_id,
        paid_at=datetime.combine(pago_em, time.min, tzinfo=UTC),
    )
    db.add(c)
    db.commit()
    return c


def _payable(
    db: Session,
    tenant_id: str,
    *,
    valor: int,
    pago_em: date,
    bank_account_id: str | None = None,
    status: str = "paid",
    supplier: str = "Aluguel",
) -> Payable:
    p = Payable(
        tenant_id=tenant_id,
        description="Despesa",
        category="operacional",
        supplier=supplier,
        amount_cents=valor,
        due_date=pago_em,
        status=status,
        bank_account_id=bank_account_id,
        paid_at=datetime.combine(pago_em, time.min, tzinfo=UTC),
    )
    db.add(p)
    db.commit()
    return p


def _tenant_id(client: TestClient, headers) -> str:
    return client.get("/auth/me", headers=headers).json()["user"]["tenant_id"]


# ── AC3/AC9 — `_off_rail`: o N e o M, os dois com o predicado de rendimento ──────────────────


def test_off_rail_conta_o_numerador_e_o_denominador(client: TestClient, headers, db: Session):
    """*"N dos M recebimentos"* — e o M inclui as DUAS rotas, nunca só a de fora."""
    tenant_id = _tenant_id(client, headers)
    conta = _account(client, headers, name="Itaú PJ")
    # Numerador: dois recebimentos direto na conta do dono.
    _charge(db, tenant_id, valor=140_000, pago_em=REF, bank_account_id=conta["id"])
    _charge(db, tenant_id, valor=60_000, pago_em=REF, bank_account_id=conta["id"])
    # Denominador (e não numerador): um recebimento pelo trilho (tem `transaction_id`).
    _charge(db, tenant_id, valor=300_000, pago_em=REF, transaction_id="tx-do-trilho")

    entrada = diagnostics._off_rail(db, start=START, end=END)
    assert entrada.recebimentos_fora_do_trilho == 2
    assert entrada.recebimentos_total == 3
    assert entrada.valor_fora_do_trilho_cents == 200_000


def test_o_rendimento_de_aplicacao_fica_fora_dos_DOIS_conjuntos(
    client: TestClient, headers, db: Session
):
    """A `Charge` sintética de rendimento **não é recebimento de cliente** — nem N, nem M.

    **Mutante que este teste mata:** tirar o `_not_investment_yield()` do DENOMINADOR. O numerador
    ficaria certo e o *"N dos M"* mentiria para quem usa Investimentos (2 de 4 em vez de 2 de 3),
    que é a mesma família do achado A-1 num conjunto ao lado.
    """
    tenant_id = _tenant_id(client, headers)
    conta = _account(client, headers, name="Itaú PJ")
    _charge(db, tenant_id, valor=140_000, pago_em=REF, bank_account_id=conta["id"])
    _charge(db, tenant_id, valor=300_000, pago_em=REF, transaction_id="tx-do-trilho")
    _charge(db, tenant_id, valor=48_000, pago_em=REF, external_ref="investment:abc")

    entrada = diagnostics._off_rail(db, start=START, end=END)
    assert entrada.recebimentos_fora_do_trilho == 1
    assert entrada.recebimentos_total == 2, "o rendimento inflou o denominador do 'N dos M'"
    assert entrada.valor_fora_do_trilho_cents == 140_000


def test_cobranca_em_aberto_nao_e_recebimento(client: TestClient, headers, db: Session):
    """Não-membro: cobrança `open` na janela — ela não foi recebida, e nem tem `paid_at`."""
    tenant_id = _tenant_id(client, headers)
    _charge(db, tenant_id, valor=140_000, pago_em=REF, status="open").paid_at = None
    db.commit()
    entrada = diagnostics._off_rail(db, start=START, end=END)
    assert (entrada.recebimentos_fora_do_trilho, entrada.recebimentos_total) == (0, 0)


def test_o_sinal_de_recebimento_externo_chega_ao_endpoint(client: TestClient, headers, db: Session):
    """Ponta a ponta: o 🟡 aparece em `GET /financial-intelligence/diagnostics`."""
    tenant_id = _tenant_id(client, headers)
    conta = _account(client, headers, name="Itaú PJ")
    _charge(db, tenant_id, valor=140_000, pago_em=REF, bank_account_id=conta["id"])

    sinais = [s for s in _diagnostics(client, headers)["signals"]
              if s["source"] == "recebimento_externo"]
    assert len(sinais) == 1
    assert sinais[0]["level"] == "amarelo"
    assert "1 dos 1 recebimentos" in sinais[0]["explanation"]
    # O contrato de saída não muda (nenhum campo novo em `SignalOut`).
    assert set(sinais[0]) == {"level", "title", "explanation", "source"}


# ── AC5/AC6/AC9 — `_debitos_suspeitos` ───────────────────────────────────────────────────────


def _cenario_de_debito_suspeito(client, headers, db, *, valor: int = 500_000) -> str:
    """Conta com divergência de **+R$ 5.000** e um débito do mesmo tamanho na janela.

    O saldo derivado fica `opening + (−valor)`; o dono declara o `opening` cheio (o banco ainda não
    executou o débito) ⇒ `divergencia = +valor`.
    """
    tenant_id = _tenant_id(client, headers)
    conta = _account(client, headers, name="Itaú PJ", opening=1_000_000)
    client.post(
        f"/bank/accounts/{conta['id']}/transactions",
        json={"posted_at": REF.isoformat(), "amount_cents": -valor, "description": "Aluguel"},
        headers=headers,
    )
    _declarar(client, headers, conta["id"], balance_cents=1_000_000)
    _payable(db, tenant_id, valor=valor, pago_em=REF, bank_account_id=conta["id"])
    return conta["id"]


def _suspeitos(db: Session) -> list:
    report = diagnostics.bank_reconciliation.reconciliation_report(
        db, start=START, end=END, today=TODAY
    )
    return diagnostics._debitos_suspeitos(
        db, start=START, end=END, report=report, today=TODAY
    )


def test_o_debito_da_janela_vira_candidato_com_a_data_e_o_fornecedor(
    client: TestClient, headers, db: Session
):
    """A população monta `descricao` (o fornecedor), `valor`, `data_debito` e a conta."""
    _cenario_de_debito_suspeito(client, headers, db)
    suspeitos = _suspeitos(db)
    assert len(suspeitos) == 1
    s = suspeitos[0]
    assert s.descricao == "Aluguel"
    assert s.valor_cents == 500_000
    assert s.data_debito == REF
    assert s.bank_account_name == "Itaú PJ"


def test_conta_sem_divergencia_positiva_nao_gera_candidato_nenhum(
    client: TestClient, headers, db: Session
):
    """Sem divergência positiva não há o que explicar — e a busca nem acontece (AC5)."""
    tenant_id = _tenant_id(client, headers)
    conta = _account(client, headers, name="Itaú PJ", opening=1_000_000)
    _declarar(client, headers, conta["id"], balance_cents=1_000_000)  # bate exato
    _payable(db, tenant_id, valor=500_000, pago_em=REF, bank_account_id=conta["id"])
    assert _suspeitos(db) == []


def test_debito_posterior_ao_saldo_declarado_nao_explica_a_divergencia(
    client: TestClient, headers, db: Session
):
    """Não-membro 2: um débito DEPOIS da data do checkpoint não entrou no saldo daquela data.

    Nomeá-lo mandaria o dono conferir no extrato um débito que, por construção, não pode ter
    causado a diferença — e *"nomear um débito inocente é pior do que ficar calado"*.
    """
    tenant_id = _tenant_id(client, headers)
    conta = _account(client, headers, name="Itaú PJ", opening=1_000_000)
    client.post(
        f"/bank/accounts/{conta['id']}/transactions",
        json={"posted_at": REF.isoformat(), "amount_cents": -500_000, "description": "Aluguel"},
        headers=headers,
    )
    _declarar(client, headers, conta["id"], balance_cents=1_000_000)
    # Débito com data POSTERIOR ao `reference_date` do checkpoint.
    _payable(db, tenant_id, valor=500_000, pago_em=REF + timedelta(days=1),
             bank_account_id=conta["id"])
    assert _suspeitos(db) == []


def test_o_debito_suspeito_sobrevive_ao_worker_promover_scheduled_para_paid(
    client: TestClient, headers, db: Session
):
    """**A garantia central da ratificação §C-2: o efeito existe, o adjetivo não.**

    O design pedia *"payables em `scheduled` cuja data já passou"* — e o worker da 8.14 promove
    `scheduled → paid` assim que o dia chega, o que torna a regra literal **código morto**. A
    população ratificada é por **comparação de datas**, não por status materializado: aqui o mesmo
    cenário é medido ANTES e DEPOIS de `promote_scheduled` rodar, e o candidato é o mesmo.

    Se a implementação voltar a depender do estado `scheduled`, a lista fica vazia depois do worker
    e este teste cai — que é exatamente o modo de falha que a renomeação existe para tornar visível.
    """
    tenant_id = _tenant_id(client, headers)
    conta = _account(client, headers, name="Itaú PJ", opening=1_000_000)
    client.post(
        f"/bank/accounts/{conta['id']}/transactions",
        json={"posted_at": REF.isoformat(), "amount_cents": -500_000, "description": "Aluguel"},
        headers=headers,
    )
    _declarar(client, headers, conta["id"], balance_cents=1_000_000)
    # Um débito AGENDADO cuja data já passou — a população "rara" do primeiro ramo.
    p = _payable(db, tenant_id, valor=500_000, pago_em=REF, bank_account_id=conta["id"],
                 status=payables_service.STATUS_SCHEDULED)

    antes = _suspeitos(db)
    assert len(antes) == 1 and antes[0].valor_cents == 500_000

    promovidas = payables_service.promote_scheduled(
        db, tenant_id=tenant_id, actor="worker", today=TODAY
    )
    db.refresh(p)
    assert promovidas == 1 and p.status == payables_service.STATUS_PAID, (
        "o cenário precisa MESMO passar pelo worker para o teste valer"
    )

    depois = _suspeitos(db)
    assert depois == antes, (
        "o débito suspeito sumiu depois do worker — a regra voltou a depender do estado "
        "`scheduled`, que é o código morto que a ratificação §C-2 corrigiu"
    )


def test_o_sinal_de_debito_nao_confirmado_chega_ao_endpoint(
    client: TestClient, headers, db: Session
):
    """Ponta a ponta: o 🟡 que NOMEIA o suspeito, com "pode não ter saído" verbatim."""
    _cenario_de_debito_suspeito(client, headers, db)
    sinais = [s for s in _diagnostics(client, headers)["signals"]
              if s["source"] == "debito_nao_confirmado"]
    assert len(sinais) == 1
    assert sinais[0]["level"] == "amarelo"
    assert "pode não ter saído" in sinais[0]["explanation"]
    assert "R$ 5.000,00" in sinais[0]["explanation"]
    assert "agendad" not in sinais[0]["explanation"].lower()


def test_a_conferencia_e_buscada_uma_vez_so_para_as_duas_regras(
    client: TestClient, headers, db: Session, monkeypatch
):
    """`collect_engine_input` chama `reconciliation_report` **uma vez** (Task 3).

    Duas leituras do mesmo relatório na mesma requisição podem divergir — e as duas regras precisam
    concordar sobre QUAL divergência estão falando, senão o motor nomearia um débito para uma conta
    com um número e explicaria outro.
    """
    _cenario_de_debito_suspeito(client, headers, db)

    chamadas = []
    original = diagnostics.bank_reconciliation.reconciliation_report

    def _espiao(*a, **kw):
        chamadas.append(kw)
        return original(*a, **kw)

    monkeypatch.setattr(
        diagnostics.bank_reconciliation, "reconciliation_report", _espiao
    )
    diagnostics.collect_engine_input(db, start=START, end=END, today=TODAY)
    assert len(chamadas) == 1, f"a conferência foi buscada {len(chamadas)} vezes"


def test_o_endpoint_responde_200_com_as_duas_regras_e_sem_chave_de_ia(
    client: TestClient, headers, db: Session, monkeypatch
):
    """AC11: zero IA nova. Os sinais são idênticos com e sem `ANTHROPIC_API_KEY`."""
    tenant_id = _tenant_id(client, headers)
    conta_id = _cenario_de_debito_suspeito(client, headers, db)
    _charge(db, tenant_id, valor=140_000, pago_em=REF, bank_account_id=conta_id)

    monkeypatch.setattr(ai_narrator.settings, "anthropic_api_key", "", raising=False)
    sem_chave = _diagnostics(client, headers)["signals"]
    monkeypatch.setattr(
        ai_narrator.settings, "anthropic_api_key", "sk-ant-inexistente", raising=False
    )
    com_chave = _diagnostics(client, headers)["signals"]

    assert sem_chave == com_chave
    fontes = {s["source"] for s in sem_chave}
    assert {"recebimento_externo", "debito_nao_confirmado"} <= fontes
