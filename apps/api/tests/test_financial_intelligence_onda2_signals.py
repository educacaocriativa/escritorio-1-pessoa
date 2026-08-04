"""As duas regras da Onda 2 no motor de diagnóstico (Story 8.16) — 100% sem banco e sem rede.

Mesma disciplina de `test_financial_intelligence_completeness.py`: as dataclasses são montadas à
mão, sem fixture de DB, sem `client`, sem Postgres. Se um dia for preciso um banco para testar uma
regra do motor, é porque a pureza foi perdida — e os dois gates de IV1 (AST + texto cru) estão lá
para impedir isso em silêncio.

Os testes que mais importam, e o modo de falha que cada um trava:

- **`test_borda_exata_do_criterio_de_casamento`** — o critério `max(R$ 50; 10%)` que substituiu o
  intervalo `[0,5×, 2×]` REJEITADO pela ratificação §C-2.3. O caso R$ 5.000 × R$ 2.500 é
  exatamente o que o fator 2 deixava passar, e **nomear um débito inocente é pior do que ficar
  calado**.
- **`test_divergencia_negativa_nao_emite_sinal_de_debito`** — divergência negativa é o sintoma
  OPOSTO (falta lançamento de saída). Nomear um débito ali manda o dono para o lado errado.
- **`test_um_unico_sinal_por_relatorio_para_o_fora_do_trilho`** e
  **`test_um_sinal_por_conta_para_o_debito_suspeito`** — a cardinalidade. A disciplina anti-ruído é
  a mesma da banda de tolerância: uma tela que grita destrói a confiança no sinal.
- **`test_iv2_off_rail_e_debitos_none_nao_mudam_nada`** — compatibilidade retroativa: com os dois
  campos em `None`, `compute_signals` devolve **exatamente** a mesma lista das 5.8/8.6.
- **`test_nenhum_texto_do_motor_usa_o_radical_agendad`** — é o que impede a renomeação normativa do
  §C-2.3 de ser desfeita por um *"voltei o nome antigo, ficou mais claro"* daqui a três meses.
"""
from __future__ import annotations

import ast
import pathlib
import re
from datetime import date

import pytest

from app.modules.financial_intelligence.engine import (
    _DEBITO_MATCH_DIVISOR,
    _DEBITO_MATCH_FLOOR_CENTS,
    AMARELO,
    VERMELHO,
    CompletenessAccountInput,
    CompletenessInput,
    DebitoSuspeitoInput,
    EngineInput,
    InvestmentReturn,
    MarginTrend,
    OffRailInput,
    ProjectionWindowInput,
    _debito_explica,
    _debito_suspeito_signals,
    _off_rail_signals,
    compute_signals,
)

ENGINE_PATH = (
    pathlib.Path(__file__).resolve().parents[1]
    / "app"
    / "modules"
    / "financial_intelligence"
    / "engine.py"
)


def _conta(
    name: str = "Itaú PJ",
    *,
    divergencia: int | None = 500_000,
    tolerancia: int = 5_000,
    dias: int | None = 0,
) -> CompletenessAccountInput:
    """Conta com divergência POSITIVA de R$ 5.000 — o cenário do débito suspeito."""
    return CompletenessAccountInput(
        account_name=name,
        divergencia_cents=divergencia,
        tolerancia_cents=tolerancia,
        dias_desde_ultima_conferencia=dias,
    )


def _debito(
    *,
    descricao: str = "Aluguel",
    valor: int = 500_000,
    dia: date = date(2026, 8, 15),
    conta: str = "Itaú PJ",
) -> DebitoSuspeitoInput:
    return DebitoSuspeitoInput(
        descricao=descricao, valor_cents=valor, data_debito=dia, bank_account_name=conta
    )


# ── AC3 — o 🟡 de recebimento fora da cobrança do e1p ─────────────────────────────────────────


def test_off_rail_none_nao_emite_sinal() -> None:
    """Motor chamado sem a entrada (o caso das 5.8/8.6) → zero sinal, nunca um verde."""
    assert _off_rail_signals(None) == []


def test_zero_recebimento_fora_do_trilho_e_silencio() -> None:
    """Nada aconteceu ⇒ **nenhuma** frase. Silêncio é o comportamento certo, não omissão."""
    assert _off_rail_signals(OffRailInput(0, 12, 0)) == []


def test_um_unico_sinal_por_relatorio_para_o_fora_do_trilho() -> None:
    """**1 por relatório**, não 1 por cobrança — a mesma disciplina anti-ruído da banda."""
    signals = _off_rail_signals(OffRailInput(3, 12, 420_000))
    assert len(signals) == 1
    s = signals[0]
    assert s.level == AMARELO, "nada está quebrado: o dinheiro entrou e está na DRE"
    assert s.source == "recebimento_externo"
    assert "3 dos 12 recebimentos" in s.explanation
    assert "R$ 4.200,00" in s.explanation
    assert "não geram boleto, lembrete automático nem baixa sozinha" in s.explanation


def test_o_texto_do_fora_do_trilho_nao_fala_de_plataforma() -> None:
    """O sinal é sobre o interesse do DONO, e nunca sobre a receita da e1p (G-D7).

    O caso é, no estudo interno, vazamento de receita da plataforma — e mesmo assim toda a redação
    é sobre a cobrança que não fecha sozinha e o cliente que não recebe régua. O jargão interno
    ("trilho") também não vaza para a tela do dono.
    """
    s = _off_rail_signals(OffRailInput(1, 4, 140_000))[0]
    texto = f"{s.title} {s.explanation}".lower()
    for proibida in ("split", "taxa", "plataforma", "trilho", "comissão", "receita da e1p"):
        assert proibida not in texto, f"o sinal do dono falou de {proibida!r}: {texto}"


# ── AC5/AC6 — o 🟡 que NOMEIA o débito suspeito ───────────────────────────────────────────────


def test_sem_debitos_ou_sem_completude_nao_emite_sinal() -> None:
    assert _debito_suspeito_signals(None, CompletenessInput(contas=[_conta()])) == []
    assert _debito_suspeito_signals([], CompletenessInput(contas=[_conta()])) == []
    assert _debito_suspeito_signals([_debito()], None) == []


def test_debito_que_explica_a_divergencia_e_nomeado() -> None:
    """O cenário canônico: débito de R$ 5.000 diante de divergência de +R$ 5.000."""
    signals = _debito_suspeito_signals([_debito()], CompletenessInput(contas=[_conta()]))
    assert len(signals) == 1
    s = signals[0]
    assert s.level == AMARELO
    assert s.source == "debito_nao_confirmado"
    assert "R$ 5.000,00" in s.explanation
    assert "de 15/08" in s.explanation
    assert "(Aluguel)" in s.explanation
    assert "Itaú PJ" in s.explanation
    # A única afirmação que o e1p tem direito de fazer — VERBATIM (ratificação §C-2.3).
    assert "pode não ter saído" in s.explanation
    assert "não saiu da conta" not in s.explanation


def test_borda_exata_do_criterio_de_casamento() -> None:
    """`max(R$ 50; 10%)` — e o caso que o `[0,5×, 2×]` REJEITADO deixava passar.

    Um fator 2 nomearia um débito de R$ 5.000 diante de uma divergência de R$ 2.500. *"Pode não ter
    saído"* sobre um débito que obviamente saiu treina o dono a ignorar a tela, e o silêncio apenas
    devolve o número que ele já tem hoje.
    """
    assert _DEBITO_MATCH_FLOOR_CENTS == 5_000
    assert _DEBITO_MATCH_DIVISOR == 10

    # Divergência de R$ 5.000 → banda de casamento = max(5_000, 50_000) = R$ 500,00.
    assert _debito_explica(500_000, 500_000) is True, "diferença zero casa"
    assert _debito_explica(550_000, 500_000) is True, "a borda EXATA (R$ 500 de diferença) casa"
    assert _debito_explica(450_000, 500_000) is True
    assert _debito_explica(550_100, 500_000) is False, "um centavo além da borda NÃO casa"
    # O caso do fator 2 rejeitado: R$ 5.000 de débito × R$ 2.500 de divergência.
    assert _debito_explica(500_000, 250_000) is False
    # E o inverso, também rejeitado pelo mesmo motivo.
    assert _debito_explica(20_000, 500_000) is False

    # Divergência PEQUENA: o piso de R$ 50 é que manda (10% de R$ 100 seria R$ 10).
    assert _debito_explica(15_000, 10_000) is True
    assert _debito_explica(15_100, 10_000) is False


def test_borda_do_criterio_ponta_a_ponta_no_sinal() -> None:
    """A borda do critério vista pela regra inteira, não só pelo predicado."""
    casa = _debito_suspeito_signals(
        [_debito(valor=500_000)], CompletenessInput(contas=[_conta(divergencia=500_000)])
    )
    assert len(casa) == 1
    silencio = _debito_suspeito_signals(
        [_debito(valor=500_000)], CompletenessInput(contas=[_conta(divergencia=250_000)])
    )
    assert silencio == [], "R$ 5.000 × R$ 2.500 tem de ser SILÊNCIO (o caso do fator 2 rejeitado)"


def test_divergencia_negativa_nao_emite_sinal_de_debito() -> None:
    """Banco ABAIXO do sistema é o sintoma OPOSTO — falta lançamento de SAÍDA.

    Nomear um débito ali mandaria o dono conferir no extrato justamente o que ele já lançou.
    """
    signals = _debito_suspeito_signals(
        [_debito(valor=500_000)], CompletenessInput(contas=[_conta(divergencia=-500_000)])
    )
    assert signals == []


def test_divergencia_nao_avaliavel_nao_emite_sinal_de_debito() -> None:
    """`None` é NÃO AVALIÁVEL, jamais zero: não se explica o que o sistema não mediu."""
    signals = _debito_suspeito_signals(
        [_debito()], CompletenessInput(contas=[_conta(divergencia=None, tolerancia=0)])
    )
    assert signals == []


def test_um_sinal_por_conta_para_o_debito_suspeito() -> None:
    """**1 por conta**, e é o suspeito de MAIOR valor entre os que casam."""
    contas = CompletenessInput(
        contas=[
            _conta("Itaú PJ", divergencia=500_000),
            _conta("Bradesco PJ", divergencia=120_000),
        ]
    )
    debitos = [
        _debito(descricao="Aluguel", valor=500_000, conta="Itaú PJ"),
        _debito(descricao="Energia", valor=480_000, conta="Itaú PJ"),
        _debito(descricao="Contador", valor=120_000, conta="Bradesco PJ"),
    ]
    signals = _debito_suspeito_signals(debitos, contas)
    assert len(signals) == 2, "um sinal por conta, nunca um por débito"
    assert "Aluguel" in signals[0].explanation and "Itaú PJ" in signals[0].explanation
    assert "Energia" not in signals[0].explanation, "o de MAIOR valor é o nomeado"
    assert "Contador" in signals[1].explanation


def test_debito_de_outra_conta_nao_explica_a_divergencia_desta() -> None:
    """O casamento é POR CONTA. Um débito do Bradesco não explica o furo do Itaú."""
    signals = _debito_suspeito_signals(
        [_debito(valor=500_000, conta="Bradesco PJ")],
        CompletenessInput(contas=[_conta("Itaú PJ", divergencia=500_000)]),
    )
    assert signals == []


def test_determinismo_das_duas_regras_novas() -> None:
    """Mesma entrada → mesma lista, sempre (inclusive no empate de valor: `max` é estável)."""
    contas = CompletenessInput(contas=[_conta()])
    debitos = [
        _debito(descricao="Primeiro", valor=500_000),
        _debito(descricao="Segundo", valor=500_000),
    ]
    primeiro = _debito_suspeito_signals(debitos, contas)
    assert primeiro == _debito_suspeito_signals(debitos, contas)
    assert "Primeiro" in primeiro[0].explanation, "empate → vence o primeiro da lista"

    off = OffRailInput(2, 9, 300_000)
    assert _off_rail_signals(off) == _off_rail_signals(off) == _off_rail_signals(off)


# ── Integração com `compute_signals` (ainda 100% puro) ────────────────────────────────────────


def test_iv2_off_rail_e_debitos_none_nao_mudam_nada() -> None:
    """**IV2** — com os dois campos novos em `None`, a saída é a MESMA lista de antes.

    Igualdade estrutural, campo a campo (as `Signal` são frozen dataclasses): mesma ordem, mesmos
    textos, mesmos níveis. É o que garante que os testes das 5.8 e 8.6 seguem válidos sem edição.
    """
    base = dict(
        margins=[MarginTrend("Alpha", 0.30, 0.10, "1 mês")],
        runway_days=30,
        projection_windows=[ProjectionWindowInput(30, True)],
        investments=[InvestmentReturn("CDB", -0.01)],
        completeness=CompletenessInput(contas=[_conta(divergencia=0)]),
    )
    antigo = EngineInput(**base)
    assert antigo.off_rail is None and antigo.debitos_suspeitos is None
    explicito = EngineInput(**base, off_rail=None, debitos_suspeitos=None)
    assert compute_signals(antigo) == compute_signals(explicito)

    # E a construção POSICIONAL das 5.8/8.6 continua válida.
    posicional = EngineInput([], None, [], [])
    assert posicional.off_rail is None and posicional.debitos_suspeitos is None
    assert compute_signals(posicional) == []


def test_as_regras_novas_entram_junto_da_completude_e_antes_das_demais() -> None:
    """Precedência semântica preservada: completude → fora do trilho → débito → margem/runway.

    O sort é ESTÁVEL, então a ordem de avaliação decide o empate DENTRO do nível. Aqui os quatro
    🟡 aparecem na ordem de avaliação, depois do 🔴 (a gravidade nunca é ultrapassada).
    """
    data = EngineInput(
        margins=[MarginTrend("Alpha", 0.30, 0.20, "1 mês")],  # queda de 10 p.p. → 🟡
        runway_days=None,
        projection_windows=[],
        investments=[],
        completeness=CompletenessInput(
            contas=[_conta("Itaú PJ", divergencia=500_000, dias=90)]  # 🔴 fora da banda + 🟡 velho
        ),
        off_rail=OffRailInput(1, 5, 140_000),
        debitos_suspeitos=[_debito()],
    )
    signals = compute_signals(data)
    assert [s.level for s in signals] == [VERMELHO, AMARELO, AMARELO, AMARELO, AMARELO]
    assert [s.source for s in signals] == [
        "completude",
        "completude",
        "recebimento_externo",
        "debito_nao_confirmado",
        "lucratividade",
    ]


# ── A renomeação normativa do §C-2.3, travada por varredura ───────────────────────────────────


def _strings_de_codigo(path: pathlib.Path) -> list[str]:
    """Todas as strings literais do arquivo **exceto docstrings**.

    A prosa PRECISA poder citar a palavra proibida para explicar a proibição (é literalmente o que
    a docstring de `_debito_suspeito_signals` faz). O que não pode é a palavra voltar para um
    **texto que o dono lê** ou para um identificador. Mesmo espírito da separação
    docstring × código do gate de pureza da 8.6.
    """
    codigo = path.read_text(encoding="utf-8")
    arvore = ast.parse(codigo, filename=str(path))
    docstrings = {
        no.body[0].value
        for no in ast.walk(arvore)
        if isinstance(no, ast.Module | ast.ClassDef | ast.FunctionDef)
        and no.body
        and isinstance(no.body[0], ast.Expr)
        and isinstance(no.body[0].value, ast.Constant)
        and isinstance(no.body[0].value.value, str)
    }
    return [
        no.value
        for no in ast.walk(arvore)
        if isinstance(no, ast.Constant) and isinstance(no.value, str) and no not in docstrings
    ]


def test_nenhum_texto_do_motor_usa_o_radical_agendad() -> None:
    """*"O efeito existe; o adjetivo não"* (ratificação §C-2.3, ajuste 1) — em forma de gate.

    Depois que o worker promove `scheduled → paid`, **nada no dado distingue** *"agendei e o banco
    não executou"* de *"paguei no caixa e o banco não compensou"*. Um nome que diz uma coisa
    carregando outra é o defeito D-3, e este épico já o cometeu duas vezes. Sem este teste, a
    renomeação seria desfeita pelo primeiro *"voltei o nome antigo, ficou mais claro"*.
    """
    ofensores = [s for s in _strings_de_codigo(ENGINE_PATH) if "agendad" in s.lower()]
    assert not ofensores, (
        f"o motor voltou a afirmar 'agendado' num texto que o dono lê: {ofensores}. O adjetivo não "
        "sobrevive ao worker — aponte o DÉBITO e a divergência, e diga 'pode não ter saído'."
    )
    # E os identificadores também: nada de `AgendamentoSuspeitoInput`/`source="agendamento"`.
    codigo = ENGINE_PATH.read_text(encoding="utf-8")
    arvore = ast.parse(codigo, filename=str(ENGINE_PATH))
    nomes = {
        no.name
        for no in ast.walk(arvore)
        if isinstance(no, ast.ClassDef | ast.FunctionDef)
    }
    assert not [n for n in nomes if "agendam" in n.lower()], nomes


def test_o_rotulo_do_frontend_tambem_perdeu_o_adjetivo() -> None:
    """A superfície mais cara é a que o dono lê — o rótulo é *"Saídas"*, nunca *"Agendamentos"*.

    Varredura do arquivo real do frontend a partir do backend, de propósito: a renomeação atravessa
    as duas pontas e um teste em cada lado deixaria a metade não coberta passar sozinha.

    Pula (em vez de falhar) quando `apps/web` não está presente: o backend precisa poder rodar
    sozinho num container sem o frontend (mesmo padrão de
    `test_bank_contagem_dupla.py::test_vocabulario_sugerido_bate_com_a_ui`). O cálculo do caminho
    fica DENTRO da função, não em escopo de módulo: `parents[3]` levanta `IndexError` — não apenas
    "arquivo ausente" — dentro da imagem de produção, onde o contexto de build é só `apps/api` e a
    árvore de diretórios é mais rasa do que no checkout completo.
    """
    parents = pathlib.Path(__file__).resolve().parents
    if len(parents) <= 3:
        pytest.skip("apps/web não está presente nesta árvore")
    diagnostico_ts = (
        parents[3] / "apps" / "web" / "src" / "features" / "financeiro" / "diagnostico.ts"
    )
    if not diagnostico_ts.exists():
        pytest.skip("apps/web não está presente nesta árvore")
    bruto = diagnostico_ts.read_text(encoding="utf-8")
    assert '"Saídas"' in bruto, "o rótulo de `debito_nao_confirmado` tem de ser 'Saídas'"
    # Só as STRINGS do código, e nunca os comentários nem os identificadores. O comentário precisa
    # poder citar a palavra proibida para explicar a proibição (mesma separação docstring × código
    # de `_strings_de_codigo`); e `month.split("-")` é o método do JS, não o split do e1p.
    codigo = re.sub(r"//[^\n]*", "", re.sub(r"/\*.*?\*/", "", bruto, flags=re.S))
    literais = " ".join(re.findall(r'"([^"\n]*)"', codigo)).lower()
    for proibida in ("agendad", "agendament", "trilho", "split", "plataforma"):
        assert proibida not in literais, (
            f"{proibida!r} apareceu num texto que o dono lê, em diagnostico.ts: {literais}"
        )


# ── IV1 — os símbolos novos não trouxeram I/O nem relógio para dentro do motor ────────────────


def test_iv1_os_simbolos_novos_nao_trouxeram_relogio_para_o_motor() -> None:
    """`data_debito` chega PRONTA: o motor não calcula "já venceu" nem compara com hoje.

    Complementa os dois gates da 8.6 (que continuam valendo) com a asserção específica desta story:
    a tentação aqui era importar `date.today` para decidir o que é suspeito. Quem decide é
    `diagnostics.py`.
    """
    codigo = ENGINE_PATH.read_text(encoding="utf-8")
    arvore = ast.parse(codigo, filename=str(ENGINE_PATH))
    fontes = [
        ast.get_source_segment(codigo, no) or ""
        for no in ast.walk(arvore)
        if isinstance(no, ast.Call | ast.Attribute | ast.Name)
    ]
    proibidos = ("date.today", "datetime.now", "timedelta", "utcnow")
    ofensores = sorted({p for p in proibidos for t in fontes if p in t})
    assert not ofensores, (
        f"o motor passou a depender de relógio: {ofensores}. `DebitoSuspeitoInput.data_debito` "
        "chega pronta de `diagnostics.py` — é isso que mantém a regra testável sem banco."
    )
