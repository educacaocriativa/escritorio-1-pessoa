"""O primitivo de busca textual — escape de curinga.

Este é o teste que o #125 provou ser necessário: a implementação ingênua (`f"%{termo}%"`) passa em
todos os OUTROS testes de busca, porque casar texto comum funciona. Só um caso com `%` denuncia.
"""
from app.core.textsearch import ESCAPE, escapa_curinga, padrao_ilike


def test_escapa_porcento_e_underline():
    assert escapa_curinga("100%") == "100\\%"
    assert escapa_curinga("a_b") == "a\\_b"


def test_texto_comum_passa_intacto():
    assert escapa_curinga("Ana Souza") == "Ana Souza"


def test_barra_invertida_e_escapada_primeiro():
    """Se a barra fosse escapada por último, ela duplicaria as barras recém-inseridas e o `%`
    voltaria a ser curinga vivo precedido de barra literal."""
    assert escapa_curinga("\\%") == "\\\\\\%"


def test_padrao_envolve_em_curingas_de_verdade():
    """As pontas SÃO curinga — é isso que faz a busca casar no meio da palavra."""
    assert padrao_ilike("ana") == "%ana%"
    assert padrao_ilike("50%") == "%50\\%%"


def test_escape_e_a_barra_invertida():
    """O valor tem que casar com o que os `replace` inserem, senão o escape não acontece."""
    assert ESCAPE == "\\"
