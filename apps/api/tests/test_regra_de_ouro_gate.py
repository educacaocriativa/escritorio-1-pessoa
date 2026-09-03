"""Gate estrutural: nenhuma chamada de IA sai sem passar pelo anonimizador.

`core/ai.py` é o ponto único de acesso à Anthropic e seu docstring declara a Regra de Ouro nº 2:
*"todo texto que entra aqui DEVE já estar anonimizado (ver anonymizer.py)"*. **A camada não
verifica nada** — `ai.complete` recebe `user_message` e envia. A regra vive na cabeça de quem
escreve o chamador, e foi assim que cinco chamadas nasceram sem anonimização nenhuma
(`quotes`, `funnels`, `marketing` e as DUAS de `receivables`): o `brief` que o dono digita, o
`prompt` livre do funil, o `topic` do carrossel e a descrição da cobrança iam crus para os
Estados Unidos, e a suíte ficava verde.

Por que um gate, e não só a correção: o repositório já protege invariantes MENORES com gate
(`test_ancora_de_hoje.py`, `test_invariante_do_trilho.py`, `test_dna_vocabulario_gate.py`).
A Regra de Ouro nº 2 é a única com consequência jurídica — a Política de Privacidade em
`/privacidade` afirma ao titular que a anonimização acontece — e era a única sem consumidor
mecânico. Sem ele, o sexto furo nasce igual aos cinco primeiros: sem ninguém ver.

São duas asserções, porque a primeira sozinha não basta:

1. **Presença** — a função que contém a chamada usa `anonymizer`/`AnonymizationContext` e chama
   algum `mask*`. Pega o esquecimento total.
2. **Destino** — o que vai em `user_message=` é o resultado de um `mask*`, não um parâmetro cru.
   Pega o furo mais sutil, que a primeira deixaria passar: mascarar UMA coisa e mandar OUTRA.
   `receivables._compose_dunning` era exatamente isso — trocava o nome por `[NOME]` na mão e
   mandava a descrição inteira sem tocar.

Ambas olham a ÁRVORE, não o texto: este arquivo cita `ai.complete` uma dúzia de vezes ao
explicar-se, e uma varredura textual acusaria justamente quem já está correto.
"""
from __future__ import annotations

import ast
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1] / "app"

_MODULO_IA = "app.core.ai"
_FUNCOES_IA = {"complete", "complete_with_tools"}
_MASCARADORES = {"mask", "mask_literals", "mask_value", "mask_tool_result"}
_SIMBOLOS_DE_ANONIMIZACAO = {"anonymizer", "Anonymizer", "AnonymizationContext"}

# Exceções explícitas. Uma entrada aqui é uma DECISÃO registrada, não um silenciamento: quem
# adicionar precisa escrever por que aquele chamador legitimamente não anonimiza. Fica no gate,
# onde a próxima pessoa lê, e não na cabeça de quem passou por aqui.
#
# Formato: "app/caminho/relativo.py::nome_da_funcao": "motivo"
EXCECOES: dict[str, str] = {
    # (vazia de propósito — todos os chamadores atuais anonimizam)
}

# `core/ai.py` é quem DEFINE `complete`; não é chamador.
ARQUIVOS_IGNORADOS = {"core/ai.py"}


def _arquivos_do_app() -> list[Path]:
    return sorted(
        arquivo
        for arquivo in APP_DIR.rglob("*.py")
        if arquivo.relative_to(APP_DIR).as_posix() not in ARQUIVOS_IGNORADOS
    )


def _importa_direto(arvore: ast.Module) -> set[str]:
    """Nomes de `complete`/`complete_with_tools` trazidos por `from app.core.ai import ...`.

    `juridico/service.py` importa assim, e um gate que só procurasse `ai.complete` daria verde
    para o módulo cujo dado é o mais sensível do produto (segredo de justiça).
    """
    importados: set[str] = set()
    for no in ast.walk(arvore):
        if isinstance(no, ast.ImportFrom) and no.module == _MODULO_IA:
            for alias in no.names:
                if alias.name in _FUNCOES_IA:
                    importados.add(alias.asname or alias.name)
    return importados


def _e_chamada_de_ia(no: ast.Call, importados: set[str]) -> bool:
    func = no.func
    if isinstance(func, ast.Attribute) and func.attr in _FUNCOES_IA:
        return isinstance(func.value, ast.Name) and func.value.id == "ai"
    return isinstance(func, ast.Name) and func.id in importados


def _cadeia_de_funcoes(arvore: ast.Module) -> dict[ast.AST, list[ast.AST]]:
    """Para cada nó, a pilha de funções que o contêm (da mais interna para a mais externa).

    A pilha, e não só a função imediata: em `vima/pergunta.py` o `mask_tool_result` mora numa
    closure e o `mask` da pergunta mora na função de fora. Olhar só uma das duas erraria.
    """
    pilhas: dict[ast.AST, list[ast.AST]] = {}

    def _descer(no: ast.AST, pilha: list[ast.AST]) -> None:
        pilhas[no] = pilha
        proxima = [no, *pilha] if isinstance(no, ast.FunctionDef | ast.AsyncFunctionDef) else pilha
        for filho in ast.iter_child_nodes(no):
            _descer(filho, proxima)

    _descer(arvore, [])
    return pilhas


def _anonimiza(funcoes: list[ast.AST]) -> bool:
    """Alguma função da pilha referencia o anonimizador E chama um `mask*`."""
    tem_simbolo = False
    tem_mascaramento = False
    for funcao in funcoes:
        for no in ast.walk(funcao):
            if isinstance(no, ast.Name) and no.id in _SIMBOLOS_DE_ANONIMIZACAO:
                tem_simbolo = True
            elif isinstance(no, ast.Call):
                alvo = no.func
                if isinstance(alvo, ast.Attribute) and alvo.attr in _MASCARADORES:
                    tem_mascaramento = True
    return tem_simbolo and tem_mascaramento


def _nomes_mascarados(funcoes: list[ast.AST]) -> set[str]:
    """Variáveis que RECEBEM o resultado de um `mask*` — `x = anon.mask(t)` e `x, m = ...`."""
    seguros: set[str] = set()
    for funcao in funcoes:
        for no in ast.walk(funcao):
            if not isinstance(no, ast.Assign) or not isinstance(no.value, ast.Call):
                continue
            alvo = no.value.func
            if not (isinstance(alvo, ast.Attribute) and alvo.attr in _MASCARADORES):
                continue
            for destino in no.targets:
                if isinstance(destino, ast.Name):
                    seguros.add(destino.id)
                elif isinstance(destino, ast.Tuple):
                    seguros.update(
                        elemento.id for elemento in destino.elts if isinstance(elemento, ast.Name)
                    )
    return seguros


def _parametros(funcoes: list[ast.AST]) -> set[str]:
    nomes: set[str] = set()
    for funcao in funcoes:
        args = funcao.args  # type: ignore[attr-defined]
        for grupo in (args.posonlyargs, args.args, args.kwonlyargs):
            nomes.update(arg.arg for arg in grupo)
        for solto in (args.vararg, args.kwarg):
            if solto is not None:
                nomes.add(solto.arg)
    return nomes


def _destino_e_seguro(chamada: ast.Call, funcoes: list[ast.AST]) -> bool:
    """O que vai em `user_message=` saiu de um `mask*` e não é um parâmetro cru.

    Um `user_message` construído inline (f-string com o texto do usuário) reprova aqui de
    propósito: mascarar depois de montar é o único jeito de garantir que nada escapou.
    """
    argumento = next((kw.value for kw in chamada.keywords if kw.arg == "user_message"), None)
    if argumento is None:
        return False  # posicional/desconhecido: o gate não consegue provar, então reprova.

    seguros = _nomes_mascarados(funcoes)
    crus = _parametros(funcoes) - seguros
    referenciados = {no.id for no in ast.walk(argumento) if isinstance(no, ast.Name)}
    if referenciados & crus:
        return False
    return bool(referenciados & seguros)


def _infratores(fonte: str, rotulo: str, *, checar_destino: bool) -> list[str]:
    arvore = ast.parse(fonte)
    importados = _importa_direto(arvore)
    pilhas = _cadeia_de_funcoes(arvore)

    achados: list[str] = []
    for no in ast.walk(arvore):
        if not isinstance(no, ast.Call) or not _e_chamada_de_ia(no, importados):
            continue
        funcoes = pilhas.get(no, [])
        if not funcoes:
            achados.append(f"{rotulo}:{no.lineno} — chamada de IA fora de qualquer função")
            continue
        nome = funcoes[0].name  # type: ignore[attr-defined]
        if f"{rotulo}::{nome}" in EXCECOES:
            continue
        ok = _destino_e_seguro(no, funcoes) if checar_destino else _anonimiza(funcoes)
        if not ok:
            achados.append(f"{rotulo}:{no.lineno} — def {nome}()")
    return achados


def _varrer(*, checar_destino: bool) -> list[str]:
    achados: list[str] = []
    for arquivo in _arquivos_do_app():
        rotulo = f"app/{arquivo.relative_to(APP_DIR).as_posix()}"
        achados.extend(
            _infratores(arquivo.read_text(encoding="utf-8"), rotulo, checar_destino=checar_destino)
        )
    return achados


def test_toda_chamada_de_ia_esta_numa_funcao_que_anonimiza() -> None:
    culpados = _varrer(checar_destino=False)
    assert not culpados, (
        "Regra de Ouro nº 2: `core/ai.py` exige texto já anonimizado e não verifica nada. "
        "Estes chamadores não usam `anonymizer`/`AnonymizationContext` — mascare ANTES de "
        "`ai.complete` e desmascare a resposta localmente (padrão em "
        "`modules/juridico/service.py`):\n  " + "\n  ".join(culpados)
    )


def test_o_texto_que_vai_para_a_ia_e_o_texto_mascarado() -> None:
    culpados = _varrer(checar_destino=True)
    assert not culpados, (
        "`user_message=` não recebe o resultado de um `mask*`. Anonimizar alguma coisa e enviar "
        "outra é o furo que `receivables._compose_dunning` tinha (nome virava [NOME] na mão, "
        "descrição ia crua). Monte o texto inteiro, mascare o texto montado, envie o "
        "mascarado:\n  " + "\n  ".join(culpados)
    )


# ── Instanciação obrigatória ──────────────────────────────────────────────────────────────
#
# Sem um infrator o gate poderia não estar varrendo nada; sem um inocente, poderia estar
# acusando todo mundo. Os pares abaixo são o mínimo para que "verde" signifique alguma coisa —
# foi o que `test_ancora_de_hoje.py` ensinou quando a primeira versão do gate dele passou verde
# sobre um arquivo que continuava quebrado.

_INFRATOR = """
from app.core import ai

def gerar(db, tenant_id, brief):
    return ai.complete(db=db, tenant_id=tenant_id, task="x", system="s", user_message=brief)
"""

_CORRETO = """
from app.core import ai
from app.core.anonymizer import anonymizer

def gerar(db, tenant_id, brief):
    seguro, mapa = anonymizer.mask(brief)
    r = ai.complete(db=db, tenant_id=tenant_id, task="x", system="s", user_message=seguro)
    return anonymizer.unmask(r.text, mapa)
"""

# Importa `complete` direto, como `juridico/service.py`. Um gate que só procurasse `ai.complete`
# daria verde aqui.
_INFRATOR_IMPORT_DIRETO = """
from app.core.ai import complete

def gerar(db, tenant_id, brief):
    return complete(db=db, tenant_id=tenant_id, task="x", system="s", user_message=brief)
"""

# Anonimiza — mas manda outra coisa. Passa na primeira asserção e reprova na segunda.
_INFRATOR_MANDA_OUTRA_COISA = """
from app.core import ai
from app.core.anonymizer import anonymizer

def gerar(db, tenant_id, brief, descricao):
    seguro, mapa = anonymizer.mask(brief)
    return ai.complete(db=db, tenant_id=tenant_id, task="x", system="s", user_message=descricao)
"""


def test_o_gate_reconhece_o_infrator_e_ignora_quem_esta_correto() -> None:
    assert _infratores(_INFRATOR, "x.py", checar_destino=False)
    assert _infratores(_INFRATOR_IMPORT_DIRETO, "x.py", checar_destino=False), (
        "não pegaria `from app.core.ai import complete` — o padrão do módulo Jurídico"
    )
    assert not _infratores(_CORRETO, "x.py", checar_destino=False)


def test_o_gate_de_destino_pega_quem_mascara_uma_coisa_e_manda_outra() -> None:
    assert not _infratores(_INFRATOR_MANDA_OUTRA_COISA, "x.py", checar_destino=False), (
        "este infrator TEM anonimizador; quem tem de pegá-lo é a asserção de destino"
    )
    assert _infratores(_INFRATOR_MANDA_OUTRA_COISA, "x.py", checar_destino=True)
    assert not _infratores(_CORRETO, "x.py", checar_destino=True)


def test_a_varredura_encontra_os_chamadores_reais() -> None:
    """Se um refactor mover `core/ai.py` ou renomear as funções, o gate fica verde por vacuidade.

    Esta asserção é o cinto: o app TEM chamadas de IA, e o gate tem de enxergá-las.
    """
    vistas = 0
    for arquivo in _arquivos_do_app():
        arvore = ast.parse(arquivo.read_text(encoding="utf-8"))
        importados = _importa_direto(arvore)
        vistas += sum(
            1
            for no in ast.walk(arvore)
            if isinstance(no, ast.Call) and _e_chamada_de_ia(no, importados)
        )
    assert vistas >= 5, f"o gate só enxergou {vistas} chamadas de IA — está varrendo o quê?"
