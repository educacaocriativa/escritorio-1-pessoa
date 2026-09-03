"""O mascaramento de nomes da Vima não pode engolir o português.

O caso medido antes da correção, com "Bar do Porto", "Casa Nova Reformas" e "Sol Nascente Ltda"
na carteira:

    pergunta : quanto gastei no bar esse mes? preciso pagar a casa e comprar sol e sombra
    Claude ve: quanto gastei no [PESSOA_3] esse mes? preciso pagar a [PESSOA_1] e comprar
               [PESSOA_2] e sombra

Três marcadores numa pergunta que não fala de ninguém. O teste tem dois lados e os dois importam:
as palavras comuns sobrevivem **e** os nomes continuam mascarados. Um lado sozinho deixaria passar
a correção preguiçosa (desligar o mascaramento de componentes) ou a correção nula.
"""
from __future__ import annotations

from app.core.anonymizer import AnonymizationContext
from app.modules.vima.palavras_comuns import componentes_mascaraveis

CARTEIRA = ["Bar do Porto", "Casa Nova Reformas", "Sol Nascente Ltda"]


def _como_a_claude_ve(texto: str, nomes: list[str]) -> str:
    """Reproduz o que `pergunta.responder` faz: nomes completos e depois componentes."""
    privacy = AnonymizationContext()
    return privacy.mask_literals(
        texto, nomes + list(componentes_mascaraveis(nomes)), label="PESSOA"
    )


def test_palavra_comum_sobrevive_na_pergunta() -> None:
    pergunta = "quanto gastei no bar esse mes? preciso pagar a casa e comprar sol e sombra"
    visto = _como_a_claude_ve(pergunta, CARTEIRA)
    assert visto == pergunta, f"a pergunta chegou mutilada: {visto}"


def test_termo_societario_nao_vira_marcador() -> None:
    """`Ltda` era o pior caso: uma empresa na carteira mascarava "ltda" em toda pergunta."""
    pergunta = "preciso emitir nota para uma ltda ou posso emitir para o CNPJ direto?"
    assert _como_a_claude_ve(pergunta, CARTEIRA) == pergunta


def test_o_nome_completo_continua_sempre_mascarado() -> None:
    """A garantia. Não depende da lista de palavras comuns e não pode depender."""
    pergunta = "quanto o Bar do Porto me deve? e a Casa Nova Reformas?"
    visto = _como_a_claude_ve(pergunta, CARTEIRA)
    assert "Bar do Porto" not in visto
    assert "Casa Nova Reformas" not in visto
    assert "[PESSOA_" in visto


def test_componente_incomum_continua_mascarado() -> None:
    """Mencionar o cliente pelo sobrenome ainda protege — é para isso que os componentes existem."""
    visto = _como_a_claude_ve("o Porto pagou? e o Nascente?", CARTEIRA)
    assert "Porto" not in visto and "Nascente" not in visto


def test_nome_de_pessoa_nao_e_afetado_pela_lista() -> None:
    """O caso do docstring de `_nomes_conhecidos` ("fale com João") tem de continuar valendo."""
    nomes = ["João da Silva Pereira"]
    componentes = componentes_mascaraveis(nomes)
    assert {"João", "Silva", "Pereira"} <= componentes
    assert "da" not in componentes  # conector, e abaixo do tamanho mínimo
    assert "fale com [PESSOA_1]" == _como_a_claude_ve("fale com joão", nomes)


def test_acento_e_pontuacao_nao_escapam_da_lista() -> None:
    """Sem normalizar, "Serviços" e "Cia." passariam por cima de "servicos" e "cia"."""
    assert componentes_mascaraveis(["Alfa Serviços Ltda"]) == {"Alfa"}
    assert componentes_mascaraveis(["Beta & Cia."]) == {"Beta"}


def test_nome_inteiramente_comum_ainda_e_protegido_como_nome_completo() -> None:
    """O limite honesto desta escolha, escrito.

    Um cliente chamado "Casa Nova" perde a proteção do componente isolado — de propósito, porque
    "casa" e "nova" numa pergunta quase nunca falam dele. O nome completo continua protegido, e é
    essa a garantia que a Política de Privacidade descreve.
    """
    nomes = ["Casa Nova"]
    assert componentes_mascaraveis(nomes) == set()
    visto = _como_a_claude_ve("quanto a Casa Nova me deve?", nomes)
    assert "Casa Nova" not in visto and "[PESSOA_1]" in visto
