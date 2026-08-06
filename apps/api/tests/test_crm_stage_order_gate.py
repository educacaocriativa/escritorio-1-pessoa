"""Guarda ESTÁTICA da fila do Kanban: quem move card, carimba.

`clients.stage_entered_at` é a ordem da fila de cada coluna do Funil (spec
`2026-08-05-crm-ordem-de-entrada-na-etapa-design.md`). Existem hoje três caminhos que escrevem
`Client.stage_id`, e a spec escolheu uma COLUNA em vez de derivar de `client_events` porque
esse log não registra troca de etapa de forma completa.

O preço dessa escolha é este arquivo. Um quarto caminho que escreva `stage_id` sem carimbar
`stage_entered_at` **não quebra teste nenhum**: nada estoura, nenhuma rota falha, a coluna só
passa a devolver a fila fora de ordem — e o dono atende na ordem errada sem nada avisar.

Mesma família de `test_tenancy_guard.py` e `test_money_planes.py`: varredura barata, sem
ferramenta externa, contra a regressão que os testes de comportamento não alcançam.
"""
from __future__ import annotations

import ast
import pathlib

CRM_DIR = pathlib.Path(__file__).resolve().parents[1] / "app" / "modules" / "crm"

CAMPO_ETAPA = "stage_id"
CAMPO_CARIMBO = "stage_entered_at"

# Funções que escrevem `stage_id` e NÃO carimbam, por decisão registrada.
ALLOWLIST = {
    # Arquivar uma etapa é ato administrativo do dono, não mudança na situação do cliente.
    # Recarimbar jogaria todo card da coluna, em bloco, para o fim da fila de destino — e a
    # fila existe justamente para atender por antiguidade. Ver a seção 3 da spec.
    "archive_stage",
}


def _atribui(no: ast.FunctionDef, campo: str) -> bool:
    """A função atribui `campo`, por atributo ou dentro de um dict de `.update()`?"""
    for filho in ast.walk(no):
        # `algo.campo = ...`
        if isinstance(filho, ast.Assign):
            for alvo in filho.targets:
                if isinstance(alvo, ast.Attribute) and alvo.attr == campo:
                    return True
        # `.update({Client.campo: ...})`
        if isinstance(filho, ast.Dict):
            for chave in filho.keys:
                if isinstance(chave, ast.Attribute) and chave.attr == campo:
                    return True
    return False


def _funcoes_do_crm() -> list[tuple[str, ast.FunctionDef]]:
    encontradas: list[tuple[str, ast.FunctionDef]] = []
    arquivos = sorted(p for p in CRM_DIR.rglob("*.py") if "__pycache__" not in p.parts)
    assert arquivos, f"Nenhum .py encontrado em {CRM_DIR} — teste desatualizado?"
    for arquivo in arquivos:
        arvore = ast.parse(arquivo.read_text(encoding="utf-8"))
        for no in ast.walk(arvore):
            if isinstance(no, ast.FunctionDef):
                encontradas.append((f"{arquivo.name}::{no.name}", no))
    return encontradas


def test_quem_escreve_stage_id_carimba_stage_entered_at():
    infratores = [
        rotulo
        for rotulo, no in _funcoes_do_crm()
        if _atribui(no, CAMPO_ETAPA)
        and not _atribui(no, CAMPO_CARIMBO)
        and no.name not in ALLOWLIST
    ]
    assert not infratores, (
        f"Função(ões) que movem card entre etapas sem carimbar `{CAMPO_CARIMBO}`: "
        f"{sorted(infratores)}. A ordem das colunas do Kanban é a ordem de entrada na etapa; "
        "sem o carimbo o card entra na fila na posição errada e NADA falha. Carimbe "
        f"`client.{CAMPO_CARIMBO} = datetime.now(UTC)` junto com a troca de `{CAMPO_ETAPA}`, ou "
        "— se a função tiver motivo para preservar a antiguidade — adicione-a à ALLOWLIST "
        "deste arquivo COM o motivo escrito."
    )


def test_allowlist_nao_apodrece():
    """Nome na allowlist que não existe mais é allowlist mentindo sobre o código."""
    nomes = {no.name for _, no in _funcoes_do_crm()}
    fantasmas = sorted(ALLOWLIST - nomes)
    assert not fantasmas, f"ALLOWLIST cita função inexistente: {fantasmas}"
