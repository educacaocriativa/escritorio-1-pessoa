"""**Teste de ausência** — `investment_accounts.principal_cents` está congelada (Onda 2b-ii).

Quem ler a coluna vai receber `0` (ou o que sobrou de antes da onda), nunca o principal real. E
**nada quebra** se alguém voltar a lê-la: a coluna existe, tem valor, a leitura funciona. Só o dono,
meses depois, veria a tela discordar do extrato sobre quanto ele tem aplicado.

Este teste é o consumidor mecânico que essa mudança não tem sozinha.

**Precedente exato:** `tenant_profiles.timezone`, congelada em 2026-08-07 (migration 0073). Ela
tinha **três** consumidores que a investigação inicial não achou — Agenda, Cockpit e a validade das
notificações. Corrigir só o caminho óbvio teria quebrado os três em silêncio.

`app/scripts/investment_audit.py` lê a coluna **de propósito**, para comparar com o derivado, e está
fora do alcance desta varredura **por construção**: ela só visita `app/modules/`. Não é uma exceção
escrita numa lista — é uma consequência de onde o arquivo mora, e por isso não pode ser ampliada
por engano.
"""
from __future__ import annotations

import ast
from pathlib import Path

_MODULES = Path(__file__).resolve().parents[1] / "app" / "modules"

# O model DEFINE a coluna — mencioná-la lá não é lê-la.
_PODEM_MENCIONAR = {"investments/models.py"}

# Os nomes que o atributo tinha nos call sites reais antes da onda: `a.principal_cents` (router),
# `acc.principal_cents` (service) e `data.principal_cents` (o payload do schema). `data` fica de
# FORA da lista de propósito: ler o campo do REQUEST é legítimo — é assim que a recusa 409 sabe
# que alguém tentou editar. O que está proibido é ler o campo da LINHA.
_BASES_PROIBIDAS = {"a", "acc", "account", "conta", "aplicacao", "InvestmentAccount"}


def _ofensores(raiz: Path, ignorar: set[str], bases: set[str] = _BASES_PROIBIDAS) -> list[str]:
    achados: list[str] = []
    for arquivo in sorted(raiz.rglob("*.py")):
        rel = arquivo.relative_to(raiz).as_posix()
        if rel in ignorar:
            continue
        arvore = ast.parse(arquivo.read_text(encoding="utf-8"))
        for no in ast.walk(arvore):
            if not isinstance(no, ast.Attribute) or no.attr != "principal_cents":
                continue
            base = no.value
            nome = base.id if isinstance(base, ast.Name) else None
            if nome in bases:
                achados.append(f"{rel}:{no.lineno} ({nome}.principal_cents)")
    return achados


def test_ninguem_le_o_principal_da_coluna():
    ofensores = _ofensores(_MODULES, _PODEM_MENCIONAR)
    assert not ofensores, (
        "Estes pontos leem `principal_cents` da COLUNA, que está congelada desde a Onda 2b-ii. "
        "Use `investments.service.principal_derivado(db, acc)` — ou, para várias contas, "
        f"`principais_derivados(db, accs)`: {ofensores}"
    )


def test_o_gate_reprova_quando_a_leitura_existe(tmp_path: Path):
    """**Controle positivo.** Um gate que nunca reprovou nada não é um gate — é um teste que passa
    e não prova nada, a família dominante da Onda 2 (oito ocorrências independentes).
    """
    (tmp_path / "fake.py").write_text(
        "def f(acc):\n    return acc.principal_cents\n", encoding="utf-8"
    )
    assert _ofensores(tmp_path, set()) == ["fake.py:2 (acc.principal_cents)"]


def test_o_gate_nao_reprova_a_leitura_do_PAYLOAD():
    """`data.principal_cents` é o campo do REQUEST, e lê-lo é como a recusa 409 funciona.

    Sem este teste, alguém "endurecendo" o gate acrescentaria `data` à lista de bases proibidas, a
    guarda de `create_account`/`update_account` viraria inalcançável, e o principal voltaria a ser
    editável — com o gate verde o tempo todo.
    """
    assert "data" not in _BASES_PROIBIDAS
