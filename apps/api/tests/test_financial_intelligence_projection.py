"""Testes da projeção de fluxo de caixa 30/60/90 + runway (Story 5.7) — regime de CAIXA, read-only.

Cobre: saldo inicial vem da Carteira (disponível, NÃO recalculado); entradas/saídas abertas dentro
da janela entram (cumulativas), fora não; **IV2 — usa `due_date` (pagamento previsto), NUNCA
`competence_date`**, com um cenário desenhado para dar resultado DIFERENTE se o campo errado fosse
usado; recorrências futuras aparecem automaticamente (constatação da Task 2, sem lógica extra);
runway com burn positivo; runway `None` quando o caixa cresce / não há despesas (divisão por zero
tratada); janela negativa marca `alert`; e **read-only** (nenhuma escrita — IV1).

**Story 8.1 (Onda 0 do Epic 8) — saldo inicial honesto.** A partir daqui o arquivo cobre também:
a declaração de procedência (`saldo_inicial_origem`), a supressão do runway em dias (AC3) e do
`alert` de janela negativa (AC4b) quando a origem é `plataforma`, a distinção entre "sem risco" e
"não sei" (AC4 — o teste de maior valor da story) e o silêncio do diagnóstico (AC6).

⚠️ **Três testes da 5.7 mudaram de expectativa nesta story, e isso é a CORREÇÃO, não regressão**
(autorizado pelo IV5 da 8.1): `test_runway_with_positive_burn` e
`test_overdue_payable_shortens_runway` afirmavam `runway.days == 90` — um número derivado de
premissa errada; a cobertura do cálculo se deslocou para `burn_rate_cents_per_day`, que continua
exposto e continua correto. E
`test_negative_window_sets_alert` virou `test_negative_window_alert_suprimido` (o veredito é calado;
o `saldo_projetado_cents` negativo continua asserido — suprime-se a afirmação, nunca o número).

RLS/isolamento cross-tenant é validado à parte no Postgres real
(test_financial_intelligence_projection_rls.py, marcado `rls_e2e`) — aqui a suíte roda em SQLite e a
RLS não é exercida (ver conftest).
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.money_planes import ORIGEM_PLATAFORMA, ORIGENS
from app.modules.financial_intelligence import diagnostics as diagnostics_service
from app.modules.financial_intelligence import projection as projection_service
from app.modules.payables.models import Payable
from app.modules.receivables.models import Charge
from app.modules.wallet.models import Transaction

REGISTER = {
    "legal_name": "Consultoria Projeção",
    "document": "22333444000181",
    "slug": "projecao",
    "email": "projecao@example.com",
    "name": "Paula",
    "password": "uma-senha-bem-grande",
}

TODAY = datetime.now(UTC).date()


def _d(days: int) -> str:
    """Data ISO de hoje + `days` (âncora UTC, a mesma que o serviço usa)."""
    return (TODAY + timedelta(days=days)).isoformat()


@pytest.fixture()
def headers(client: TestClient) -> dict[str, str]:
    token = client.post("/auth/register", json=REGISTER).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _charge(client, headers, *, amount, due, competence=None) -> dict:
    body = {"kind": "service", "method": "pix", "amount_cents": amount, "due_date": due}
    if competence is not None:
        body["competence_date"] = competence
    r = client.post("/receivables/charges", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def _payable(client, headers, *, amount, due, competence=None, recurrence="none", count=1) -> dict:
    body = {
        "description": "conta",
        "amount_cents": amount,
        "due_date": due,
        "recurrence": recurrence,
        "recurrence_count": count,
    }
    if competence is not None:
        body["competence_date"] = competence
    r = client.post("/payables/bills", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def _seed_available(client, headers, *, gross: int) -> int:
    """Semeia saldo DISPONÍVEL na Carteira via uma venda pix (líquida imediatamente disponível).
    Retorna o líquido creditado (net = gross − split)."""
    tx = client.post(
        "/wallet/transactions",
        json={"kind": "product", "method": "pix", "gross_cents": gross},
        headers=headers,
    ).json()
    assert tx["status"] == "available"
    return tx["net_cents"]


def _projection(client, headers) -> dict:
    r = client.get("/financial-intelligence/projection", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _window(body: dict, days: int) -> dict:
    return next(w for w in body["windows"] if w["days"] == days)


def test_requires_auth(client: TestClient):
    assert client.get("/financial-intelligence/projection").status_code == 401


def test_empty_has_three_windows_and_no_runway(client: TestClient, headers):
    body = _projection(client, headers)
    assert body["saldo_inicial_cents"] == 0
    assert [w["days"] for w in body["windows"]] == [30, 60, 90]
    assert all(w["saldo_projetado_cents"] == 0 and w["alert"] is False for w in body["windows"])
    # sem despesas → sem queima → runway não se aplica (divisão por zero tratada)
    assert body["runway"]["days"] is None
    assert body["runway"]["days_suprimido"] is False  # "sem risco", não "não sei" (8.1 AC4)
    assert body["runway"]["burn_rate_cents_per_day"] == 0
    assert any("CAIXA" in n for n in body["notes"])


def test_initial_balance_comes_from_wallet_not_recalculated(client: TestClient, headers):
    net = _seed_available(client, headers, gross=150000)  # product 40% → net 90000
    body = _projection(client, headers)
    assert net == 90000
    # saldo inicial da projeção é EXATAMENTE o disponível da Carteira (reuso, não recalculado)
    assert body["saldo_inicial_cents"] == 90000


def test_inflows_and_outflows_are_cumulative_within_windows(client: TestClient, headers):
    # entrada dentro de todas as janelas (+20d)
    _charge(client, headers, amount=50000, due=_d(20))
    # saída só a partir de 60 dias (+45d)
    _payable(client, headers, amount=30000, due=_d(45))
    # fora de todas as janelas (+200d) — NÃO deve entrar
    _charge(client, headers, amount=999999, due=_d(200))

    body = _projection(client, headers)
    # cumulativo: 30d = +50000 ; 60d = +50000 −30000 = 20000 ; 90d = 20000
    assert _window(body, 30)["saldo_projetado_cents"] == 50000
    assert _window(body, 60)["saldo_projetado_cents"] == 20000
    assert _window(body, 90)["saldo_projetado_cents"] == 20000
    assert all(w["alert"] is False for w in body["windows"])


def test_empty_projection_has_zero_overdue(client: TestClient, headers):
    body = _projection(client, headers)
    assert body["overdue_inflow_cents"] == 0
    assert body["overdue_outflow_cents"] == 0
    assert not any("VENCIDOS" in n for n in body["notes"])


def test_overdue_open_items_count_as_expected_cash(client: TestClient, headers):
    """Decisão do @architect (Aria, gate da 5.7): itens VENCIDOS e ainda em aberto (atraso/
    inadimplência) ENTRAM na projeção como caixa esperado imediato — em TODAS as janelas — e a
    parcela vencida é exposta à parte. Excluí-los subestimava o caixa e (pior) ocultava contas a
    pagar já vencidas, deixando a projeção otimista demais."""
    # recebível vencido há 5 dias, ainda em aberto → esperado imediato (entra em todas as janelas)
    _charge(client, headers, amount=40000, due=_d(-5))
    # conta a pagar vencida há 3 dias, ainda em aberto → obrigação quase-certa (entra em todas)
    _payable(client, headers, amount=10000, due=_d(-3))
    # um item futuro normal, dentro de todas as janelas, para provar que soma junto ao vencido
    _charge(client, headers, amount=5000, due=_d(20))

    body = _projection(client, headers)
    # vencido líquido = 40000 − 10000 = 30000 (em todas as janelas) + 5000 futuro (em todas) = 35000
    for days in (30, 60, 90):
        assert _window(body, days)["saldo_projetado_cents"] == 35000
    # parcela vencida exposta separadamente (transparência da incerteza)
    assert body["overdue_inflow_cents"] == 40000
    assert body["overdue_outflow_cents"] == 10000
    assert any("VENCIDOS" in n for n in body["notes"])


def test_overdue_payable_shortens_runway(client: TestClient, headers):
    """Uma conta a pagar VENCIDA e em aberto é obrigação quase-certa: deve pesar no burn, não ficar
    invisível (o risco que a exclusão criava — projeção otimista demais).

    **[Story 8.1 / IV5] Atualizado:** este teste afirmava `runway.days == 90`. Com o saldo inicial
    de origem `plataforma`, os dias são SUPRIMIDOS (AC3) — o número que preserva a intenção original
    ("a obrigação vencida pesa e não fica invisível") é o `burn_rate_cents_per_day`, que continua
    exposto e continua exatamente 1000, mais o `overdue_outflow_cents`."""
    _seed_available(client, headers, gross=150000)  # disponível 90000
    _payable(client, headers, amount=90000, due=_d(-2))  # vencida há 2 dias, ainda aberta
    body = _projection(client, headers)
    # a saída vencida entra no burn de 90d: 90000/90 = 1000/dia — o cálculo NÃO mudou (AC7)
    assert body["runway"]["burn_rate_cents_per_day"] == 1000
    # ...mas os "90 dias" que dele derivavam via saldo inicial contaminado são calados (AC3)
    assert body["runway"]["days"] is None
    assert body["runway"]["days_suprimido"] is True
    assert body["overdue_outflow_cents"] == 90000


def test_negative_window_alert_suprimido(client: TestClient, headers):
    """**[Story 8.1 / AC4b / IV5]** Substitui `test_negative_window_sets_alert` da 5.7.

    Suprima a AFIRMAÇÃO, nunca o NÚMERO: o `saldo_projetado_cents` negativo continua sendo calculado
    e exposto **exatamente igual** (AC7) — só o veredito "seu caixa fica negativo" é calado, porque
    ele é um cruzamento de limiar sobre uma soma que parte do disponível da Carteira e1p e não do
    saldo da conta bancária (§6.1.2)."""
    # sem saldo inicial e uma saída grande em +10d → saldo projetado negativo em todas as janelas
    _payable(client, headers, amount=100000, due=_d(10))
    body = _projection(client, headers)
    for days in (30, 60, 90):
        w = _window(body, days)
        assert w["saldo_projetado_cents"] == -100000, "o NÚMERO não pode ser suprimido nem alterado"
        assert w["alert"] is False, "a AFIRMAÇÃO de caixa negativo deve ser calada na Onda 0"
        assert w["alert_suprimido"] is True
    # a nota diz ao usuário que o número está lá e que o veredito é que não existe
    assert any("não afirma se o seu caixa fica negativo" in n for n in body["notes"])


def test_uses_due_date_not_competence_date(client: TestClient, headers):
    """IV2 — a projeção usa `due_date` (pagamento previsto), NUNCA `competence_date`.

    Cenário desenhado para DIVERGIR: se o código usasse `competence_date` por engano, o resultado da
    janela de 30d seria 99999; usando `due_date` (correto) é 40000."""
    # A: vence dentro da janela (+10d), mas competência lá na frente (+200d) → DEVE entrar (due)
    _charge(client, headers, amount=40000, due=_d(10), competence=_d(200))
    # B: competência dentro da janela (+10d), mas vence fora (+200d) → NÃO deve entrar (due_date)
    _charge(client, headers, amount=99999, due=_d(200), competence=_d(10))

    body = _projection(client, headers)
    saldo_30 = _window(body, 30)["saldo_projetado_cents"]
    assert saldo_30 == 40000, "projeção não usou due_date (regime de caixa) — usou competência?"
    assert saldo_30 != 99999


def test_future_recurrence_occurrences_appear_without_extra_logic(client: TestClient, headers):
    """Task 2 (AC3): cada ocorrência recorrente já é uma linha própria com seu vencimento — a
    projeção as captura pela mesma query, sem reimplementar recorrência."""
    # mensal, 3x, começando em +5d → ocorrências ~ +5d, +~35d, +~65d
    created = _payable(client, headers, amount=10000, due=_d(5), recurrence="monthly", count=3)
    assert created["recurrence_count"] == 3

    body = _projection(client, headers)
    # 30d pega 1 ocorrência (−10000); 60d pega 2 (−20000); 90d pega 3 (−30000)
    assert _window(body, 30)["saldo_projetado_cents"] == -10000
    assert _window(body, 60)["saldo_projetado_cents"] == -20000
    assert _window(body, 90)["saldo_projetado_cents"] == -30000


def test_runway_with_positive_burn(client: TestClient, headers):
    """**[Story 8.1 / IV5] Atualizado:** afirmava `runway.days == 90`. Com origem `plataforma` os
    dias são suprimidos (AC3); a cobertura do CÁLCULO se desloca para `burn_rate_cents_per_day`,
    que não está contaminado (deriva de contas em aberto, não do saldo inicial) e segue idêntico."""
    _seed_available(client, headers, gross=150000)  # disponível 90000
    _payable(client, headers, amount=90000, due=_d(10))  # queima 90000 na janela de 90d
    body = _projection(client, headers)
    # burn diário = 90000 / 90 = 1000 — o cálculo é o mesmo de antes da 8.1 (AC7)
    assert body["runway"]["burn_rate_cents_per_day"] == 1000
    assert body["runway"]["days"] is None
    assert body["runway"]["days_suprimido"] is True


def test_runway_none_when_cash_is_growing(client: TestClient, headers):
    _seed_available(client, headers, gross=100000)  # disponível 60000
    _charge(client, headers, amount=80000, due=_d(10))  # entrada líquida → caixa cresce
    body = _projection(client, headers)
    assert body["runway"]["days"] is None
    # sem queima → não há o que suprimir; este "None" é "sem risco", não "não sei" (8.1 AC4)
    assert body["runway"]["days_suprimido"] is False
    assert body["runway"]["burn_rate_cents_per_day"] == 0
    assert any("risco" in n.lower() for n in body["notes"])


def test_runway_none_when_no_expenses(client: TestClient, headers):
    _seed_available(client, headers, gross=100000)  # disponível, sem nenhuma despesa
    body = _projection(client, headers)
    # sem burn rate → divisão por zero evitada explicitamente
    assert body["runway"]["days"] is None
    assert body["runway"]["days_suprimido"] is False
    assert body["runway"]["burn_rate_cents_per_day"] == 0


# ── Story 8.1 — saldo inicial honesto (procedência declarada + inferências caladas) ────────────


def test_projecao_declara_origem_do_saldo_inicial(client: TestClient, headers):
    """**[8.1 AC1]** O teste nomeado no design §1.3 (item 4) e no §8 Onda 0 AC3: nenhum saldo
    trafega sem procedência (Regra dos Planos §1.3c). Na Onda 0 o valor é sempre `plataforma` (não
    existe `bank_accounts` ainda), mas o CONTRATO é "preenchido e pertence a `ORIGENS`", para que a
    Story 8.8 troque o valor sem tocar em nenhum consumidor."""
    _seed_available(client, headers, gross=150000)
    body = _projection(client, headers)
    assert body["saldo_inicial_origem"] in ORIGENS
    assert body["saldo_inicial_origem"] == ORIGEM_PLATAFORMA
    # o NÚMERO não muda por ter ganhado um rótulo (AC7)
    assert body["saldo_inicial_cents"] == 90000


def test_origem_declarada_mesmo_com_carteira_zerada(client: TestClient, headers):
    """Procedência não é um enfeite do caso feliz: saldo 0 também é um saldo, e também precisa
    declarar de onde veio (senão o campo vira opcional na prática)."""
    body = _projection(client, headers)
    assert body["saldo_inicial_cents"] == 0
    assert body["saldo_inicial_origem"] == ORIGEM_PLATAFORMA


def test_note_de_origem_plataforma_presente(client: TestClient, headers):
    """**[8.1 AC2]** A nota é explícita, não eufemística: diz de onde o número vem E o que ele
    não é. O campo `notes` já existe exatamente para isso (`_NOTE_CAIXA`, `_NOTE_OVERDUE`)."""
    body = _projection(client, headers)
    assert any(
        "Carteira e1p" in n and "não da sua conta bancária" in n for n in body["notes"]
    ), "faltou a nota que declara a procedência do saldo inicial"
    # ...e a nota do regime caixa×competência continua com a responsabilidade dela, só que sem
    # acumular a frase de procedência (que agora tem nota própria)
    assert any("Regime de CAIXA" in n for n in body["notes"])


def test_runway_suprimido_quando_origem_plataforma_e_ha_queima(client: TestClient, headers):
    """**[8.1 AC3]** Havendo queima e saldo inicial de origem `plataforma`, os dias são calados —
    mas a queima diária NÃO é: ela vem das contas em aberto (`due_date`), não do saldo inicial."""
    _seed_available(client, headers, gross=150000)  # disponível 90000
    _payable(client, headers, amount=90000, due=_d(10))
    body = _projection(client, headers)

    assert body["runway"]["days"] is None
    assert body["runway"]["days_suprimido"] is True
    assert body["runway"]["burn_rate_cents_per_day"] > 0, "a queima NÃO é suprimida"
    assert body["runway"]["burn_rate_cents_per_day"] == 1000
    assert any("fôlego de caixa em dias não é exibido" in n for n in body["notes"])


def test_runway_sem_risco_nao_marca_suprimido(client: TestClient, headers):
    """**[8.1 AC4] — o teste de maior valor da story.** "Sem risco" (eu sei, e está tudo bem) e
    "não sei" (não tenho lastro) nunca compartilham nota nem mensagem. Trocar "faltam 43 dias"
    (falso preciso) por "sem risco" (falso tranquilizador) é PIOR que o bug original: o primeiro
    erra um número, o segundo dá permissão para gastar."""
    _seed_available(client, headers, gross=100000)  # disponível 60000
    _charge(client, headers, amount=80000, due=_d(10))  # entrada líquida → caixa cresce
    body = _projection(client, headers)

    assert body["runway"]["days"] is None
    assert body["runway"]["days_suprimido"] is False
    assert body["runway"]["burn_rate_cents_per_day"] == 0
    # a nota de "sem risco" da 5.7 continua — essa afirmação não depende do saldo inicial
    assert any("sem risco de runway" in n for n in body["notes"])
    # ...e a de supressão está AUSENTE (as duas situações nunca coexistem)
    assert not any("fôlego de caixa em dias não é exibido" in n for n in body["notes"])


def test_caso_suprimido_nao_emite_nota_de_sem_risco(client: TestClient, headers):
    """**[8.1 AC4, o recíproco]** A guarda que o design chama de "a armadilha que anula o
    benefício": a condição da nota de "sem risco" passou de `runway_days is None` para
    `runway_days is None and not days_suprimido`. Sem ela, o caso suprimido herda a nota errada."""
    _seed_available(client, headers, gross=150000)
    _payable(client, headers, amount=90000, due=_d(10))  # há queima → supressão
    body = _projection(client, headers)

    assert body["runway"]["days_suprimido"] is True
    assert not any("sem risco" in n.lower() for n in body["notes"])


def test_alert_suprimido_mantem_saldo_projetado_e_nota_propria(client: TestClient, headers):
    """**[8.1 AC4b]** O alerta é calado em QUALQUER janela contaminada — inclusive quando não há
    queima líquida (a condição do `alert`, ao contrário da do runway, não olha `burn_rate`)."""
    _seed_available(client, headers, gross=150000)  # disponível 90000
    # saída grande dentro de 30d + entrada maior ainda em 90d → burn líquido de 90d é ZERO...
    _payable(client, headers, amount=200000, due=_d(10))
    _charge(client, headers, amount=500000, due=_d(80))
    body = _projection(client, headers)

    assert body["runway"]["burn_rate_cents_per_day"] == 0, "cenário: sem queima líquida em 90d"
    assert body["runway"]["days_suprimido"] is False, "sem queima → nada de runway a suprimir"
    # ...e mesmo assim a janela de 30d, que fica negativa, tem o veredito calado
    w30 = _window(body, 30)
    assert w30["saldo_projetado_cents"] == -110000, "o número continua exposto e inalterado"
    assert w30["alert"] is False
    assert w30["alert_suprimido"] is True
    assert any("não afirma se o seu caixa fica negativo" in n for n in body["notes"])


def test_invariantes_de_supressao_valem_em_todos_os_cenarios(client: TestClient, headers):
    """**[8.1, invariantes de contrato]** `days_suprimido ⇒ days is None` e
    `alert_suprimido ⇒ alert is False`. Nenhum consumidor deve precisar tratar "suprimido, mas com
    valor" — se um dia a supressão for aplicada ANTES do cálculo (ou esquecida), isto pega."""
    _seed_available(client, headers, gross=150000)
    _payable(client, headers, amount=90000, due=_d(10))
    _charge(client, headers, amount=5000, due=_d(-1))
    body = _projection(client, headers)

    runway = body["runway"]
    if runway["days_suprimido"]:
        assert runway["days"] is None
    for w in body["windows"]:
        if w["alert_suprimido"]:
            assert w["alert"] is False


def test_diagnostico_nao_emite_nenhum_sinal_de_projecao_na_onda_0(
    client: TestClient, headers, db: Session
):
    """**[8.1 AC6]** A segunda superfície: `/financeiro/diagnostico`. Com origem `plataforma`,
    **nenhum** `Signal` de `source="projecao"` sai — nem runway, nem "Projeção de caixa negativa".

    Isso acontece **por construção**, sem editar `engine.py` nem `diagnostics.py`:
    `collect_engine_input` repassa `proj.runway.days` (agora `None` → `_runway_signal` devolve `[]`)
    e `w.alert` (agora `False` → `_projection_window_signals` não emite). Silêncio, não um 🟢 falso.

    Asserimos a **lista vazia** de `source="projecao"`, não a ausência de uma string: é o que impede
    o teste de passar por engano se amanhã nascer um terceiro sinal daquela origem."""
    # cenário que, antes da 8.1, produzia OS DOIS sinais: queima positiva (runway) e janela negativa
    _seed_available(client, headers, gross=150000)  # disponível 90000
    _payable(client, headers, amount=300000, due=_d(10))  # saldo projetado −210000 em todas
    db.commit()

    entrada = diagnostics_service.collect_engine_input(db, start=TODAY, end=TODAY)
    assert entrada.runway_days is None, "o motor não pode receber dias derivados do saldo sujo"
    assert all(not w.alert for w in entrada.projection_windows)

    sinais = diagnostics_service.compute_signals(db, start=TODAY, end=TODAY)
    da_projecao = [s for s in sinais if s.source == "projecao"]
    assert da_projecao == [], f"diagnóstico ainda afirma algo sobre a projeção: {da_projecao}"


def _snapshot(db: Session) -> dict:
    """Fotografia do estado que a projeção JAMAIS pode alterar (IV1 — read-only)."""
    db.expire_all()
    charges = {
        c.id: (c.status, c.amount_cents, c.due_date, c.paid_at)
        for c in db.scalars(select(Charge)).all()
    }
    payables = {
        p.id: (p.status, p.amount_cents, p.due_date, p.paid_at)
        for p in db.scalars(select(Payable)).all()
    }
    txs = {t.id: (t.status, t.net_cents) for t in db.scalars(select(Transaction)).all()}
    return {"charges": charges, "payables": payables, "transactions": txs}


def test_projection_is_read_only(client: TestClient, headers, db: Session):
    _seed_available(client, headers, gross=150000)
    _charge(client, headers, amount=50000, due=_d(20))
    _payable(client, headers, amount=30000, due=_d(45))
    before = _snapshot(db)
    _projection(client, headers)
    _projection(client, headers)
    after = _snapshot(db)
    assert after == before, "projeção escreveu/alterou dados — viola IV1 (read-only)"


# ══════════════════════════════════════════════════════════════════════════════════════════════
# Story 8.14 — o pagamento AGENDADO entra na Projeção, e entra UMA VEZ SÓ
# ══════════════════════════════════════════════════════════════════════════════════════════════
#
# ⚠️ **É a razão de a story existir.** Sem o `scheduled` em `_window_sums`, uma conta agendada não é
# `open` (sai dos fluxos de saída) e o movimento bancário dela é futuro (não entra no
# `saldo_inicial`, que usa `active_balance_total(until=today)`): os R$ 5.000 **somem por completo**
# da Projeção. *"O saldo diz que você os tem, e nada diz que vão sair"* — a máquina de falso
# negativo da Onda 0 ressuscitada na mesma tela que a Onda 0 consertou.
#
# E o recorte `paid_at::date > hoje` é a diferença entre consertar o falso negativo e trocá-lo por
# um falso positivo do mesmo tamanho: no dia agendado, antes da varredura do worker, o movimento já
# está no `saldo_inicial` **e** o `Payable` ainda está `scheduled`.


ABERTURA_BANCO = TODAY - timedelta(days=60)
SALDO_ABERTURA = 20_000_00


def _conta_bancaria(client, headers, **over) -> dict:
    payload = {
        "name": "Itaú PJ",
        "kind": "checking",
        "opening_balance_cents": SALDO_ABERTURA,
        "opening_date": ABERTURA_BANCO.isoformat(),
    }
    payload.update(over)
    r = client.post("/bank/accounts", json=payload, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def _agendar(client, headers, bill_id: str, *, conta_id: str, quando) -> dict:
    r = client.post(
        f"/payables/bills/{bill_id}/pay",
        json={"bank_account_id": conta_id, "paid_on": quando.isoformat()},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_IV1_o_agendado_esta_na_projecao_e_fora_do_saldo_inicial(client: TestClient, headers):
    """**IV1 — o cenário único, verificado nas TRÊS leituras ao mesmo tempo.**

    Saldo de abertura + 1 conta AGENDADA para D+15 + 1 conta ABERTA vencendo em D+20:

      (a) `saldo_inicial` **não** inclui o agendado (o movimento é futuro);
      (b) `_window_sums` **inclui** o agendado na janela de 30 dias, pela data do débito;
      (c) `saldo_projetado(D+30)` = saldo inicial − agendado − aberta.

    Se (a) e (b) discordassem, o número estaria certo por acidente numa das duas.
    """
    conta = _conta_bancaria(client, headers)
    agendada = _payable(client, headers, amount=5_000_00, due=_d(0))
    _agendar(
        client, headers, agendada["id"], conta_id=conta["id"], quando=TODAY + timedelta(days=15)
    )
    _payable(client, headers, amount=1_200_00, due=_d(20))

    body = _projection(client, headers)

    # (a) o saldo de partida é o saldo de abertura, limpo: o débito agendado ainda não saiu.
    assert body["saldo_inicial_banco_cents"] == SALDO_ABERTURA, (
        "o saldo inicial somou (ou subtraiu) um movimento FUTURO — `_saldo_inicial` deixou de "
        "passar `until=today`, ou `active_balance_total` mudou de default"
    )
    # (b)+(c) as duas saídas estão na janela de 30 dias, e o agendado entrou pela data do DÉBITO.
    esperado = body["saldo_inicial_cents"] - 5_000_00 - 1_200_00
    assert _window(body, 30)["saldo_projetado_cents"] == esperado, (
        "o pagamento AGENDADO sumiu da Projeção (ou entrou duas vezes). É o bug inteiro que a "
        "Story 8.14 existe para impedir."
    )
    assert _window(body, 90)["saldo_projetado_cents"] == esperado


def test_o_agendado_entra_pela_DATA_DO_DEBITO_nao_pelo_vencimento(client: TestClient, headers):
    """A conta **vence hoje** e foi agendada para D+45: ela entra na janela de 60, não na de 30.

    O dinheiro sai no dia agendado, não no dia do vencimento. Se `_window_sums` usasse `due_date`
    para a população agendada, a saída apareceria 45 dias antes de acontecer — e a Projeção
    passaria a apertar o caixa do dono num mês em que ele está folgado.
    """
    conta = _conta_bancaria(client, headers)
    bill = _payable(client, headers, amount=3_000_00, due=_d(0))
    _agendar(client, headers, bill["id"], conta_id=conta["id"], quando=TODAY + timedelta(days=45))

    body = _projection(client, headers)
    inicial = body["saldo_inicial_cents"]
    assert _window(body, 30)["saldo_projetado_cents"] == inicial, "entrou na janela ERRADA (30)"
    assert _window(body, 60)["saldo_projetado_cents"] == inicial - 3_000_00
    assert _window(body, 90)["saldo_projetado_cents"] == inicial - 3_000_00


def test_AC6_a_agendada_no_DIA_DO_DEBITO_nao_conta_duas_vezes(
    client: TestClient, headers, db: Session
):
    """⚠️ **O TESTE MAIS VALIOSO DA STORY.** `status == scheduled` **e** `paid_at::date == hoje`.

    Entre 00:00 do dia agendado e a varredura do worker, o `Payable` ainda está `scheduled` **e** o
    `bank_transaction` já tem `posted_at <= hoje`, logo já entra em
    `active_balance_total(db, until=today)`. Sem o recorte `paid_at::date > today`, a mesma conta
    seria subtraída **duas vezes** da projeção — um falso positivo do mesmo tamanho do falso
    negativo que a story veio consertar, e que dura um dia inteiro sem deixar rastro.

    ⚠️ **Como o estado é MONTADO importa, e a primeira versão deste teste estava errada.** Agendar
    "para hoje" **não** produz uma agendada: a derivação do AC2 devolve `paid` quando
    `paid_on == hoje` (é a borda estrita). Um teste escrito assim passa — **pelo motivo errado**,
    porque não há `scheduled` nenhum no banco e nada poderia ser contado duas vezes. O estado real
    do dia D se monta agendando para **amanhã** e pedindo a projeção **de amanhã** (o `today` é
    injetável desde a 5.7, justamente para isto). Nada é plantado à mão: a linha nasce pelo caminho
    de produção, e a pré-condição do cenário é asserida antes de o número ser medido.
    """
    conta = _conta_bancaria(client, headers)
    bill = _payable(client, headers, amount=5_000_00, due=_d(0))
    amanha = TODAY + timedelta(days=1)
    _agendar(client, headers, bill["id"], conta_id=conta["id"], quando=amanha)

    # Pré-condição do cenário: chegou o dia D e o worker AINDA NÃO rodou.
    assert (
        client.get(f"/payables/bills/{bill['id']}", headers=headers).json()["status"]
        == "scheduled"
    )

    proj = projection_service.cash_projection(db, today=amanha)
    # O valor entra UMA vez, pelo saldo inicial (o movimento é do dia e o corte é inclusivo).
    assert proj.saldo_inicial_banco_cents == SALDO_ABERTURA - 5_000_00
    for w in proj.windows:
        assert w.saldo_projetado_cents == proj.saldo_inicial_cents, (
            f"janela de {w.days} dias subtraiu o débito do DIA uma segunda vez: ele já está dentro "
            "do saldo inicial. O recorte `paid_at::date > today` de `_window_sums` sumiu."
        )


def test_AC6_o_numero_e_IDENTICO_com_e_sem_o_worker(client: TestClient, headers, db: Session):
    """A outra metade do AC6, e a que prova a **equivalência**, não só a ausência de dobra.

    Mesmo cenário do teste acima, medido duas vezes: com a conta ainda `scheduled` (worker parado) e
    depois de `promote_scheduled` tê-la promovido. **Campo a campo, os dois resultados são iguais.**
    Se um dia divergirem, a corretude da Projeção passou a depender de um processo em background —
    e o dono que abrir a tela às 8h da manhã veria um número diferente do de quem abrir às 9h.
    """
    from dataclasses import asdict

    from app.modules.payables import service as payables_service

    conta = _conta_bancaria(client, headers)
    bill = _payable(client, headers, amount=5_000_00, due=_d(0))
    amanha = TODAY + timedelta(days=1)
    _agendar(client, headers, bill["id"], conta_id=conta["id"], quando=amanha)
    _payable(client, headers, amount=800_00, due=_d(20))

    antes = asdict(projection_service.cash_projection(db, today=amanha))

    tenant_id = client.get("/auth/me", headers=headers).json()["user"]["tenant_id"]
    promovidas = payables_service.promote_scheduled(
        db, tenant_id=tenant_id, actor="system:worker", today=amanha
    )
    assert promovidas == 1, "pré-condição: a varredura tinha de ter algo a promover"

    depois = asdict(projection_service.cash_projection(db, today=amanha))
    assert depois == antes, (
        "a Projeção MUDOU depois de o worker rodar. O status é rótulo; a aritmética é função da "
        "data (F-D11). Se isto quebrou, `_window_sums` voltou a depender do status materializado."
    )


def test_saldo_inicial_chama_active_balance_total_com_until_igual_a_hoje(
    client: TestClient, headers, db: Session, monkeypatch
):
    """⚠️ **ASSERÇÃO OBRIGATÓRIA da IV1** (ratificação §C-7.3 / achado A-4). Espião sobre o kwarg.

    O recorte do AC6 tira a agendada de `_window_sums` quando a data já chegou **confiando** que o
    movimento está no `saldo_inicial`. Isso só é verdade porque `_saldo_inicial` passa
    `until=today`. Trocado por `None` ou por `SEM_CORTE`, a agendada **futura** passaria a contar
    nos DOIS lugares e a dupla contagem voltaria — agora pelo lado oposto, **em silêncio**, num
    arquivo que a story declara não tocar.

    O comentário que existe no código diz *por que* o argumento está lá (*"a MESMA âncora do resto
    da projeção"*) e **não diz o que quebra** — e o que quebra agora é outra coisa. Este espião é o
    que torna o AC6 auditável amanhã, e não só correto hoje.

    Espião (e não varredura de texto) de propósito: um `until` calculado de outro jeito passaria
    numa varredura por `"until=today"` e falha aqui, que é onde importa.
    """
    from app.modules.bank import service as bank_service

    _conta_bancaria(client, headers)
    capturado: list[object] = []
    original = bank_service.active_balance_total

    def _espiao(*args, **kwargs):
        capturado.append(kwargs.get("until", "AUSENTE"))
        return original(*args, **kwargs)

    monkeypatch.setattr(bank_service, "active_balance_total", _espiao)
    projection_service.cash_projection(db, today=TODAY)

    assert capturado, "`_saldo_inicial` deixou de chamar `active_balance_total`"
    assert capturado == [TODAY], (
        f"`_saldo_inicial` chamou `active_balance_total(until={capturado!r})` em vez de "
        f"`until={TODAY!r}`. Com `None` ou `SEM_CORTE` ali, o pagamento AGENDADO passa a contar no "
        "saldo inicial E nos fluxos de saída — a dupla contagem do AC6 volta pela porta oposta, "
        "sem nenhum teste de comportamento ficar vermelho."
    )


def test_conta_agendada_para_ALEM_de_90_dias_nao_entra_em_janela_nenhuma(
    client: TestClient, headers
):
    """A borda superior: o agendado respeita o horizonte, como o `open` sempre respeitou."""
    conta = _conta_bancaria(client, headers)
    bill = _payable(client, headers, amount=9_000_00, due=_d(0))
    _agendar(client, headers, bill["id"], conta_id=conta["id"], quando=TODAY + timedelta(days=120))

    body = _projection(client, headers)
    for dias in (30, 60, 90):
        assert _window(body, dias)["saldo_projetado_cents"] == body["saldo_inicial_cents"]


def test_agendada_nao_entra_em_overdue_outflow(client: TestClient, headers):
    """`overdue_outflow_cents` é a parcela **vencida e em aberto**. Uma agendada nunca é vencida —
    a data do débito é futura por construção —, e a conta que vencia há 30 dias deixa de ser
    "atrasada" no instante em que ganha dia marcado. É o `status == open_status` explícito dentro
    do `CASE` de `overdue_col`: sem ele, o agendado com vencimento passado cairia ali."""
    conta = _conta_bancaria(client, headers)
    bill = _payable(client, headers, amount=700_00, due=_d(-30))
    assert _projection(client, headers)["overdue_outflow_cents"] == 700_00

    _agendar(client, headers, bill["id"], conta_id=conta["id"], quando=TODAY + timedelta(days=5))
    body = _projection(client, headers)
    assert body["overdue_outflow_cents"] == 0, (
        "a conta agendada apareceu como VENCIDA. `overdue_col` perdeu o filtro de status e passou "
        "a olhar só a data."
    )
    # ...mas ela continua na projeção, pela data do débito.
    assert _window(body, 30)["saldo_projetado_cents"] == body["saldo_inicial_cents"] - 700_00


def test_conta_CANCELADA_e_conta_PAGA_continuam_fora_da_projecao(client: TestClient, headers):
    """A população cresceu para `{open, scheduled}` — e **só** para isso. `canceled` e `paid`
    continuam fora dos fluxos de saída, como sempre estiveram."""
    conta = _conta_bancaria(client, headers)
    cancelada = _payable(client, headers, amount=4_000_00, due=_d(10))
    client.post(f"/payables/bills/{cancelada['id']}/cancel", headers=headers)
    paga = _payable(client, headers, amount=2_000_00, due=_d(10))
    _agendar(client, headers, paga["id"], conta_id=conta["id"], quando=TODAY - timedelta(days=1))

    body = _projection(client, headers)
    assert _window(body, 30)["saldo_projetado_cents"] == body["saldo_inicial_cents"], (
        "conta cancelada ou já paga entrou nos fluxos de saída"
    )


def test_window_sums_SEM_os_parametros_de_agendado_se_comporta_como_antes_da_8_14(
    client: TestClient, headers, db: Session
):
    """**O contrato da parametrização, em forma de teste** — omitidos, os parâmetros não mudam nada.

    ⚠️ **[Story 8.15] Este teste mudou de NOME e de propósito, e a mudança é a correção.** Ele se
    chamava `test_ENTRADAS_continuam_so_open_nesta_story` e era a delimitação de escopo da 8.14
    (*"o lado do recebimento é a Story 8.15"*). A 8.15 chegou: `cash_projection` agora liga
    `scheduled_status`/`scheduled_at` para `Charge` também (ver os testes abaixo), e manter o nome
    antigo faria o arquivo afirmar o contrário do que o código faz.

    O que continua valendo — e é o motivo de o teste **ficar** em vez de sumir — é o contrato da
    parametrização: `_window_sums` **sem** os dois argumentos se comporta byte a byte como antes da
    8.14. É essa propriedade que permite ligar/desligar a população 2 por chamador, em vez de um
    `isinstance(model, Payable)` dentro da função.
    """
    from app.modules.receivables.models import STATUS_OPEN as CHARGE_OPEN
    from app.modules.receivables.models import Charge

    _charge(client, headers, amount=1_000_00, due=_d(10))
    horizons = [TODAY + timedelta(days=w) for w in (30, 60, 90)]
    somas, vencido = projection_service._window_sums(
        db, Charge, open_status=CHARGE_OPEN, today=TODAY, horizons=horizons
    )
    assert somas == [1_000_00, 1_000_00, 1_000_00] and vencido == 0


# ══════════════════════════════════════════════════════════════════════════════════════════════
# Story 8.15 (AC6) — o lado das ENTRADAS herda o mesmo conserto
# ══════════════════════════════════════════════════════════════════════════════════════════════
#
# Sem isto, o espelho EXATO do bug da 8.14 acontece do lado das entradas: um Pix agendado não é
# `open` (sai das entradas) **e** o movimento bancário dele é futuro (não entra no `saldo_inicial`,
# que usa `active_balance_total(until=today)`) → **some da Projeção**. O dono veria um caixa mais
# apertado do que o real, e a tela que responde *"e quando o caixa aperta?"* mentiria por omissão —
# na direção oposta, mas pela mesma mecânica.


def _receber_fora_do_trilho(client, headers, charge_id: str, *, conta_id: str, quando) -> dict:
    r = client.post(
        f"/receivables/charges/{charge_id}/settle-externally",
        json={"bank_account_id": conta_id, "received_on": quando.isoformat()},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_AC6_o_recebimento_agendado_esta_na_projecao_e_fora_do_saldo_inicial(
    client: TestClient, headers
):
    """O cenário único, nas TRÊS leituras ao mesmo tempo — espelho da IV1 da 8.14.

    Saldo de abertura + 1 cobrança RECEBIDA-AGENDADA para D+15 + 1 cobrança ABERTA vencendo D+20:
      (a) `saldo_inicial` **não** inclui o crédito agendado (o movimento é futuro);
      (b) a janela de 30 dias **inclui** o agendado, pela data do CRÉDITO;
      (c) `saldo_projetado(D+30)` = saldo inicial + agendado + aberta.
    """
    conta = _conta_bancaria(client, headers)
    agendada = _charge(client, headers, amount=3_000_00, due=_d(0))
    _receber_fora_do_trilho(
        client, headers, agendada["id"], conta_id=conta["id"], quando=TODAY + timedelta(days=15)
    )
    _charge(client, headers, amount=1_200_00, due=_d(20))

    body = _projection(client, headers)

    assert body["saldo_inicial_banco_cents"] == SALDO_ABERTURA, (
        "o saldo inicial somou um crédito FUTURO — `_saldo_inicial` deixou de passar `until=today`"
    )
    esperado = body["saldo_inicial_cents"] + 3_000_00 + 1_200_00
    assert _window(body, 30)["saldo_projetado_cents"] == esperado, (
        "o recebimento AGENDADO sumiu da Projeção (ou entrou duas vezes) — é o espelho exato do "
        "bug que a Story 8.14 consertou do lado das saídas"
    )
    assert _window(body, 90)["saldo_projetado_cents"] == esperado


def test_AC6_o_recebimento_agendado_entra_pela_DATA_DO_CREDITO_nao_pelo_vencimento(
    client: TestClient, headers
):
    """A cobrança **vence hoje** e o Pix caiu para D+45: entra na janela de 60, não na de 30."""
    conta = _conta_bancaria(client, headers)
    charge = _charge(client, headers, amount=2_000_00, due=_d(0))
    _receber_fora_do_trilho(
        client, headers, charge["id"], conta_id=conta["id"], quando=TODAY + timedelta(days=45)
    )

    body = _projection(client, headers)
    assert _window(body, 30)["saldo_projetado_cents"] == body["saldo_inicial_cents"]
    assert _window(body, 60)["saldo_projetado_cents"] == body["saldo_inicial_cents"] + 2_000_00


def test_AC6_o_recebimento_agendado_no_DIA_DO_CREDITO_nao_conta_duas_vezes(
    client: TestClient, headers, db: Session
):
    """⚠️ **O recorte `paid_at::date > today`, do lado das entradas.**

    Entre 00:00 do dia do crédito e a varredura do worker, a `Charge` ainda está `scheduled` **e**
    o `bank_transaction` já tem `posted_at <= hoje` — logo já entra em `active_balance_total(db,
    until=today)`, que semeia o `saldo_inicial`. Sem o recorte, o mesmo dinheiro seria **somado
    duas vezes**.

    ⚠️ O estado do dia D se monta agendando para **amanhã** e pedindo a projeção **de amanhã**:
    registrar "para hoje" devolve `paid` (a borda é estrita) e o teste passaria pelo motivo errado,
    sem nenhum `scheduled` no banco.
    """
    conta = _conta_bancaria(client, headers)
    charge = _charge(client, headers, amount=3_000_00, due=_d(0))
    amanha = TODAY + timedelta(days=1)
    _receber_fora_do_trilho(client, headers, charge["id"], conta_id=conta["id"], quando=amanha)

    # Pré-condição: chegou o dia D e o worker AINDA NÃO rodou.
    assert (
        client.get(f"/receivables/charges/{charge['id']}", headers=headers).json()["status"]
        == "scheduled"
    )

    proj = projection_service.cash_projection(db, today=amanha)
    assert proj.saldo_inicial_banco_cents == SALDO_ABERTURA + 3_000_00
    for w in proj.windows:
        assert w.saldo_projetado_cents == proj.saldo_inicial_cents, (
            f"janela de {w.days} dias somou o crédito do DIA uma segunda vez: ele já está dentro "
            "do saldo inicial. O recorte `paid_at::date > today` sumiu do lado das entradas."
        )


def test_AC6_ENTRADAS_o_numero_e_IDENTICO_com_e_sem_o_worker(
    client: TestClient, headers, db: Session
):
    """A equivalência, não só a ausência de dobra — a prova do F-D11 do lado das entradas.

    Mesmo cenário medido duas vezes: com a cobrança ainda `scheduled` (worker parado) e depois de
    `receivables.promote_scheduled` tê-la promovido. **Campo a campo, iguais.** Se um dia
    divergirem, a corretude da Projeção passou a depender de um processo em background.
    """
    from dataclasses import asdict

    from app.modules.receivables import service as receivables_service

    conta = _conta_bancaria(client, headers)
    charge = _charge(client, headers, amount=3_000_00, due=_d(0))
    amanha = TODAY + timedelta(days=1)
    _receber_fora_do_trilho(client, headers, charge["id"], conta_id=conta["id"], quando=amanha)
    _charge(client, headers, amount=800_00, due=_d(20))

    antes = asdict(projection_service.cash_projection(db, today=amanha))

    tenant_id = client.get("/auth/me", headers=headers).json()["user"]["tenant_id"]
    promovidas = receivables_service.promote_scheduled(
        db, tenant_id=tenant_id, actor="system:worker", today=amanha
    )
    assert promovidas == 1, "pré-condição: a varredura tinha de ter algo a promover"

    depois = asdict(projection_service.cash_projection(db, today=amanha))
    assert depois == antes, (
        "a Projeção MUDOU depois de o worker rodar. O status é rótulo; a aritmética é função da "
        "data (F-D11)."
    )


def test_AC6_o_recebimento_agendado_nao_entra_em_overdue_inflow(client: TestClient, headers):
    """Uma cobrança agendada nunca está vencida — nem quando o vencimento dela já passou.

    É o `status == open_status` explícito dentro do `CASE` de `overdue_col`: sem ele, o agendado
    com vencimento passado cairia em `overdue_inflow_cents` e a régua de cobrança teria um número
    para justificar um lembrete a quem já pagou.
    """
    conta = _conta_bancaria(client, headers)
    charge = _charge(client, headers, amount=900_00, due=_d(-30))
    assert _projection(client, headers)["overdue_inflow_cents"] == 900_00

    _receber_fora_do_trilho(
        client, headers, charge["id"], conta_id=conta["id"], quando=TODAY + timedelta(days=5)
    )
    body = _projection(client, headers)
    assert body["overdue_inflow_cents"] == 0
    assert _window(body, 30)["saldo_projetado_cents"] == body["saldo_inicial_cents"] + 900_00


def test_AC6_cobranca_CANCELADA_e_RECEBIDA_continuam_fora_das_entradas(client: TestClient, headers):
    """A população de entradas cresceu para `{open, scheduled}` — e **só** para isso."""
    conta = _conta_bancaria(client, headers)
    cancelada = _charge(client, headers, amount=4_000_00, due=_d(10))
    client.post(f"/receivables/charges/{cancelada['id']}/cancel", headers=headers)
    recebida = _charge(client, headers, amount=2_000_00, due=_d(10))
    _receber_fora_do_trilho(
        client, headers, recebida["id"], conta_id=conta["id"], quando=TODAY - timedelta(days=1)
    )

    body = _projection(client, headers)
    assert _window(body, 30)["saldo_projetado_cents"] == body["saldo_inicial_cents"], (
        "cobrança cancelada ou já recebida entrou nos fluxos de entrada"
    )
