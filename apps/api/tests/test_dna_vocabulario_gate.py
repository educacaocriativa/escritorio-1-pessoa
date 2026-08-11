"""§6.3 — o vocabulário do DNA tem uma porta só, e ela é guardada.

`facts.record` tem guarda mecânica equivalente (o `kind` tem de começar pelo `module`) e
`audit.record` **não tem nenhuma** — `account_deleted`, sem pontos e fora do padrão
`<entidade>.<entidade>.<verbo>`, é a prova de que a convenção sozinha não segura o vocabulário.
Sem esta guarda, quatro actions × três sources viram doze strings, e é assim que 117 viram 200.

**Controle positivo obrigatório** em cada asserção: um gate que deixasse de encontrar as chamadas
(glob quebrado, `audit` importado com outro nome, pasta renomeada) passaria **verde por vacuidade**
— a família do "teste que passa e não prova nada" que o Epic 8 documenta oito vezes.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.modules.dna import eventos

_DNA_DIR = Path(__file__).resolve().parents[1] / "app" / "modules" / "dna"

# A allowlist tem UM membro, e é esse o ponto. Mesmo padrão de `_CHAMADORES_PERMITIDOS` do
# `sync_origin_movement`: quem precisar entrar aqui entra COM a justificativa, e é isso que faz a
# revisão acontecer — não a linha na lista.
_PODE_CHAMAR_AUDIT = {"eventos.py"}


def _chamadas_a_audit_record(fonte: str) -> list[int]:
    """Linhas de `audit.record(...)` — a forma que qualquer call site do repo usa."""
    linhas: list[int] = []
    for no in ast.walk(ast.parse(fonte)):
        if (
            isinstance(no, ast.Call)
            and isinstance(no.func, ast.Attribute)
            and no.func.attr == "record"
            and isinstance(no.func.value, ast.Name)
            and no.func.value.id == "audit"
        ):
            linhas.append(no.lineno)
    return linhas


def test_o_scanner_acha_o_que_promete_achar():
    """Controle positivo DO SCANNER. Sem ele, um scanner quebrado aprova o módulo inteiro."""
    achou = _chamadas_a_audit_record(
        "from app.core import audit\n"
        "audit.record(db, tenant_id=t, actor=a, action='dna.inventada', target='')\n"
    )
    assert achou == [2]
    # E o não-membro: uma chamada que NÃO é `audit.record` não pode ser contada.
    assert _chamadas_a_audit_record("facts.record(db, kind='crm.lead.created')\n") == []


def test_so_o_eventos_py_chama_audit_record():
    ofensores: list[str] = []
    for arquivo in sorted(_DNA_DIR.glob("*.py")):
        if arquivo.name in _PODE_CHAMAR_AUDIT:
            continue
        for linha in _chamadas_a_audit_record(arquivo.read_text(encoding="utf-8")):
            ofensores.append(f"{arquivo.name}:{linha}")
    assert not ofensores, (
        "Estes pontos gravam trilha por fora da porta do módulo, e por isso escapam da validação "
        f"de vocabulário. Use `eventos.registrar(...)`: {ofensores}"
    )


def test_a_porta_do_modulo_existe_de_fato():
    """Controle positivo do gate acima: se NINGUÉM mais chama, é porque `eventos.py` chama."""
    fonte = (_DNA_DIR / "eventos.py").read_text(encoding="utf-8")
    assert _chamadas_a_audit_record(fonte), (
        "`eventos.py` deixou de chamar `audit.record`. O gate acima passaria verde sobre um "
        "módulo que não grava trilha nenhuma — exatamente a vacuidade que ele existe para impedir."
    )


def test_toda_action_declarada_comeca_com_dna():
    assert eventos.ACTIONS, "a tupla está vazia: não há vocabulário para guardar"
    for action in eventos.ACTIONS:
        assert action.startswith(eventos.PREFIXO), action


def test_a_tupla_e_o_conjunto_que_a_spec_fechou():
    """A instanciação obrigatória: o conjunto tem membros escritos, e são estes quatro."""
    assert eventos.ACTIONS == (
        "dna.answer.save",
        "dna.answer.skip",
        "dna.nucleo.open",
        "dna.nucleo.abandon",
    )
    assert set(eventos.EVENTOS_DO_NUCLEO) == {"open", "abandon"}


@pytest.mark.parametrize("intrusa", ["settings.perfil.update", "dna.inventada", "account_deleted"])
def test_registrar_recusa_action_fora_da_tupla(intrusa: str):
    """O controle positivo que importa: a guarda MORDE.

    `dna.inventada` é o não-membro sutil — começa com `dna.` e mesmo assim é recusada, porque o
    prefixo sozinho não é o contrato. `account_deleted` é o membro real do repo que prova que a
    convenção sem guarda não segura nada.
    """
    with pytest.raises(eventos.VocabularioError):
        eventos.registrar(db=None, tenant_id="t", actor="u", action=intrusa, target="")
