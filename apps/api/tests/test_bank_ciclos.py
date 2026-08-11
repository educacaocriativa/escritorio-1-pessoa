"""O ciclo da conferência — o corte do termo P4, a legibilidade e o histórico.

O que estes testes protegem, em uma frase: **um número medido sobre base incompleta não é gate.**
O épico já pagou essa lição duas vezes — em 2026-07-30, quando a divergência da Onda 1 media a
ausência de uma porta e teria pedido a onda mais cara; e na Story 8.20, quando a comparação
degenerada emitia 🟢 sobre razão bancário vazio. O ciclo é o instrumento que impede a terceira.
"""
from __future__ import annotations

from datetime import date

from app.modules.bank import reconciliation

# A Onda 3 entrou em `main` neste dia (commit 54bb1d4). É um fato do REPOSITÓRIO — ao contrário da
# data do deploy — e é exatamente por isso que ele serve de piso e a data do deploy não serviria.
MERGE_DA_ONDA_3 = date(2026, 8, 10)


def test_primeiro_ciclo_medivel_nao_antecede_a_onda_3():
    """O único valor deste módulo que depende de um fato FORA do repositório.

    Cravá-lo cedo demais faz o e1p declarar conferido um ciclo cujo termo **P4 nunca foi medido** —
    e o relatório reporta esse termo como zero **por omissão**, que é a leitura errada que já custou
    uma decisão de produto neste épico.

    ⚠️ O piso **não prova** que a data está certa: o deploy não é um fato do repositório, e nenhum
    teste pode sabê-lo. Ele elimina a classe de erro barata (cravar no passado) e deixa registrado,
    para quem mover a data, que existe um piso a mover junto.
    """
    assert reconciliation.PRIMEIRO_CICLO_MEDIVEL > MERGE_DA_ONDA_3


def test_primeiro_ciclo_medivel_e_primeiro_dia_do_mes():
    """O corte é por CICLO, não por dia — um mês medido pela metade não é um mês medido.

    Uma data no meio do mês faria a condição (d) recusar setembro e aceitar outubro sem que nada na
    fronteira de setembro explicasse por quê.
    """
    assert reconciliation.PRIMEIRO_CICLO_MEDIVEL.day == 1
