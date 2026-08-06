"""Gate estrutural: nenhum teste define sua âncora de "hoje" em UTC cru.

Depois do PR #78 o sistema inteiro vive no fuso do tenant — `hoje_do_tenant(db)` é a única
âncora de "hoje" (`CLAUDE.md` §6.0). Doze arquivos de teste ficaram para trás ancorando em
`datetime.now(UTC).date()`, e **a divergência é invisível 21 horas por dia**: das 21h à
meia-noite em UTC−3 a data UTC já virou e a do tenant não, então o teste espera amanhã e o
serviço responde hoje. Resultado medido em 2026-08-05: 20 falhas às 00:28 UTC, zero às 20:33
UTC do mesmo dia — e um CI reprovado por um defeito que ninguém introduziu naquele PR.

Por que um gate, e não só a correção: quem reintroduzir a âncora em UTC vai ver a suíte verde,
abrir o PR com a suíte verde, e o custo cai numa madrugada, sobre outra pessoa. É a mesma
classe de problema que a INSTANCIAÇÃO OBRIGATÓRIA (Epic 8) descreve — sem consumidor mecânico
que proteste, acertar depende de alguém lembrar.

O gate é ESTREITO de propósito: olha a **definição da âncora** (`def _hoje`, `TODAY = ...`),
não todo uso de `datetime.now(UTC)`. Datas com margem folgada (`+ timedelta(days=30)` para
"uma data claramente futura") não viram falha quando o dia desliza, e proibi-las trocaria um
gate útil por ruído.

O idioma correto já existia no repo (`test_bank_corte_de_data.py`, `test_bank_transfers.py`):
`tenant_today(DEFAULT_TENANT_TIMEZONE)` — a primitiva pura de `core.tz`, sem `db` e sem um
segundo relógio, já que os tenants de teste ficam com o fuso padrão.
"""
from __future__ import annotations

import ast
from pathlib import Path

TESTS_DIR = Path(__file__).parent

ANCORAS_FUNCAO = {"_hoje", "_today"}
ANCORAS_CONSTANTE = {"TODAY", "HOJE"}


def _usa_utc_cru(no: ast.AST) -> bool:
    """`datetime.now(UTC).date()` ou `date.today()` dentro deste nó da árvore."""
    for filho in ast.walk(no):
        if not isinstance(filho, ast.Call) or not isinstance(filho.func, ast.Attribute):
            continue
        # date.today()
        if filho.func.attr == "today":
            return True
        # ....now(UTC).date()
        if filho.func.attr == "date" and isinstance(filho.func.value, ast.Call):
            interno = filho.func.value.func
            if isinstance(interno, ast.Attribute) and interno.attr == "now":
                return True
    return False


def _violacoes(fonte: str) -> list[str]:
    """Analisa a ÁRVORE, não o texto: docstring e comentário citam o padrão antigo ao explicá-lo,
    e uma varredura textual acusaria justamente os arquivos que já foram corrigidos."""
    achados: list[str] = []
    arvore = ast.parse(fonte)
    for no in arvore.body:
        if isinstance(no, ast.FunctionDef) and no.name in ANCORAS_FUNCAO:
            corpo = [c for c in no.body if not isinstance(c, ast.Expr)]  # tira a docstring
            if any(_usa_utc_cru(c) for c in corpo):
                achados.append(f"linha {no.lineno}: def {no.name}()")
        elif isinstance(no, ast.Assign):
            nomes = {a.id for a in no.targets if isinstance(a, ast.Name)}
            if nomes & ANCORAS_CONSTANTE and _usa_utc_cru(no.value):
                achados.append(f"linha {no.lineno}: {', '.join(sorted(nomes))} = ...")
    return achados


def _tem_ancora(arvore: ast.Module) -> bool:
    for no in arvore.body:
        if isinstance(no, ast.FunctionDef) and no.name in ANCORAS_FUNCAO:
            return True
        if isinstance(no, ast.Assign) and any(
            isinstance(a, ast.Name) and a.id in ANCORAS_CONSTANTE for a in no.targets
        ):
            return True
    return False


def _segunda_opiniao(fonte: str) -> list[str]:
    """Num arquivo que JÁ declara sua âncora, outro cálculo de "hoje" é uma segunda opinião.

    Este é o ponto cego que a primeira versão do gate tinha: `test_receipts.py` teve o helper
    `_hoje()` corrigido e continuou falhando, porque `_pay()` montava `paid_on` com
    `datetime.now(UTC).date()` **inline**, sem passar pelo helper. O arquivo tinha duas âncoras
    discordando entre si.

    Vale só para arquivos COM âncora: quem não declara uma está usando data com margem folgada
    (`+ timedelta(days=30)`), que não vira falha quando o dia desliza.
    """
    arvore = ast.parse(fonte)
    if not _tem_ancora(arvore):
        return []
    achados: list[str] = []
    for no in ast.walk(arvore):
        if isinstance(no, ast.FunctionDef) and no.name in ANCORAS_FUNCAO:
            continue  # a própria âncora já é coberta por `_violacoes`
        if isinstance(no, ast.Call) and _usa_utc_cru(no):
            achados.append(f"linha {no.lineno}")
    return achados


def test_nenhuma_ancora_de_hoje_em_utc_cru() -> None:
    culpados: dict[str, list[str]] = {}
    for arquivo in sorted(TESTS_DIR.glob("test_*.py")):
        if arquivo.name == Path(__file__).name:
            continue
        achados = _violacoes(arquivo.read_text(encoding="utf-8"))
        if achados:
            culpados[arquivo.name] = achados

    assert not culpados, (
        "Âncora de 'hoje' em UTC cru — o serviço usa o fuso do tenant desde o PR #78. Use "
        f"`tenant_today(DEFAULT_TENANT_TIMEZONE)`:\n{culpados}"
    )


def test_arquivo_com_ancora_nao_calcula_hoje_por_fora() -> None:
    culpados: dict[str, list[str]] = {}
    for arquivo in sorted(TESTS_DIR.glob("test_*.py")):
        if arquivo.name == Path(__file__).name:
            continue
        achados = _segunda_opiniao(arquivo.read_text(encoding="utf-8"))
        if achados:
            culpados[arquivo.name] = achados

    assert not culpados, (
        "Este arquivo já declara sua âncora de 'hoje' — calcular outra por fora faz as duas "
        f"discordarem 3h por dia. Use o helper do próprio arquivo:\n{culpados}"
    )


def test_o_gate_reconhece_uma_ancora_ruim_e_ignora_a_boa() -> None:
    """Instanciação obrigatória: um membro E um não-membro. Sem o não-membro o gate poderia
    estar acusando tudo; sem o membro, poderia não acusar nada."""
    ruim = "def _hoje():\n    return datetime.now(UTC).date()\n"
    ruim_constante = "TODAY = date.today()\n"
    boa = "def _hoje():\n    return tenant_today(DEFAULT_TENANT_TIMEZONE)\n"
    # O padrão antigo citado numa DOCSTRING é explicação, não âncora — não pode acusar.
    boa_com_docstring = (
        'def _hoje():\n    """Nunca `date.today()` solto."""\n'
        "    return tenant_today(DEFAULT_TENANT_TIMEZONE)\n"
    )

    assert _violacoes(ruim), "não pegaria a âncora que causou as 20 falhas"
    assert _violacoes(ruim_constante), "não pegaria a âncora em forma de constante"
    assert not _violacoes(boa)
    assert not _violacoes(boa_com_docstring), "acusaria um arquivo já corrigido"
