"""O catálogo do DNA: as duas guardas que dão sentido às classes.

Estes testes são o contrato. Sem eles, "Calibração" vira rótulo decorativo e o produto passa a
fingir que ouviu.
"""
import pytest

from app.modules.dna import catalog
from app.modules.dna.catalog import (
    CALIBRACAO,
    FORMATO_ESCOLHA,
    NUCLEO,
    PERGUNTAS,
    POR_KEY,
    RETRATO,
    CatalogoError,
    Opcao,
    Pergunta,
)
from app.modules.vima.absences import LIMIARES_PADRAO


def test_calibracao_exige_consome_e_retrato_proibe():
    for p in PERGUNTAS:
        if p.classe == CALIBRACAO:
            assert p.consome, f"{p.key} é Calibração e não declara consumidor"
        else:
            assert p.consome is None, f"{p.key} é Retrato e declara consumidor"


def test_consome_aponta_para_limiar_que_existe():
    """Um typo aqui produz silêncio perfeito: grava, não consome, não erra."""
    for p in PERGUNTAS:
        if p.consome:
            assert p.consome in LIMIARES_PADRAO, (
                f"{p.key} consome '{p.consome}', que não existe em LIMIARES_PADRAO"
            )


def test_todo_limiar_tem_pergunta():
    """O outro lado: um limiar sem pergunta é um número que ninguém pode calibrar."""
    cobertos = {p.consome for p in PERGUNTAS if p.consome}
    assert cobertos == set(LIMIARES_PADRAO)


def test_key_unica_e_prefixada_pelo_eixo():
    vistas = set()
    for p in PERGUNTAS:
        assert p.key not in vistas, f"key duplicada: {p.key}"
        vistas.add(p.key)
        assert p.key.startswith(f"{p.eixo}."), (
            f"{p.key} não começa com o eixo '{p.eixo}' — é a lição de facts.kind"
        )


def test_pergunta_de_escolha_tem_ao_menos_duas_opcoes():
    for p in PERGUNTAS:
        if p.formato == FORMATO_ESCOLHA:
            assert len(p.opcoes) >= 2, f"{p.key} é escolha com {len(p.opcoes)} opção(ões)"


def test_o_catalogo_tem_46_perguntas_sendo_7_de_calibracao():
    """São 7 de Calibração porque existem 7 consumidores — nem um a mais.

    A sétima nasceu com o consumidor no mesmo passo (a antecedência da cobrança a receber).
    Esse é o único caminho legítimo para este número subir.
    """
    assert len(PERGUNTAS) == 46
    assert sum(1 for p in PERGUNTAS if p.classe == CALIBRACAO) == 7


def test_nucleo_aponta_para_perguntas_que_existem_e_nenhuma_e_calibracao():
    """'Em quanto tempo eu te aviso?' é irrespondível antes de ter visto um briefing."""
    assert len(NUCLEO) == 6
    for key in NUCLEO:
        assert key in POR_KEY, f"núcleo cita {key}, que não está no catálogo"
        assert POR_KEY[key].classe == RETRATO


def test_toda_calibracao_tem_gancho_de_ausencia():
    for p in PERGUNTAS:
        if p.classe == CALIBRACAO:
            assert p.gancho and p.gancho.startswith("briefing.ausencia."), (
                f"{p.key} é Calibração e precisa vir colada à ausência que a motivou"
            )


def test_a_guarda_recusa_calibracao_sem_consumidor():
    """A guarda precisa ser executável sobre um catálogo arbitrário, não só sobre o real."""
    with pytest.raises(CatalogoError, match="consumidor"):
        catalog.verificar(
            (
                Pergunta(
                    key="ritmo.qualquer", classe=CALIBRACAO, eixo="ritmo",
                    texto="?", formato=FORMATO_ESCOLHA,
                    opcoes=(Opcao("a", 1), Opcao("b", 2)),
                ),
            )
        )


def test_a_guarda_recusa_consome_inexistente():
    with pytest.raises(CatalogoError, match="LIMIARES_PADRAO"):
        catalog.verificar(
            (
                Pergunta(
                    key="ritmo.qualquer", classe=CALIBRACAO, eixo="ritmo",
                    texto="?", formato=FORMATO_ESCOLHA,
                    opcoes=(Opcao("a", 1), Opcao("b", 2)),
                    consome="card_parado_dais",  # typo de propósito
                    gancho="briefing.ausencia.comercial.card.parado",
                ),
            )
        )


def test_todo_gancho_de_calibracao_aponta_para_um_kind_que_existe():
    """O gancho é o que cola a pergunta à ausência que a motivou, e é string livre nos dois
    lados. Renomear um `kind` sem renomear o gancho não quebra teste nenhum: a pergunta
    simplesmente nunca mais aparece, e o dono nunca calibra aquela regra. Silêncio perfeito, do
    mesmo feitio que a guarda de `consome` existe para impedir.
    """
    import re
    from pathlib import Path

    from app.modules.vima import absences

    fonte = Path(absences.__file__).read_text(encoding="utf-8")
    kinds = set(re.findall(r'kind="([^"]+)"', fonte))
    assert kinds, "a varredura não achou kind nenhum — o gate ficaria verde por vacuidade"

    for p in PERGUNTAS:
        if p.classe != CALIBRACAO:
            continue
        alvo = p.gancho.removeprefix("briefing.ausencia.")
        assert alvo in kinds, f"{p.key} aponta para o kind inexistente '{alvo}'"
