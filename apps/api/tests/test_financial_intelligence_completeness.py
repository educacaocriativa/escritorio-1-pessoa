"""A regra de **completude** do motor de diagnóstico (Story 8.6) — 100% sem banco e sem rede.

Este arquivo é a prova prática do valor que a Story 5.8 entregou: a regra de maior peso do Epic 8
é testada montando dataclasses à mão, sem fixture de DB, sem `client`, sem Postgres. Se um dia for
preciso um banco para testar uma regra do motor, é porque a pureza foi perdida — e o
`test_iv1_engine_permanece_estritamente_puro` (a varredura estática, no fim do arquivo) é o gate
que impede isso de acontecer em silêncio.

Os testes que mais importam, e o modo de falha que cada um trava:

- **`test_tres_contas_nenhuma_conferida_geram_tres_sinais`** — a cardinalidade da ratificação D-2
  (Ajuste 2). A versão pré-fusão emitiria **seis** 🟡 dizendo a mesma coisa. Um diagnóstico que
  grita seis vezes pelo mesmo motivo deixa de ser diagnóstico.
- **`test_cenario_do_epic_dois_vermelhos_nomeando_as_contas`** — o cenário do fundador (F3, epic
  §3.2): +R$ 1.200 / −R$ 900 / +R$ 40 consolidam em "+R$ 340, parece saudável" e escondem dois
  furos. O teste exige **dois** 🔴 nomeando as contas e proíbe o consolidado de aparecer.
- **`test_borda_divergencia_igual_a_tolerancia_e_dentro`** — a borda `==` é DENTRO (silêncio), a
  mesma semântica da 8.5. Invertê-la em manutenção transformaria a banda em ruído.
- **`test_none_significa_nao_avaliavel_e_impede_o_verde`** — `None` **não é zero**: o sistema não
  afirma que está batendo aquilo que nunca conferiu.
"""
from __future__ import annotations

import ast
import pathlib

from app.modules.financial_intelligence.engine import (
    _COMPLETENESS_STALE_DAYS,
    AMARELO,
    VERDE,
    VERMELHO,
    CompletenessAccountInput,
    CompletenessInput,
    EngineInput,
    InvestmentReturn,
    MarginTrend,
    ProjectionWindowInput,
    Signal,
    _brl,
    _completeness_signals,
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
    divergencia: int | None = 0,
    tolerancia: int = 5_000,
    dias: int | None = 0,
) -> CompletenessAccountInput:
    """Conta conferida hoje, batendo exato — o saudável. Cada teste muda só o que quer testar."""
    return CompletenessAccountInput(
        account_name=name,
        divergencia_cents=divergencia,
        tolerancia_cents=tolerancia,
        dias_desde_ultima_conferencia=dias,
    )


def _sinais(*contas: CompletenessAccountInput, orfaos: int = 0) -> list[Signal]:
    return _completeness_signals(
        CompletenessInput(contas=list(contas), movimentos_sem_contrapartida=orfaos)
    )


def _niveis(signals: list[Signal]) -> list[str]:
    return [s.level for s in signals]


# ── `data is None` → compatibilidade retroativa com a 5.8 ─────────────────────────────────────


def test_completeness_none_nao_emite_sinal() -> None:
    """Motor chamado sem a entrada (o caso da 5.8) → zero sinal de completude, não um verde."""
    assert _completeness_signals(None) == []


# ── `contas == []` → o estado de TODOS os tenants no dia do deploy ────────────────────────────


def test_nenhuma_conta_cadastrada_emite_um_amarelo() -> None:
    """Sem conta cadastrada o e1p realmente **não sabe** se os lançamentos estão completos.

    Decisão do fundador (2026-07-29): este 🟡 aparece para **todos** os tenants, sem opt-in e sem
    botão de dispensar — esconder o sinal seria a mesma mentira por omissão que a Onda 0 consertou.
    """
    signals = _sinais()
    assert len(signals) == 1
    assert signals[0].level == AMARELO
    assert signals[0].source == "completude"
    assert "Nenhuma conta bancária cadastrada" in signals[0].explanation


# ── 🔴 fora da banda — um por conta, nomeando a conta (AC4 / decisão F3) ──────────────────────


def test_cenario_do_epic_dois_vermelhos_nomeando_as_contas() -> None:
    """Epic §3.2: +R$ 1.200 / −R$ 900 / +R$ 40 → **dois** 🔴 nomeados; o consolidado não aparece.

    O consolidado (+R$ 340) é "saudável" e esconde dois problemas. Se um dia alguém trocar os
    sinais por conta por um único sinal agregado, este teste cai.
    """
    signals = _sinais(
        _conta("Itaú PJ", divergencia=120_000),
        _conta("Bradesco PJ", divergencia=-90_000),
        _conta("Nubank PJ", divergencia=4_000),
    )
    vermelhos = [s for s in signals if s.level == VERMELHO]
    assert len(vermelhos) == 2, f"esperava 2 🔴 (um por conta fora da banda), veio {signals}"
    assert "Itaú PJ" in vermelhos[0].explanation
    assert "R$ 1.200,00" in vermelhos[0].explanation
    assert "Bradesco PJ" in vermelhos[1].explanation
    assert "R$ 900,00" in vermelhos[1].explanation

    texto = " ".join(s.explanation for s in signals)
    # O consolidado NUNCA aparece como se fosse o diagnóstico (F3).
    assert "340" not in texto, f"o consolidado vazou para a explicação: {texto}"
    # A terceira conta está DENTRO da banda (R$ 40 < R$ 50) → silêncio sobre ela.
    assert "Nubank PJ" not in texto


def test_divergencia_negativa_diz_que_faltam_lancamentos_de_saida() -> None:
    """REQ-14: banco abaixo do sistema = provável **saída** não lançada — o achado de maior valor.

    A explicação precisa ser acionável, não só numérica: é ela que manda o usuário procurar a conta
    a pagar que ele esqueceu de lançar."""
    (sinal,) = [s for s in _sinais(_conta(divergencia=-90_000)) if s.level == VERMELHO]
    assert "provavelmente faltam lançamentos de saída" in sinal.explanation
    assert "tolerância de R$ 50,00" in sinal.explanation


def test_divergencia_positiva_diz_que_faltam_lancamentos_de_entrada() -> None:
    (sinal,) = [s for s in _sinais(_conta(divergencia=120_000)) if s.level == VERMELHO]
    assert "provavelmente faltam lançamentos de entrada" in sinal.explanation


def test_borda_divergencia_igual_a_tolerancia_e_dentro() -> None:
    """`abs(divergencia) == tolerancia` → **DENTRO** da banda: silêncio (🟢), nunca 🔴.

    Mesma semântica da 8.5 (`abs(div) <= tol`). Duas verdades sobre a mesma comparação seriam o
    caminho para o produto discordar de si mesmo entre a tela de conferência e o diagnóstico."""
    assert _niveis(_sinais(_conta(divergencia=5_000, tolerancia=5_000))) == [VERDE]
    assert _niveis(_sinais(_conta(divergencia=-5_000, tolerancia=5_000))) == [VERDE]
    # Um centavo além da banda já é 🔴 — a borda está exatamente onde se espera.
    assert _niveis(_sinais(_conta(divergencia=5_001, tolerancia=5_000))) == [VERMELHO]
    assert _niveis(_sinais(_conta(divergencia=-5_001, tolerancia=5_000))) == [VERMELHO]


def test_motor_nao_recalcula_a_banda_usa_a_tolerancia_recebida() -> None:
    """A banda chega PRONTA da 8.5 (`max(R$ 50; 0,5%)`). O motor só compara.

    Com uma tolerância absurda (R$ 10.000) uma divergência de R$ 1.200 fica DENTRO — o que prova
    que o motor não está recalculando `max(R$ 50; 0,5%)` por conta própria."""
    assert _niveis(_sinais(_conta(divergencia=120_000, tolerancia=1_000_000))) == [VERDE]


# ── 🟡 "não sei" — no máximo UM por conta (ratificação D-2, Ajuste 2) ─────────────────────────


def test_tres_contas_nenhuma_conferida_geram_tres_sinais() -> None:
    """3 contas nunca conferidas → **3** sinais, não 6. É a razão de existir do Ajuste 2.

    Cada conta é simultaneamente "sem saldo declarado na janela" e "nunca confirmada"; a regra
    pré-fusão emitiria um 🟡 para cada um dos dois fatos, em cada conta."""
    contas = [
        _conta("Itaú PJ", divergencia=None, tolerancia=0, dias=None),
        _conta("Bradesco PJ", divergencia=None, tolerancia=0, dias=None),
        _conta("Nubank PJ", divergencia=None, tolerancia=0, dias=None),
    ]
    signals = _sinais(*contas)
    assert len(signals) == 3, f"esperava 3 sinais (1 por conta), veio {len(signals)}: {signals}"
    assert _niveis(signals) == [AMARELO, AMARELO, AMARELO]
    # Cada frase nomeia a SUA conta — nenhuma fala pelo tenant inteiro.
    for conta, sinal in zip(contas, signals, strict=True):
        assert conta.account_name in sinal.explanation


def test_fusao_um_unico_amarelo_diz_os_dois_motivos() -> None:
    """Conta sem saldo na janela **e** nunca confirmada → UM 🟡 que diz os dois casos."""
    (sinal,) = _sinais(_conta("Itaú PJ", divergencia=None, tolerancia=0, dias=None))
    assert sinal.level == AMARELO
    assert "sem saldo declarado na janela" in sinal.explanation
    assert "nunca confirmado" in sinal.explanation


def test_contas_com_frescor_diferente_geram_um_amarelo_cada_nomeando_a_conta() -> None:
    """Uma nunca confirmada e outra confirmada há 60 dias → duas frases distintas.

    Substitui o teste do `max()` que a ratificação eliminou: "nunca confirmada" e "60 dias" não são
    o mesmo fato colapsado no pior caso — são duas afirmações sobre duas contas."""
    signals = _sinais(
        _conta("Itaú PJ", divergencia=None, tolerancia=0, dias=None),
        _conta("Bradesco PJ", divergencia=0, dias=60),
    )
    assert len(signals) == 2
    assert "Itaú PJ" in signals[0].explanation and "nunca confirmado" in signals[0].explanation
    assert (
        "Bradesco PJ" in signals[1].explanation
        and "confirmado há 60 dias" in signals[1].explanation
    )


def test_vermelho_e_amarelo_coexistem_na_mesma_conta() -> None:
    """Fora da banda **e** desatualizada → 1 🔴 + 1 🟡: afirmações diferentes (D-2, Ajuste 2)."""
    signals = _sinais(_conta("Itaú PJ", divergencia=-90_000, dias=60))
    assert _niveis(signals) == [VERMELHO, AMARELO]
    assert all("Itaú PJ" in s.explanation for s in signals)
    assert "confirmado há 60 dias" in signals[1].explanation


def test_borda_exata_do_limiar_de_45_dias() -> None:
    """`dias == 45` ainda é fresco (silêncio); `46` já é 🟡. O limiar é constante documentada."""
    assert _COMPLETENESS_STALE_DAYS == 45
    assert _niveis(_sinais(_conta(dias=_COMPLETENESS_STALE_DAYS))) == [VERDE]
    assert _niveis(_sinais(_conta(dias=_COMPLETENESS_STALE_DAYS + 1))) == [AMARELO]


def test_none_significa_nao_avaliavel_e_impede_o_verde() -> None:
    """Uma conta não avaliável impede o 🟢 do relatório inteiro — `None` não é zero.

    Com uma conta batendo e outra sem saldo declarado, o motor **não** diz "está tudo batendo":
    diria que conferiu o que não conferiu."""
    signals = _sinais(
        _conta("Itaú PJ", divergencia=0, dias=0),
        _conta("Bradesco PJ", divergencia=None, tolerancia=0, dias=None),
    )
    assert _niveis(signals) == [AMARELO], f"o verde não pode aparecer aqui: {signals}"


# ── 🟢 — só quando TUDO está conferido, dentro da banda e fresco ──────────────────────────────


def test_verde_cita_a_maior_divergencia_e_a_tolerancia() -> None:
    signals = _sinais(
        _conta("Itaú PJ", divergencia=350, tolerancia=5_000, dias=2),
        _conta("Bradesco PJ", divergencia=-1_200, tolerancia=5_000, dias=5),
    )
    assert len(signals) == 1
    assert signals[0].level == VERDE
    assert "Está tudo batendo" in signals[0].explanation
    # A MAIOR divergência absoluta é a que qualifica o verde (a mais perto de estourar a banda).
    assert "R$ 12,00" in signals[0].explanation
    assert "Bradesco PJ" in signals[0].explanation
    assert "R$ 50,00" in signals[0].explanation


def test_verde_e_deterministico_no_empate() -> None:
    """Empate na maior divergência → vence a primeira conta da lista (saída estável)."""
    a = _conta("Conta A", divergencia=1_000, dias=1)
    b = _conta("Conta B", divergencia=-1_000, dias=1)
    assert "Conta A" in _sinais(a, b)[0].explanation
    assert "Conta B" in _sinais(b, a)[0].explanation


# ── Bloco 2 (movimentos órfãos) — declarado e DORMENTE até a Onda 3 (AC6) ─────────────────────


def test_movimentos_sem_contrapartida_nasce_zero_e_nao_emite_sinal() -> None:
    """O default do contrato é 0 — a regra existe, mas não dispara na Onda 1."""
    assert CompletenessInput(contas=[]).movimentos_sem_contrapartida == 0
    assert _niveis(_sinais(_conta(), orfaos=0)) == [VERDE]


def test_regra_dos_movimentos_orfaos_esta_escrita_para_a_onda_3() -> None:
    """Quando a Onda 3 alimentar o número, o sinal já existe — e impede o 🟢."""
    signals = _sinais(_conta(), orfaos=3)
    assert _niveis(signals) == [AMARELO], "com movimento órfão não há 'está tudo batendo'"
    assert "3 movimentos sem conta correspondente" in signals[0].explanation


# ── Formatação de dinheiro (função pura, privada, sem float) ──────────────────────────────────


def test_brl_formata_centavos_em_reais_legiveis() -> None:
    assert _brl(0) == "R$ 0,00"
    assert _brl(350) == "R$ 3,50"
    assert _brl(234_000) == "R$ 2.340,00"
    assert _brl(1_234_567_890) == "R$ 12.345.678,90"
    assert _brl(-90_000) == "-R$ 900,00"
    # Um valor que um `cents/100` em float arredondaria errado continua exato (aritmética inteira).
    assert _brl(70_007) == "R$ 700,07"


# ── Integração com `compute_signals` (ainda 100% puro) ────────────────────────────────────────


def test_engine_input_aceita_completeness_e_o_default_e_none() -> None:
    """`completeness` é o ÚLTIMO campo e tem default — a assinatura da 5.8 segue válida."""
    antigo = EngineInput(
        margins=[MarginTrend("Alpha", 0.30, 0.22, "1 mês")],
        runway_days=200,
        projection_windows=[ProjectionWindowInput(30, False)],
        investments=[InvestmentReturn("CDB", 0.01)],
    )
    assert antigo.completeness is None
    # Construção POSICIONAL da 5.8 (4 argumentos) continua funcionando.
    posicional = EngineInput([], None, [], [])
    assert posicional.completeness is None
    assert compute_signals(posicional) == []


def test_completude_entra_no_compute_signals_com_a_prioridade_por_nivel() -> None:
    data = EngineInput(
        margins=[],
        runway_days=None,
        projection_windows=[],
        investments=[],
        completeness=CompletenessInput(
            contas=[
                _conta("Itaú PJ", divergencia=-90_000, dias=60),
                _conta("Bradesco PJ", divergencia=None, tolerancia=0, dias=None),
            ]
        ),
    )
    signals = compute_signals(data)
    assert _niveis(signals) == [VERMELHO, AMARELO, AMARELO]
    assert all(s.source == "completude" for s in signals)


def test_determinismo_da_regra_de_completude() -> None:
    """Mesma entrada → mesma lista, sempre. Nenhuma dependência de relógio dentro do motor:
    `dias_desde_ultima_conferencia` chega calculado de fora, de propósito."""
    data = CompletenessInput(
        contas=[
            _conta("Itaú PJ", divergencia=-90_000, dias=60),
            _conta("Bradesco PJ", divergencia=None, tolerancia=0, dias=None),
            _conta("Nubank PJ", divergencia=10, dias=1),
        ]
    )
    primeiro = _completeness_signals(data)
    assert primeiro == _completeness_signals(data) == _completeness_signals(data)


# ── IV1 — o gate de pureza do `engine.py` (varredura estática) ────────────────────────────────

# Símbolos que **não podem** aparecer no motor. Cada um representa uma classe de dependência que
# tornaria o motor não-testável sem infraestrutura — e que a Story 8.6 teria sido a primeira a
# introduzir se tivesse buscado o nome da conta lá dentro em vez de recebê-lo pronto.
_IMPORTS_PROIBIDOS = (
    "sqlalchemy",          # nenhuma Session, nenhum select
    "app.db",              # nenhuma sessão/engine do projeto
    "app.core.ai",         # nenhuma IA origina número (o narrador entra DEPOIS)
    "app.core.anonymizer",  # não há PII a mascarar aqui: o narrador anonimiza na saída
    "app.modules.bank",    # a conferência chega adaptada por diagnostics.py
    "app.modules",         # nenhum outro módulo de negócio: o motor não "vê" a camada de I/O
)


def _imported_modules(path: pathlib.Path) -> list[str]:
    """Módulos importados, via AST (não por texto) — a docstring do motor **precisa** poder citar
    `Session`/`core.ai`/`bank` em prosa sem quebrar o teste. Mesmo padrão de `test_money_planes.py`
    e `test_tenancy_guard.py`."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            modules.append(f"{'.' * node.level}{node.module or ''}")
    return modules


def test_iv1_engine_permanece_estritamente_puro() -> None:
    """O motor não importa `Session`, banco, IA, anonimizador nem nenhum outro módulo de negócio.

    Transforma a frase "NÃO NEGOCIÁVEL" da docstring do `engine.py` em **gate**. Sem isto, a
    próxima story que precisar de "só uma queryzinha" no motor descobre tarde demais que quebrou a
    propriedade que torna todos os testes deste arquivo possíveis sem banco.
    """
    ofensores = [
        module
        for module in _imported_modules(ENGINE_PATH)
        if any(module.startswith(proibido) for proibido in _IMPORTS_PROIBIDOS)
        or module.startswith(".")  # import relativo: anomalia (Constitution, Artigo VI)
    ]
    assert not ofensores, (
        f"engine.py deixou de ser PURO (IV1/NFR3): importa {ofensores}. A camada de I/O é "
        "diagnostics.py — monte a entrada lá e passe a dataclass pronta para o motor."
    )


def test_iv1_engine_nao_usa_sessao_nem_relogio_por_texto_cru() -> None:
    """O equivalente do `grep`: pega o que o AST não pegaria (uso dinâmico, `datetime.now(...)`).

    Redundante de propósito, como em `test_money_planes.py`. `datetime.now`/`date.today` entram na
    lista porque relógio dentro do motor destruiria o determinismo tanto quanto uma query — e a
    regra de completude é a primeira que teria a tentação de calcular "dias desde" sozinha.
    """
    codigo = ENGINE_PATH.read_text(encoding="utf-8")
    # Só o CÓDIGO: a prosa das docstrings cita `Session`, `core.ai` e `bank` legitimamente.
    arvore = ast.parse(codigo, filename=str(ENGINE_PATH))
    fontes = [
        ast.get_source_segment(codigo, node) or ""
        for node in ast.walk(arvore)
        if isinstance(node, ast.Call | ast.Attribute | ast.Name)
    ]
    proibidos = ("datetime.now", "date.today", "db.execute", "db.scalars", "session")
    ofensores = sorted(
        {p for p in proibidos for trecho in fontes if p in trecho.lower()}
    )
    assert not ofensores, (
        f"engine.py passou a depender de relógio/banco em runtime: {ofensores}. O motor recebe "
        "tudo calculado (inclusive `dias_desde_ultima_conferencia`) — é o que o torna previsível."
    )
